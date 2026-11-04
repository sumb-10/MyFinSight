"""M4-05 공통 구성 함수 construct(). 네 호출 위치(백테스트 시작·과거 리밸런싱·현재 구성·모의투자)가 모두 이 함수를 쓴다.

흐름: 시장모형(d 이전 자료) → 기준 비중 4종 → 뉴스 창 [d−N, d) → 충분하면 뷰(LLM) + 코드 검사 → Black-Litterman.
뉴스가 부족하거나 뉴스 반영이 꺼져 있으면 BL 없이 기준 비중만 (fallback=True, K6). 종목 재선정은 이 함수 밖에서 한다 (K8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from backend.analysis.common.llm import LlmClient
from backend.analysis.m2_data.market_data import MarketDataView
from backend.analysis.m2_data.news import EvidenceWindow
from backend.analysis.m4_portfolio.black_litterman import build_bl
from backend.analysis.m4_portfolio.market_model import build_market_model
from backend.analysis.m4_portfolio.views import generate_views
from backend.analysis.settings import AnalysisSettings
from backend.pipeline.descriptor import Descriptor

Mode = Literal["start", "rebalance", "current", "paper"]


@dataclass
class ConstructResult:
    as_of: str
    mode: Mode
    market_model: dict[str, Any]
    baselines: dict[str, Any]  # BaselinePortfolios dict (templates + chosen_baseline)
    bl_portfolios: list[dict[str, Any]] = field(default_factory=list)
    view_sets: list[dict[str, Any]] = field(default_factory=list)
    evidence: EvidenceWindow | None = None
    fallback: bool = False
    fallback_reason_ko: str | None = None
    params: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def tickers(self) -> list[str]:
        return list(self.market_model["tickers"])

    @property
    def baseline(self) -> dict[str, Any]:
        return next(p for p in self.baselines["portfolios"] if p["id"] == self.baselines["chosen_baseline"])

    @property
    def baseline_weights(self) -> dict[str, float]:
        return dict(self.baseline["weights"])

    @property
    def applied_bl(self) -> list[dict[str, Any]]:
        """뷰가 실제로 반영된 BL 세트 (최적화가 실패해 기준 비중을 유지한 세트는 뺀다)."""
        return [p for p in self.bl_portfolios if p.get("views_applied")]

    @property
    def chosen_weights(self) -> dict[str, float]:
        """리밸런싱·모의투자가 적용할 비중: 뷰가 반영된 첫 BL 세트가 있으면 그것, 없으면 기준 비중."""
        ap = self.applied_bl
        return dict(ap[0]["weights"]) if ap else self.baseline_weights

    def evidence_summary(self) -> dict[str, Any] | None:
        return self.evidence.summary() if self.evidence else None


def construct(
    view: MarketDataView,
    tickers: list[str],
    req: dict[str, Any],
    intent: dict[str, Any],
    settings: AnalysisSettings,
    llm: LlmClient,
    desc: Descriptor,
    *,
    mode: Mode,
    n_view_sets: int | None = None,
    views_per_set: int | None = None,
    stage_tag: str | None = None,
    id_prefix: str = "bl",
    name_prefix: str = "BL 타겟",
) -> ConstructResult:
    ns = settings.news
    n_sets = n_view_sets if n_view_sets is not None else (ns.view_sets_at_start if mode in ("start", "current") else ns.view_sets_at_rebalance)
    per_set = views_per_set if views_per_set is not None else ns.views_per_set
    model, base = build_market_model(view, tickers, req, desc, settings, request_id=req["request_id"])
    tk = model["tickers"]
    res = ConstructResult(as_of=str(view.as_of), mode=mode, market_model=model, baselines=base)
    res.warnings += [n for n in model.get("notes", []) if n.startswith("dropped") or n.startswith("caps allow")
                     or (n.startswith("market cap missing for") and _cap_floored(model, base))]  # fmt: skip
    if not intent["news_tilt"]["enabled"]:
        res.fallback, res.fallback_reason_ko = True, "뉴스 반영을 꺼서 기준 비중을 사용"
        return res
    ev = view.news_window(tk)
    res.evidence = ev
    if not ev.enough:
        res.fallback = True
        res.fallback_reason_ko = f"뉴스·공시가 있는 종목 {ev.n_tickers_with_evidence}개 < 최소 {ev.min_tickers}개: 뷰를 만들지 않고 기준 비중을 사용"
        res.warnings.append(f"{view.as_of}: {res.fallback_reason_ko}")
        return res
    wb = {t: res.baseline_weights[t] for t in tk}
    sets, w = generate_views(view, tk, model, wb, intent, desc, settings, llm, ev, n_sets=n_sets, views_per_set=per_set,
                             stage_tag=stage_tag or f"09_views_news_{view.as_of}")  # fmt: skip
    res.warnings += w
    if not sets:
        res.fallback, res.fallback_reason_ko = True, "유효한 뷰가 하나도 남지 않아 기준 비중을 사용"
        res.warnings.append(f"{view.as_of}: {res.fallback_reason_ko}")
        return res
    ports, w2, params = build_bl(model, base, sets, req, intent, desc, settings, id_prefix=id_prefix, name_prefix=name_prefix)
    res.bl_portfolios, res.view_sets, res.params = ports, sets, params
    res.warnings += w2
    if ports and not res.applied_bl:  # 모든 세트가 실패했을 때만 기준 비중 유지 (세트 하나 실패로 전체를 fallback 이라 부르지 않는다)
        res.fallback = True
        res.fallback_reason_ko = "뉴스 뷰 비중 최적화가 수렴하지 않아 기준 비중을 사용"
    return res


def _cap_floored(model: dict[str, Any], base: dict[str, Any]) -> bool:
    """시가총액 자료가 없어 시가총액비중이 0 인 종목이 시가총액비중 구성에서 다른 종목보다 적게 담겼나 → 사용자 공지 (025: 필수 포함 XOM 이
    최소 비중 1% 에 남는 몫만 더한 1.4~1.7%, 더 작은 CVX 는 상한 25% 였는데 공지가 없었다). 모두 비면 동일비중으로 돌아가고(0 인 종목 없음),
    모두 상한에 걸려 비중이 같으면 회사 크기와 무관하게 같은 비중이라 알릴 것이 없다."""
    zero = [t for t, w in (model.get("cap_weights") or {}).items() if not w]
    mc = next((p["weights"] for p in base.get("portfolios", []) if p.get("id") == "market_cap"), None)
    return bool(zero and mc) and min(mc.get(t, 0.0) for t in zero) < max(mc.values()) - 1e-6
