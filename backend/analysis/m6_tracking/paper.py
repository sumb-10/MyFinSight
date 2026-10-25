"""Module6 모의투자 (M6-01~04). docs/Module6.md 의 규칙을 그대로 코드로 옮겼다.

- 시작은 preview → create 두 단계. create 는 preview 와 같은 계산을 다시 하므로 확인한 비중 = 적용 비중.
- 시작일: 두 시장이 모두 거래한 날, 자료 마감(ceiling) 이하, 리포트 기준일 이상. 거래일이 아니면 앞의 거래일로 옮기고 경고.
- 시작일 > 리포트 기준일이면 그 날 자료로 construct(mode="paper") 를 다시 돌려 시작 비중을 만든다 (종목은 그대로, K8).
- 하루 처리 순서: 보유 평가 → 적립(해당일) → 리밸런싱(해당일) → 수수료 → 최종 평가 한 줄. 체결은 그날 종가(USD 환산),
  추정(공분산·뉴스)은 그 전날까지 자료 (D4). 휴장일 가격 유지는 Module2 패널 규칙.
- 운용 수익률은 단위가격(unit price) 기준: 적립은 그날 단위가격으로 새 단위를 발행 → 납입금이 수익으로 잡히지 않는다.
  비교지수도 같은 자본·적립로 평가한다.
- 필수 가격·환율이 없으면 그 날 기록을 만들지 않고 update_status=delayed 로 둔다 (가짜 스냅샷 없음).
- 중지 중에는 평가·리밸런싱을 하지 않는다. 재개하면 중지 기간은 비워 두고, 지나간 리밸런싱은 skipped 로 기록한다.
- 같은 날짜를 두 번 처리하지 않는다 (last_snapshot_date 이후만, 스냅샷 날짜 집합으로 한 번 더 확인).
"""

from __future__ import annotations

import copy
import datetime as dt
import logging
from dataclasses import asdict, dataclass
from typing import Any, Literal

import pandas as pd

from backend.analysis.common.store import JsonStore, PaperStore, new_paper_id
from backend.analysis.errors import Conflict, DataMissing, NotFound, RequestInvalid
from backend.analysis.m2_data import descriptor as D
from backend.analysis.m2_data.market_data import MarketData, MarketDataView
from backend.analysis.m4_portfolio.construct import construct
from backend.analysis.m5_backtest_report.backtest_engine import contribution_dates
from backend.analysis.settings import AnalysisSettings

log = logging.getLogger(__name__)

TEMPLATES = ("equal_weight", "market_cap", "inverse_volatility", "min_variance")
TEMPLATE_KO = {"equal_weight": "동일비중", "market_cap": "시가총액비중", "inverse_volatility": "역변동성", "min_variance": "최소분산"}
Kind = Literal["template", "black_litterman", "cash_blend"]


def _d(x: Any) -> dt.date:
    return pd.Timestamp(x).date()


def _now() -> str:
    return dt.datetime.now(dt.UTC).astimezone().isoformat(timespec="seconds")


# ───────────────────────── 전략 해석 ─────────────────────────
@dataclass(frozen=True)
class Strategy:
    id: str
    kind: Kind
    template: str | None
    cash_ratio: float
    name_ko: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_strategy(strategy_id: str, results: dict[str, Any]) -> Strategy:
    """리포트 안 포트폴리오 id → 전략 종류. wf_·fwd_ 접두는 같은 전략의 다른 평가 방식이라 벗긴다."""
    sid = strategy_id
    cash_ratio = 0.0
    if sid.startswith("dd_match_"):  # 라운드 5: 낙폭 맞춤안 — 백테스트 결과의 정식 후보. 기준이 템플릿이면 그 비중 × (1−c), BL 이면 BL 비중 × (1−c)
        blk = next((p for p in results.get("backtest", {}).get("portfolios", []) if p.get("id") == sid), None)
        if blk is None:
            raise NotFound(f"리포트에 낙폭 맞춤안 {sid} 이 없습니다")
        cash_ratio = float(blk.get("cash_ratio") or 0.0)
        base = str(blk.get("base_id") or sid[len("dd_match_"):])
        core = base[3:] if base.startswith("wf_") else base
        core = core[4:] if core.startswith("fwd_") else core
        name = blk.get("name_ko") or sid
        if core in TEMPLATES:
            return Strategy(sid, "cash_blend", core, cash_ratio, name)
        if core.startswith("bl"):
            return Strategy(sid, "cash_blend", None, cash_ratio, name)
        raise RequestInvalid(f"낙폭 맞춤안의 기준 비중 {base} 을 알 수 없습니다")
    if sid.startswith("cash_blend_"):
        base = sid[len("cash_blend_"):]
        alt = next((a for a in results.get("validation", {}).get("alternatives", []) if a.get("id") == sid), None)
        if alt is None:
            raise NotFound(f"리포트에 현금 혼합안 {sid} 이 없습니다")
        cash_ratio = float(alt.get("cash_ratio") or 0.0)
        if base not in TEMPLATES:
            raise RequestInvalid(f"현금 혼합안의 기준 비중 {base} 을 알 수 없습니다")
        return Strategy(sid, "cash_blend", base, cash_ratio, f"현금 혼합안: {TEMPLATE_KO[base]} × {1 - cash_ratio:.0%} + 현금 {cash_ratio:.0%}")
    core = sid[3:] if sid.startswith("wf_") else sid
    core = core[4:] if core.startswith("fwd_") else core
    if core in TEMPLATES:
        return Strategy(sid, "template", core, 0.0, TEMPLATE_KO[core])
    if core.startswith("bl"):
        return Strategy(sid, "black_litterman", None, 0.0, "뉴스 반영 Black-Litterman (기준 비중 + 뉴스 뷰)")
    raise RequestInvalid(f"전략 {sid} 을 해석할 수 없습니다")


def strategy_options(results: dict[str, Any]) -> list[dict[str, Any]]:
    """리포트에서 고를 수 있는 전략 목록 (검증 결과·추천·선택안 표시)."""
    v = results.get("validation", {})
    rec = (v.get("recommended") or {}).get("id")
    chosen = v.get("chosen_id")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in [*v.get("results", []), *v.get("alternatives", [])]:
        sid = r.get("id")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        try:
            st = resolve_strategy(sid, results)
        except (RequestInvalid, NotFound):
            continue
        out.append({**st.to_dict(), "status": r.get("status"), "recommended": sid == rec, "chosen": sid == chosen,
                    "n_fail": r.get("n_fail"), "n_warn": r.get("n_warn")})  # fmt: skip
    out.sort(key=lambda o: (not o["chosen"], not o["recommended"], o["id"]))
    return out


# ───────────────────────── 거래 ─────────────────────────
def trade_to_target(holdings: dict[str, float], cash: float, prices: dict[str, float], target_w: dict[str, float], cash_w: float,
                    commission_bps: float) -> tuple[dict[str, float], float, list[dict[str, Any]], float, float]:  # fmt: skip
    """현재 보유 → 목표 비중으로 가상 체결 (그날 USD 종가, 소수 주식 허용). 수수료는 거래대금 × bps, 현금에서 뺀다.

    투자 가능 금액을 (1 − cash_w) × 총액 ÷ (1 + bps) 로 잡아 수수료 뒤에도 현금이 음수가 되지 않게 한다.
    돌려주는 값: (보유, 현금, 거래 목록, 수수료 합, 회전율=매도·매수 대금 합 ÷ 2 ÷ 총액).
    """
    value = sum(holdings.get(t, 0.0) * p for t, p in prices.items()) + cash
    if value <= 0:
        return holdings, cash, [], 0.0, 0.0
    rate = commission_bps / 1e4
    investable = value * max(0.0, 1.0 - cash_w) / (1.0 + rate)
    tot_w = sum(target_w.values()) or 1.0
    target_usd = {t: investable * (w / tot_w) for t, w in target_w.items()}
    new = dict(holdings)
    trades: list[dict[str, Any]] = []
    fees = 0.0
    traded = 0.0
    for t in sorted(set(prices) | set(target_usd)):
        p = prices.get(t)
        if p is None or p <= 0:
            continue
        cur = new.get(t, 0.0) * p
        diff = target_usd.get(t, 0.0) - cur
        if abs(diff) < 0.01:
            continue
        shares = diff / p
        fee = abs(diff) * rate
        new[t] = max(0.0, new.get(t, 0.0) + shares)
        cash -= diff + fee
        fees += fee
        traded += abs(diff)
        trades.append({"ticker": t, "side": "buy" if diff > 0 else "sell", "shares": round(abs(shares), 6), "price": round(p, 6), "value_usd": round(abs(diff), 2)})
    new = {t: s for t, s in new.items() if s > 1e-12}
    return new, max(cash, 0.0), trades, round(fees, 4), round(traded / 2 / value, 6)


def weights_of(holdings: dict[str, float], cash: float, prices: dict[str, float]) -> tuple[dict[str, float], float, float]:
    """(종목 비중, 보유 평가액, 총액)."""
    vals = {t: s * prices[t] for t, s in holdings.items() if t in prices}
    hv = sum(vals.values())
    total = hv + cash
    return ({t: round(v / total, 6) for t, v in vals.items()} if total > 0 else {}), round(hv, 2), round(total, 2)


def rebalance_due_dates(rule: dict[str, Any], calendar: pd.DatetimeIndex, start: dt.date, *, two_week_days: int = 10) -> list[dt.date]:
    """시작일 이후 리밸런싱 날짜 (시작일 자체는 최초 매수라 제외). 백테스트와 같은 '기간 첫 거래일' 규칙, 마지막 날도 그대로 둔다."""
    cal = calendar[calendar >= pd.Timestamp(start)]
    if len(cal) == 0 or not rule.get("enabled", True) or int(rule.get("count", 0)) == 0:
        return []
    count = int(rule["count"])
    if rule["unit"] == "2w":
        return [_d(x) for x in cal[:: two_week_days * count][1:]]
    key = {"1m": lambda t: (t.year, t.month), "1q": lambda t: (t.year, (t.month - 1) // 3), "6m": lambda t: (t.year, (t.month - 1) // 6), "1y": lambda t: (t.year,)}[rule["unit"]]
    firsts, seen = [], set()
    for ts in cal:
        k = key(ts)
        if k not in seen:
            seen.add(k)
            firsts.append(ts)
    return [_d(x) for x in firsts[::count][1:]]


# ───────────────────────── 서비스 ─────────────────────────
class PaperService:
    def __init__(self, store: JsonStore, repo: Any, md: MarketData, llm: Any, settings: AnalysisSettings) -> None:
        self.store = store
        self.papers = PaperStore(store)
        self.repo = repo
        self.md = md
        self.llm = llm
        self.s = settings

    # ── 리포트 묶음 ──
    def _bundle(self, report_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        row = self.repo.get_report(report_id)
        if not row:
            raise NotFound(f"리포트 {report_id} 이 없습니다")
        run_id = row.get("run_id") or report_id
        art = self.repo.get_run_artifact(run_id)
        if not art:
            raise NotFound(f"리포트 {report_id} 의 결과 묶음이 없습니다")
        return row, art["results"]

    def _desc(self, as_of: dt.date, req: dict[str, Any]):
        ms = self.s.market
        desc, _info, _w = D.load_for(as_of, req["constraints"]["universe"], ms.markets, processed_dir=ms.descriptor_dir or D.PROCESSED, universe_file=ms.descriptor_universe)
        return desc

    # ── 비중 ──
    @staticmethod
    def _report_weights(strategy: Strategy, results: dict[str, Any]) -> tuple[dict[str, float], float]:
        """리포트 기준일의 현재 구성(10f)에서 전략의 비중을 꺼낸다."""
        fw = results["portfolio"]["forward"]
        if strategy.kind == "black_litterman" or (strategy.kind == "cash_blend" and strategy.template is None):
            w = dict(fw.get("chosen_weights") or {})
            cash = 0.0
            for p in fw.get("portfolios", []):
                if p.get("weights") == w:
                    cash = float(p.get("cash_weight") or 0.0)
        else:
            tpl = next((t for t in fw["templates"] if t["id"] == strategy.template), None)
            if tpl is None:
                raise NotFound(f"리포트 현재 구성에 {strategy.template} 비중이 없습니다")
            w = dict(tpl["weights"])
            cash = float(tpl.get("cash_weight") or 0.0)
        if strategy.kind == "cash_blend" and strategy.cash_ratio > 0:
            w = {t: x * (1 - strategy.cash_ratio) for t, x in w.items()}
            cash = 1.0 - sum(w.values())
        return w, cash

    def _construct_weights(self, strategy: Strategy, view: MarketDataView, tickers: list[str], req: dict[str, Any], intent: dict[str, Any],
                           *, stage_tag: str) -> tuple[dict[str, float], float, dict[str, Any]]:  # fmt: skip
        """시작일/리밸런싱일 자료로 전략 비중을 다시 만든다 (종목 유지). 템플릿·현금혼합은 LLM 을 부르지 않는다."""
        desc = self._desc(view.as_of, req)
        req2, intent2 = copy.deepcopy(req), copy.deepcopy(intent)
        info: dict[str, Any] = {"fallback": False, "views": [], "evidence_window": None, "warnings": []}
        if strategy.kind == "black_litterman" or (strategy.kind == "cash_blend" and strategy.template is None):
            res = construct(view, tickers, req2, intent2, self.s, self.llm, desc, mode="paper", n_view_sets=1, stage_tag=stage_tag, id_prefix="paper_bl", name_prefix="모의투자 BL")
            info["warnings"] = list(res.warnings)
            info["fallback"] = bool(res.fallback)
            if res.fallback:
                info["warnings"].append(res.fallback_reason_ko or "기준 비중 사용")
            if res.evidence:
                ev = res.evidence.summary()
                info["evidence_window"] = {"start": str(ev["window"][0]), "end": str(ev["window"][1]), "n_articles": int(ev["n_articles"]), "n_tickers_with_news": int(ev["n_tickers_with_news"])} if isinstance(ev.get("window"), (list, tuple)) else None
            if res.bl_portfolios:
                p = res.bl_portfolios[0]
                info["views"] = [{"summary_ko": v.get("summary_ko") or v.get("text_ko") or str(v.get("view", "")), "evidence_ids": list(v.get("evidence_ids", [])), "confidence": float(v.get("confidence", 0) or 0)}
                                 for v in (res.view_sets[0].get("views", []) if res.view_sets else [])]  # fmt: skip
                w, cash = dict(p["weights"]), float(p.get("cash_weight") or 0.0)
            else:
                w, cash = dict(res.baseline_weights), float(res.baseline.get("cash_weight") or 0.0)
            if strategy.kind == "cash_blend" and strategy.cash_ratio > 0:  # 낙폭 맞춤안(BL 기준): 뷰 비중 × (1−c)
                w = {t: x * (1 - strategy.cash_ratio) for t, x in w.items()}
                cash = 1.0 - sum(w.values())
            return w, cash, info
        intent2["news_tilt"]["enabled"] = False
        req2["strategy_preference"]["baseline_weighting"] = strategy.template
        req2["strategy_preference"]["use_news_tilt"] = False
        res = construct(view, tickers, req2, intent2, self.s, self.llm, desc, mode="paper", stage_tag=stage_tag)
        info["warnings"] = [w for w in res.warnings]
        tpl = next((p for p in res.baselines["portfolios"] if p["id"] == strategy.template), None)
        if tpl is None:
            raise DataMissing(f"{view.as_of} 에 {strategy.template} 비중을 만들 수 없습니다")
        w, cash = dict(tpl["weights"]), float(tpl.get("cash_weight") or 0.0)
        if strategy.kind == "cash_blend":
            w = {t: x * (1 - strategy.cash_ratio) for t, x in w.items()}
            cash = 1.0 - sum(w.values())
        return w, cash, info

    # ── 시작 ──
    def _plan(self, report_id: str, *, strategy_id: str | None, start_date: dt.date | str | None, initial_amount: float | None,
              currency: str | None, monthly_contribution: float | None) -> dict[str, Any]:  # fmt: skip
        row, results = self._bundle(report_id)
        req, intent = results["request"], results["intent"]
        v = results.get("validation", {})
        sid = strategy_id or v.get("chosen_id") or (v.get("recommended") or {}).get("id")
        if not sid:
            raise RequestInvalid("리포트에 선택할 전략이 없습니다")
        strategy = resolve_strategy(sid, results)
        warnings: list[str] = []
        report_as_of = dt.date.fromisoformat(str(req["derived"]["as_of"]))
        markets = list(req["derived"].get("markets") or self.s.market.markets)
        ceiling = self.md.common_trading_day_on_or_before(self.md.ceiling, markets)
        want = dt.date.fromisoformat(start_date) if isinstance(start_date, str) else (start_date or ceiling)
        if want > ceiling:
            raise RequestInvalid(f"시작일 {want} 의 자료가 아직 없습니다. 가능한 가장 늦은 날은 {ceiling} 입니다",
                                 details={"fields": {"start_date": f"{ceiling} 이하"}, "latest": str(ceiling)})  # fmt: skip
        start = self.md.common_trading_day_on_or_before(want, markets)
        if start != want:
            warnings.append(f"{want} 은 거래일이 아니라 {start} 로 옮김")
        if start < report_as_of:
            raise RequestInvalid(f"시작일 {start} 이 리포트 기준일 {report_as_of} 보다 이릅니다. 기준일 이후 날짜로 시작해 주세요",
                                 details={"fields": {"start_date": f"{report_as_of} 이상"}})  # fmt: skip
        tickers = [s["ticker"] for s in results["selection"]["selected"]] if isinstance(results.get("selection"), dict) and "selected" in results["selection"] else list(results["portfolio"]["forward"]["market_model"]["tickers"])
        bench = results["portfolio"]["backtest_spec"]["benchmark"]
        cap = req["capital"]
        cur = (currency or cap["currency"]).upper()
        amount = float(initial_amount if initial_amount is not None else cap["initial_amount"])
        if amount <= 0:
            raise RequestInvalid("가상 초기자본은 0보다 커야 합니다", details={"fields": {"initial_amount": "0보다 커야 합니다"}})
        monthly = float(monthly_contribution if monthly_contribution is not None else cap.get("monthly_contribution", 0) or 0)
        view = self.md.view(start)
        fx = view.fx_on_or_before(start)
        rate = float(fx.rate) if cur == "KRW" else 1.0
        usd = round(amount / rate, 2)
        rep_w, rep_cash = self._report_weights(strategy, results)
        reconstructed = start > report_as_of
        info: dict[str, Any] = {"fallback": False, "views": [], "evidence_window": None, "warnings": []}
        if reconstructed:
            w, cash_w, info = self._construct_weights(strategy, view, tickers, req, intent, stage_tag=f"09_views_news_{start}_paper")
            warnings += info["warnings"]
        else:
            w, cash_w = rep_w, rep_cash
        w = {t: round(float(x), 6) for t, x in w.items() if float(x) > 0}
        diff = [{"ticker": t, "report": round(rep_w.get(t, 0.0), 4), "start": round(w.get(t, 0.0), 4), "delta": round(w.get(t, 0.0) - rep_w.get(t, 0.0), 4)}
                for t in sorted(set(rep_w) | set(w), key=lambda t: -(w.get(t, 0.0)))]  # fmt: skip
        prices = view.panel(list(w), start, start, required=[*w, bench], benchmarks=[bench])[0].iloc[-1]
        alloc = [{"ticker": t, "weight": x, "usd": round(usd * x, 2), "krw": round(usd * x * float(fx.rate)), "price_usd": round(float(prices[t]), 4)} for t, x in sorted(w.items(), key=lambda kv: -kv[1])]
        rb = req["derived"]["rebalance_rule"]
        return {"report_id": report_id, "run_id": row.get("run_id") or report_id, "report_as_of": str(report_as_of), "strategy": strategy.to_dict(),
                "strategy_options": strategy_options(results), "start_date": str(start), "data_ceiling": str(ceiling), "reconstructed_at_start": reconstructed,
                "initial_capital": {"amount": amount, "currency": cur, "usd": usd, "fx_rate": float(fx.rate), "fx_date": str(fx.date)},
                "contribution": {"enabled": monthly > 0, "monthly_amount": monthly, "currency": cur, "day": int(cap.get("contribution_day") or 25)},
                "rebalance_rule": {"count": int(rb["count"]), "unit": rb["unit"]}, "benchmark": bench, "tickers": [t for t in tickers if t in w] or list(w),
                "weights": w, "cash_weight": round(cash_w, 6), "report_weights": rep_w, "weight_diff": diff, "allocation": alloc,
                "construct_info": info, "warnings": warnings, "_results": results, "_req": req, "_intent": intent, "_prices": {t: float(prices[t]) for t in [*w, bench]}}  # fmt: skip

    def preview(self, report_id: str, **kw: Any) -> dict[str, Any]:
        plan = self._plan(report_id, **{k: kw.get(k) for k in ("strategy_id", "start_date", "initial_amount", "currency", "monthly_contribution")})
        return {k: v for k, v in plan.items() if not k.startswith("_")}

    def create(self, report_id: str, **kw: Any) -> dict[str, Any]:
        plan = self._plan(report_id, **{k: kw.get(k) for k in ("strategy_id", "start_date", "initial_amount", "currency", "monthly_contribution")})
        req, intent = plan["_req"], plan["_intent"]
        start = dt.date.fromisoformat(plan["start_date"])
        usd = plan["initial_capital"]["usd"]
        prices = {t: p for t, p in plan["_prices"].items() if t in plan["weights"]}
        holdings, cash, trades, fees, turnover = trade_to_target({}, usd, prices, plan["weights"], plan["cash_weight"], self.s.backtest.commission_bps)
        weights, hv, total = weights_of(holdings, cash, prices)
        bench_px = plan["_prices"][plan["benchmark"]]
        pid = new_paper_id()
        now = _now()
        doc = {"schema_version": 1, "paper_id": pid, "report_id": plan["report_id"], "run_id": plan["run_id"], "strategy_id": plan["strategy"]["id"], "strategy": plan["strategy"],
               "name_ko": plan["strategy"]["name_ko"], "start_date": plan["start_date"], "report_as_of": plan["report_as_of"], "reconstructed_at_start": plan["reconstructed_at_start"],
               "initial_capital": plan["initial_capital"], "contribution": plan["contribution"], "rebalance_rule": plan["rebalance_rule"],
               "constraints_snapshot": {"request": {k: req[k] for k in ("request_id", "profile", "capital", "horizon", "risk", "constraints", "strategy_preference", "natural_language", "derived")},
                                        "intent": intent, "commission_bps": self.s.backtest.commission_bps},
               "benchmark": plan["benchmark"], "benchmark_start_px": bench_px, "tickers": list(plan["weights"]), "start_weights": plan["weights"],
               "state": {"holdings": {t: round(s, 8) for t, s in holdings.items()}, "cash_usd": round(cash, 4), "last_snapshot_date": plan["start_date"], "last_rebalance_date": plan["start_date"],
                         "n_rebalances": 0, "units": usd, "unit_price_peak": total / usd, "benchmark_units": usd / bench_px, "contributions_total_usd": 0.0,
                         "target_weights": plan["weights"], "cash_weight": plan["cash_weight"], "update_status": "ok", "delayed_reason_ko": None, "last_refresh_at": now},
               "status": "active", "created_at": now, "stopped_at": None, "resumed_at": None,
               "history": [{"at": now, "event": "started", "note": f"{plan['start_date']} 시작, {plan['strategy']['name_ko']}"}], "warnings": plan["warnings"]}  # fmt: skip
        self.papers.save(doc)
        self.papers.append_rebalance(pid, {"date": plan["start_date"], "seq": 0, "kind": "initial", "before_weights": {}, "target_weights": plan["weights"], "applied_weights": weights,
                                           "trades": trades, "commission_usd": fees, "turnover": turnover, "views": plan["construct_info"]["views"],
                                           "evidence_window": plan["construct_info"]["evidence_window"], "fallback": bool(plan["construct_info"]["fallback"]), "skipped": False,
                                           "max_tilt": None, "warnings": list(plan["construct_info"]["warnings"]), "note_ko": "최초 매수"})  # fmt: skip
        self.papers.append_snapshot(pid, {"date": plan["start_date"], "value_usd": total, "cash_usd": round(cash, 2), "holdings_value_usd": hv, "weights": weights,
                                          "drawdown": round(total / usd - 1, 6) if total < usd else 0.0, "return_since_start": round(total / usd - 1, 6), "unit_price": round(total / usd, 8),
                                          "contribution_usd": 0.0, "contributions_total_usd": 0.0, "benchmark_value_usd": usd, "benchmark_return_since_start": 0.0,
                                          "fx_rate": plan["initial_capital"]["fx_rate"], "status": "ok", "warnings": []})  # fmt: skip
        return self.detail(pid)

    # ── 갱신 ──
    def refresh(self, paper_id: str) -> dict[str, Any]:
        doc = self.papers.load(paper_id)
        if doc["status"] != "active":
            return self.detail(paper_id)
        try:
            self._advance(doc)
        except DataMissing as e:
            doc["state"]["update_status"] = "delayed"
            doc["state"]["delayed_reason_ko"] = str(e)[:300]
            doc["state"]["last_refresh_at"] = _now()
            self.papers.save(doc)
        return self.detail(paper_id)

    def _advance(self, doc: dict[str, Any]) -> None:
        st = doc["state"]
        snap = doc["constraints_snapshot"]
        req, intent = snap["request"], snap["intent"]
        strategy = Strategy(**doc["strategy"])
        tickers, bench = list(doc["tickers"]), doc["benchmark"]
        markets = list(req["derived"].get("markets") or self.s.market.markets)
        last = dt.date.fromisoformat(st["last_snapshot_date"])
        ceiling = self.md.common_trading_day_on_or_before(self.md.ceiling, markets)
        st["last_refresh_at"] = _now()
        if ceiling <= last:
            st["update_status"], st["delayed_reason_ko"] = "ok", None
            self.papers.save(doc)
            return
        view = self.md.view(ceiling)
        start = dt.date.fromisoformat(doc["start_date"])
        cal = view.trading_days(start, ceiling, markets=markets)
        panel, _q = view.panel(tickers, last, ceiling, required=[*tickers, bench], benchmarks=[bench])
        fx = self.md.fx_series(last, ceiling)
        resumed = dt.datetime.fromisoformat(doc["resumed_at"]).date() if doc.get("resumed_at") else None
        done = {s["date"] for s in self.papers.snapshots(doc["paper_id"])}
        contrib = doc["contribution"]
        c_dates = set(contribution_dates(cal, start, ceiling, int(contrib.get("day") or 25))) if contrib.get("enabled") else set()
        r_dates = rebalance_due_dates(doc["rebalance_rule"], cal, start, two_week_days=self.s.backtest.rebalance_trading_days["2w"])
        bps = float(snap.get("commission_bps", self.s.backtest.commission_bps))
        for ts in panel.index:
            d = _d(ts)
            if d <= last or str(d) in done or (resumed and d < resumed):
                continue
            prices = {t: float(panel.loc[ts, t]) for t in tickers}
            bench_px = float(panel.loc[ts, bench])
            holdings, cash = dict(st["holdings"]), float(st["cash_usd"])
            units = float(st["units"])
            _w, _hv, value_pre = weights_of(holdings, cash, prices)
            contribution_usd = 0.0
            if pd.Timestamp(d) in c_dates and contrib.get("enabled"):
                rate = float(fx.get(pd.Timestamp(d), fx.iloc[-1])) if contrib.get("currency") == "KRW" else 1.0
                contribution_usd = round(float(contrib["monthly_amount"]) / rate, 2)
                unit_price_pre = value_pre / units if units > 0 else 1.0
                units += contribution_usd / unit_price_pre
                cash += contribution_usd
                st["contributions_total_usd"] = round(float(st.get("contributions_total_usd", 0.0)) + contribution_usd, 2)
                if st.get("benchmark_units") is not None:
                    st["benchmark_units"] = float(st["benchmark_units"]) + contribution_usd / bench_px
                holdings, cash, trades, fees, turnover = trade_to_target(holdings, cash, prices, st["target_weights"], float(st.get("cash_weight", 0.0)), bps)
                w_after, _, _ = weights_of(holdings, cash, prices)
                self.papers.append_rebalance(doc["paper_id"], {"date": str(d), "seq": int(st.get("n_rebalances", 0)), "kind": "contribution", "before_weights": _w, "target_weights": st["target_weights"],
                                                                "applied_weights": w_after, "trades": trades, "commission_usd": fees, "turnover": turnover, "fallback": False, "skipped": False,
                                                                "note_ko": f"월 적립 {contribution_usd:,.2f} USD 를 목표 비중대로 매수"})  # fmt: skip
            if d in r_dates:
                before, _, _ = weights_of(holdings, cash, prices)
                try:
                    tw, cw, info = self._construct_weights(strategy, self.md.view(d), tickers, req, intent, stage_tag=f"09_views_news_{d}_paper")
                except DataMissing as e:
                    info = {"fallback": True, "views": [], "evidence_window": None, "warnings": [f"재구성 실패: {e}"[:300]]}
                    tw, cw = dict(st["target_weights"]), float(st.get("cash_weight", 0.0))
                holdings, cash, trades, fees, turnover = trade_to_target(holdings, cash, prices, tw, cw, bps)
                applied, _, _ = weights_of(holdings, cash, prices)
                st["n_rebalances"] = int(st.get("n_rebalances", 0)) + 1
                st["last_rebalance_date"] = str(d)
                st["target_weights"], st["cash_weight"] = {t: round(x, 6) for t, x in tw.items()}, round(cw, 6)
                self.papers.append_rebalance(doc["paper_id"], {"date": str(d), "seq": st["n_rebalances"], "kind": "rebalance", "before_weights": before, "target_weights": st["target_weights"],
                                                                "applied_weights": applied, "trades": trades, "commission_usd": fees, "turnover": turnover, "views": info["views"],
                                                                "evidence_window": info["evidence_window"], "fallback": bool(info["fallback"]), "skipped": False, "max_tilt": None,
                                                                "warnings": list(info["warnings"]), "note_ko": "정기 리밸런싱 (종목 유지, 비중만 갱신)"})  # fmt: skip
            weights, hv, total = weights_of(holdings, cash, prices)
            unit_price = total / units if units > 0 else 1.0
            peak = max(float(st.get("unit_price_peak", 1.0)), unit_price)
            bench_units = st.get("benchmark_units")
            bench_value = round(float(bench_units) * bench_px, 2) if bench_units is not None else None
            # 비교지수 운용 수익률 = 시작일 가격 대비 (적립은 수익이 아니므로 단위가격과 같은 뜻)
            bench_px0 = doc.get("benchmark_start_px")
            bench_ret = round(bench_px / float(bench_px0) - 1, 6) if bench_px0 else None
            st.update({"holdings": {t: round(s, 8) for t, s in holdings.items()}, "cash_usd": round(cash, 4), "units": units, "unit_price_peak": peak, "last_snapshot_date": str(d),
                       "update_status": "ok", "delayed_reason_ko": None})  # fmt: skip
            self.papers.save(doc)
            self.papers.append_snapshot(doc["paper_id"], {"date": str(d), "value_usd": total, "cash_usd": round(cash, 2), "holdings_value_usd": hv, "weights": weights,
                                                          "drawdown": round(unit_price / peak - 1, 6), "return_since_start": round(unit_price - 1, 6), "unit_price": round(unit_price, 8),
                                                          "contribution_usd": contribution_usd, "contributions_total_usd": float(st.get("contributions_total_usd", 0.0)),
                                                          "benchmark_value_usd": bench_value, "benchmark_return_since_start": bench_ret,
                                                          "fx_rate": float(fx.get(pd.Timestamp(d), fx.iloc[-1])), "status": "ok", "warnings": []})  # fmt: skip
            done.add(str(d))
        st["update_status"], st["delayed_reason_ko"] = "ok", None
        self.papers.save(doc)

    # ── 중지·재개 ──
    def stop(self, paper_id: str) -> dict[str, Any]:
        doc = self.papers.load(paper_id)
        if doc["status"] == "stopped":
            raise Conflict("이미 중지된 모의투자입니다")
        now = _now()
        doc["status"], doc["stopped_at"] = "stopped", now
        doc.setdefault("history", []).append({"at": now, "event": "stopped", "note": f"마지막 평가일 {doc['state']['last_snapshot_date']}"})
        self.papers.save(doc)
        return self.detail(paper_id)

    def resume(self, paper_id: str) -> dict[str, Any]:
        doc = self.papers.load(paper_id)
        if doc["status"] == "active":
            raise Conflict("이미 진행 중인 모의투자입니다")
        req = doc["constraints_snapshot"]["request"]
        markets = list(req["derived"].get("markets") or self.s.market.markets)
        ceiling = self.md.common_trading_day_on_or_before(self.md.ceiling, markets)
        resume_day = ceiling
        stopped_day = dt.datetime.fromisoformat(doc["stopped_at"]).date() if doc.get("stopped_at") else resume_day
        start = dt.date.fromisoformat(doc["start_date"])
        cal = self.md.view(ceiling).trading_days(start, ceiling, markets=markets)
        last = dt.date.fromisoformat(doc["state"]["last_snapshot_date"])
        skipped = [d for d in rebalance_due_dates(doc["rebalance_rule"], cal, start, two_week_days=self.s.backtest.rebalance_trading_days["2w"]) if last < d < resume_day]
        now = _now()
        for d in skipped:
            doc["state"]["n_rebalances"] = int(doc["state"].get("n_rebalances", 0)) + 1
            self.papers.append_rebalance(paper_id, {"date": str(d), "seq": doc["state"]["n_rebalances"], "kind": "rebalance", "before_weights": {}, "target_weights": doc["state"]["target_weights"],
                                                    "applied_weights": {}, "trades": [], "commission_usd": 0.0, "turnover": 0.0, "fallback": False, "skipped": True,
                                                    "note_ko": f"중지 기간({stopped_day}~{resume_day})에 지나간 리밸런싱이라 건너뜀"})  # fmt: skip
            doc.setdefault("history", []).append({"at": now, "event": "rebalance_skipped", "note": str(d)})
        doc["status"], doc["resumed_at"] = "active", dt.datetime.combine(resume_day, dt.time(0, 0), tzinfo=dt.UTC).astimezone().isoformat(timespec="seconds")
        doc.setdefault("history", []).append({"at": now, "event": "resumed", "note": f"{resume_day} 부터 다시 평가 (중지 기간 기록은 비움)"})
        self.papers.save(doc)
        return self.refresh(paper_id)

    # ── 조회 ──
    def summary(self, doc: dict[str, Any], snaps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        snaps = snaps if snaps is not None else self._snapshots(doc["paper_id"])
        last = snaps[-1] if snaps else None
        usd0 = doc["initial_capital"]["usd"]
        st = doc["state"]
        value = last["value_usd"] if last else usd0
        contrib_total = float(st.get("contributions_total_usd", 0.0))
        return {"paper_id": doc["paper_id"], "name_ko": doc["name_ko"], "strategy": doc.get("strategy"), "report_id": doc["report_id"], "run_id": doc["run_id"], "status": doc["status"],
                "start_date": doc["start_date"], "last_date": st.get("last_snapshot_date"), "days_tracked": len(snaps), "initial_capital": doc["initial_capital"],
                "value_usd": value, "contributions_total_usd": contrib_total, "gain_usd": round(value - usd0 - contrib_total, 2),
                "return_since_start": last["return_since_start"] if last else 0.0, "benchmark": doc.get("benchmark"),
                "benchmark_return_since_start": (last or {}).get("benchmark_return_since_start"),
                "excess_return": (round(last["return_since_start"] - last["benchmark_return_since_start"], 6) if last and last.get("benchmark_return_since_start") is not None else None),
                "drawdown": last["drawdown"] if last else 0.0, "max_drawdown": round(min((s["drawdown"] for s in snaps), default=0.0), 6),
                "n_rebalances": st.get("n_rebalances", 0), "update_status": st.get("update_status", "ok"), "delayed_reason_ko": st.get("delayed_reason_ko"),
                "last_refresh_at": st.get("last_refresh_at"), "data_ceiling": str(self.md.ceiling), "reconstructed_at_start": doc.get("reconstructed_at_start", False)}  # fmt: skip

    def _snapshots(self, paper_id: str) -> list[dict[str, Any]]:
        by_date: dict[str, dict[str, Any]] = {}
        for s in self.papers.snapshots(paper_id):
            by_date[s["date"]] = s  # 같은 날짜가 두 번이면 마지막 줄
        return [by_date[k] for k in sorted(by_date)]

    def detail(self, paper_id: str) -> dict[str, Any]:
        doc = self.papers.load(paper_id)
        snaps = self._snapshots(paper_id)
        rebs = self.papers.rebalances(paper_id)
        public = {k: v for k, v in doc.items() if k != "constraints_snapshot"}
        public["constraints_snapshot"] = {k: v for k, v in doc["constraints_snapshot"].items() if k in ("request", "commission_bps")}
        return {"portfolio": public, "summary": self.summary(doc, snaps), "snapshots": snaps, "rebalances": rebs,
                "series": {"dates": [s["date"] for s in snaps], "value_usd": [s["value_usd"] for s in snaps], "benchmark_value_usd": [s.get("benchmark_value_usd") for s in snaps],
                           "return_since_start": [s["return_since_start"] for s in snaps], "benchmark_return_since_start": [s.get("benchmark_return_since_start") for s in snaps],
                           "drawdown": [s["drawdown"] for s in snaps]}}  # fmt: skip

    def list(self) -> list[dict[str, Any]]:
        return [self.summary(doc) for doc in sorted(self.papers.list(), key=lambda d: d["created_at"], reverse=True)]

    def refresh_all(self) -> list[str]:
        out = []
        for doc in self.papers.list():
            if doc["status"] != "active":
                continue
            try:
                self.refresh(doc["paper_id"])
                out.append(doc["paper_id"])
            except Exception as e:  # noqa: BLE001
                log.exception("paper %s refresh failed", doc["paper_id"])
                d2 = self.papers.load(doc["paper_id"])
                d2.setdefault("history", []).append({"at": _now(), "event": "refresh_failed", "note": f"{type(e).__name__}: {e}"[:300]})
                self.papers.save(d2)
        return out


def refresh_all_papers(repo: Any, store: JsonStore, settings: AnalysisSettings, llm: Any = None) -> list[str]:
    """일꾼이 한가할 때 부르는 진입점: 진행 중인 모의투자를 모두 최신 거래일까지 갱신."""
    from backend.analysis.common.llm import make_llm

    md = MarketData(repo, settings)
    return PaperService(store, repo, md, llm or make_llm(settings.llm), settings).refresh_all()
