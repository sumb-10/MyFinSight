"""M4-03 뉴스 근거 뷰 생성기 (LLM #4). 구성일 직전 뉴스 창의 헤드라인만 근거로 BL 뷰를 만든다 (K6: 플레이스홀더 뷰 없음).

코드 검사: 종목은 입력만, evidence_ids 는 창 안의 것만, 근거 없는 절대 뷰 제거, 신뢰도·수익률 범위 클리핑.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from backend.analysis.common.llm import LlmClient, messages_from_prompts
from backend.analysis.common.prompts import load_prompts
from backend.analysis.m2_data import descriptor as D
from backend.analysis.m2_data.market_data import MarketDataView
from backend.analysis.m2_data.news import EvidenceWindow
from backend.analysis.settings import AnalysisSettings
from backend.pipeline.descriptor import Descriptor

STAGE = "09_views_news"


def trailing_12m_return(view: MarketDataView, tickers: list[str]) -> dict[str, float]:
    px = view.adj_close(tickers, view.as_of - dt.timedelta(days=380), fill=True)
    px = px.dropna(how="all")
    if px.empty:
        return {}
    first = px.bfill().iloc[0]
    return (px.iloc[-1] / first - 1).to_dict()


def _check(a: dict[str, Any]) -> None:
    if not (isinstance(a.get("sets"), list) and a["sets"]):
        raise ValueError("sets must be a non-empty list")


def generate_views(
    view: MarketDataView,
    tickers: list[str],
    mm: dict[str, Any],
    base_weights: dict[str, float],
    intent: dict[str, Any],
    desc: Descriptor,
    settings: AnalysisSettings,
    llm: LlmClient,
    evidence: EvidenceWindow,
    *,
    n_sets: int,
    views_per_set: int,
    stage_tag: str = STAGE,
) -> tuple[list[dict[str, Any]], list[str]]:
    """(sets, warnings). evidence.enough 가 아니면 호출자가 부르지 않는다 (기준 비중 fallback)."""
    ps = settings.portfolio
    max_conf = float(intent["news_tilt"]["max_view_confidence"])
    r12 = trailing_12m_return(view, tickers)
    rows = []
    for t in tickers:
        e = desc.by_ticker(t) or {}
        g = D.gics_model(e) if e else None
        rows.append(
            f"{t} | {e.get('name', t)} | {g.sector.name if g else ''} | {str(e.get('intro', ''))[:120]} | "
            f"{r12.get(t, float('nan')):+.1%} | {mm['ann_vol'][t]:.1%} | {mm['cap_weights'][t]:.1%} | {base_weights[t]:.1%} | {mm['implied_returns'][t]:+.1%}"
        )
    themes_block = "\n".join(f"- {th['id']}: {th['label_ko']} — {th['description_ko']}" for th in intent["interpretation"]["themes"])
    abs_r = f"{ps.abs_return_range[0]:+.0%} ~ {ps.abs_return_range[1]:+.0%}"
    rel_r = f"{ps.rel_return_range[0]:+.0%} ~ {ps.rel_return_range[1]:+.0%}"
    ev_lines, no_news, no_evidence = [], [], []
    for t in tickers:
        if not (evidence.by_ticker.get(t) or []):
            no_news.append(t)
        if not evidence.has_evidence(t):
            no_evidence.append(t)
    for r in evidence.records:
        if r["ticker"] in tickers:
            ev_lines.append(f"{r['evidence_id']} | {r['published_at']} | {r.get('source', '')}({r.get('language', '')}) | {r.get('publisher') or '-'} | {r['ticker']} | {r['title'][:140]}")
    dc_lines = [ln for ln in evidence.disclosure_lines() if ln.split(" | ")[4] in tickers] if evidence.disclosures else []
    ds = getattr(settings, "disclosures", None)
    dc_only_max = float(getattr(ds, "disclosure_only_max_confidence", 0.25) or 0.25)
    vars_ = dict(as_of=view.as_of, summary_ko=intent["interpretation"]["summary_ko"], themes_block=themes_block, stocks_block="\n".join(rows),
                 n_sets=n_sets, views_per_set=views_per_set, max_conf=max_conf, abs_range=abs_r, rel_range=rel_r,
                 news_window_days=(evidence.end - evidence.start).days, evidence_block="\n".join(ev_lines) or "(없음)",
                 dc_window_days=((evidence.end - evidence.dc_start).days if evidence.dc_start else 0), disclosure_block="\n".join(dc_lines) or "(없음)",
                 dc_only_max_conf=dc_only_max, no_news_tickers=", ".join(no_news) or "없음", no_evidence_tickers=", ".join(no_evidence) or "없음")  # fmt: skip
    system, user = load_prompts(STAGE, **vars_)  # 시스템 프롬프트는 상수 (날짜·조건은 사용자 메시지에만) → 제공자 프리픽스 캐시
    ans = llm.complete_json(stage_tag, messages_from_prompts(system, user), validator=_check, stub_key=STAGE)

    warnings: list[str] = []
    sets: list[dict[str, Any]] = []
    known = set(tickers)
    known_ev = evidence.ids
    for s_ in ans.get("sets", []):
        seen: set = set()
        views = []
        sid = s_.get("scenario_id")
        for v in s_.get("views", []):
            legs = list(v.get("long", [])) + list(v.get("short", []))
            bad = [x for x in legs if x not in known]
            if bad:
                warnings.append(f"{sid}: view dropped, unknown tickers {bad}")
                continue
            if not v.get("long") or (v.get("type") == "relative" and not v.get("short")) or (v.get("type") == "absolute" and v.get("short")):
                warnings.append(f"{sid}: view dropped, malformed legs long={v.get('long')} short={v.get('short')}")
                continue
            key = (tuple(sorted(v["long"])), tuple(sorted(v.get("short", []))))
            if key in seen:
                warnings.append(f"{sid}: duplicate view {key} dropped")
                continue
            seen.add(key)
            c = float(v.get("confidence", 0))
            if not (ps.confidence_floor <= c <= max_conf):
                warnings.append(f"{sid}: confidence {c} clipped to [{ps.confidence_floor}, {max_conf}]")
                v["confidence"] = min(max(c, ps.confidence_floor), max_conf)
            lo, hi = ps.abs_return_range if v["type"] == "absolute" else ps.rel_return_range
            r = float(v.get("expected_return_annual", 0))
            if not (lo <= r <= hi):
                warnings.append(f"{sid}: return {r} clipped to [{lo}, {hi}]")
                v["expected_return_annual"] = min(max(r, lo), hi)
            v.setdefault("horizon_months", 12)
            v.setdefault("rationale_ko", "")
            ids = [i for i in v.get("evidence_ids", []) if i in known_ev]
            missing = [i for i in v.get("evidence_ids", []) if i not in known_ev]
            if missing:
                warnings.append(f"{sid}: unknown evidence ids {missing} removed")
            if not ids:
                warnings.append(f"{sid}: view {key} dropped (no valid evidence)")
                continue
            if v["type"] == "absolute" and not evidence.has_evidence(v["long"][0]):
                warnings.append(f"{sid}: absolute view on {v['long'][0]} without news/disclosure evidence dropped")
                continue
            v["evidence_ids"] = ids
            kinds = {"disclosure" if i.startswith("dc") else "news" for i in ids}
            v["evidence_type"] = "mixed" if len(kinds) > 1 else next(iter(kinds))  # 코드가 인용 ID 로 다시 계산 (LLM 값 무시)
            if kinds == {"disclosure"} and float(v["confidence"]) > dc_only_max:
                warnings.append(f"{sid}: disclosure-only view confidence {v['confidence']} clipped to {dc_only_max}")
                v["confidence"] = dc_only_max
            views.append(v)
        if len(views) > views_per_set:
            warnings.append(f"{sid}: {len(views)} views, truncated to {views_per_set}")
            views = views[:views_per_set]
        if views:
            sets.append({**s_, "views": views})
    if len(sets) != n_sets:
        warnings.append(f"{len(sets)} sets returned, expected {n_sets}")
    return sets, warnings
