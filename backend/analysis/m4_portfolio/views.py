"""M4-03 뉴스 근거 뷰 생성기 (LLM #4). 구성일 직전 뉴스 창의 헤드라인만 근거로 BL 뷰를 만든다 (K6: 플레이스홀더 뷰 없음).

LLM 은 뷰의 방향(up/down)과 강도(weak/medium/strong)만 낸다. 수치 Q 는 코드가 사전 기대수익 π 대비로 만든다
(2026-11 시나리오 QA, 논의사항 C1: LLM 이 "좋은 소식 +3%" 처럼 π 보다 낮은 숫자를 써서 긍정 뷰가 비중 축소로 뒤집히던 문제).
코드 검사: 종목은 입력만, evidence_ids 는 창 안의 것만, 근거 없는 절대 뷰 제거, 같은 종목 양쪽 다리 금지, 신뢰도 상한.
"""

from __future__ import annotations

import datetime as dt
import math
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
            f"{r12.get(t, float('nan')):+.1%} | {mm['ann_vol'][t]:.1%} | {mm['cap_weights'][t]:.1%} | {base_weights[t]:.1%}"
        )
    themes_block = "\n".join(f"- {th['id']}: {th['label_ko']} — {th['description_ko']}" for th in intent["interpretation"]["themes"])
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
                 n_sets=n_sets, views_per_set=views_per_set, max_conf=max_conf, single_max_conf=ps.single_evidence_max_confidence,
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
            if set(v["long"]) & set(v.get("short", [])):
                warnings.append(f"{sid}: view dropped, same ticker on both legs {key}")
                continue
            if v["type"] == "absolute" and len(v["long"]) != 1:
                warnings.append(f"{sid}: absolute view dropped, needs exactly one ticker (got {v['long']})")
                continue
            c = float(v.get("confidence", 0))
            if not (ps.confidence_floor <= c <= max_conf):
                warnings.append(f"{sid}: confidence {c} clipped to [{ps.confidence_floor}, {max_conf}]")
                v["confidence"] = min(max(c, ps.confidence_floor), max_conf)
            _quantify(v, mm, tickers, ps, warnings, sid)
            v.setdefault("horizon_months", 12)
            v.setdefault("rationale_ko", "")
            ids, missing = [], []
            for raw_id in v.get("evidence_ids", []):
                eid = str(raw_id).strip()
                if eid not in known_ev and eid.isdecimal():
                    # 접두사 누락만 복원하며, 뉴스·공시 ID 가 겹치면 추측하지 않는다.
                    matches = [prefix + eid for prefix in ("ev", "dc") if prefix + eid in known_ev]
                    if len(matches) == 1:
                        eid = matches[0]
                if eid in known_ev:
                    ids.append(eid)
                else:
                    missing.append(raw_id)
            if missing:
                warnings.append(f"{sid}: unknown evidence ids {missing} removed")
            if not ids:
                warnings.append(f"{sid}: view {key} dropped (no valid evidence)")
                continue
            if v["type"] == "absolute" and not evidence.has_evidence(v["long"][0]):
                warnings.append(f"{sid}: absolute view on {v['long'][0]} without news/disclosure evidence dropped")
                continue
            v["evidence_ids"] = ids
            if len(ids) == 1 and float(v["confidence"]) > ps.single_evidence_max_confidence:
                warnings.append(f"{sid}: single-evidence view confidence {v['confidence']} clipped to {ps.single_evidence_max_confidence}")
                v["confidence"] = ps.single_evidence_max_confidence
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


def _quantify(v: dict[str, Any], mm: dict[str, Any], tickers: list[str], ps, warnings: list[str], sid: Any) -> None:
    """LLM 의 방향·강도를 사전 기대수익 대비 연 기대수익 Q(`expected_return_annual`)로 바꾼다.

    절대 뷰: Q = π_i + 방향 × k × σ_i. 상대 뷰: Q = (π_long − π_short) + k × σ(long − short) — 사전 기대 차이를 long 쪽으로 강도만큼 옮긴다.
    (처음에는 max(차이, 0) 을 썼는데, 사전 차이가 −10% 인 '약한' 뷰가 15%p 넘게 움직이는 강한 뷰가 됐다 — 000 CCI > SPG.)
    방향이 없으면(옛 캐시 응답·옛 stub) 숫자의 부호로 추정하고 경고를 남긴다. 상대 뷰의 down 은 다리를 바꿔 up 으로 둔다.
    """
    pi, vol = mm["implied_returns"], mm["ann_vol"]
    direction = str(v.get("direction") or "").lower()
    if v["type"] == "relative" and direction not in ("up", "down"):
        direction = "up"  # 상대 뷰는 방향을 안 써도 된다: long 이 short 를 이긴다는 뜻
    elif direction not in ("up", "down"):
        r = float(v.get("expected_return_annual", 0) or 0)
        direction = "down" if r < 0 else "up"
        warnings.append(f"{sid}: view {v['long']} has no direction; inferred '{direction}' from the sign of its number")
    if v["type"] == "relative" and direction == "down":
        v["long"], v["short"] = list(v["short"]), list(v["long"])
        direction = "up"
        warnings.append(f"{sid}: relative 'down' view rewritten as long {v['long']} over short {v['short']}")
    strength = str(v.get("strength") or "").lower()
    if strength not in ps.view_strength_k:
        warnings.append(f"{sid}: view {v['long']} strength {v.get('strength')!r} unknown; using 'medium'")
        strength = "medium"
    k = float(ps.view_strength_k[strength])
    if v["type"] == "absolute":
        t = v["long"][0]
        prior = float(pi[t])
        q = prior + (1 if direction == "up" else -1) * k * float(vol[t])
        lo, hi = ps.abs_return_range
    else:
        prior = sum(float(pi[t]) for t in v["long"]) / len(v["long"]) - sum(float(pi[t]) for t in v["short"]) / len(v["short"])
        q = prior + k * _spread_vol(v, mm, tickers)
        lo, hi = ps.abs_return_range  # 상대 뷰도 사전 차이가 음수일 수 있어 절대 뷰 범위로 자른다 (부호가 아니라 이동 방향이 뜻)
    if not (lo <= q <= hi):
        warnings.append(f"{sid}: view {v['long']} return {q:.4f} clipped to [{lo}, {hi}]")
        q = min(max(q, lo), hi)
    v["direction"], v["strength"] = direction, strength
    v["prior_return"], v["expected_return_annual"] = round(prior, 6), round(q, 6)


def _spread_vol(v: dict[str, Any], mm: dict[str, Any], tickers: list[str]) -> float:
    """long 바스켓 − short 바스켓 수익률 차이의 연변동성 σ(P) = √(p'Σp). 공분산이 없으면 상관 0 으로 근사."""
    w = {t: 1 / len(v["long"]) for t in v["long"]}
    for t in v["short"]:
        w[t] = w.get(t, 0.0) - 1 / len(v["short"])
    cov, tk = mm.get("cov"), mm.get("tickers") or tickers
    if cov is not None and all(t in tk for t in w):
        idx = {t: i for i, t in enumerate(tk)}
        var = sum(w[a] * w[b] * float(cov[idx[a]][idx[b]]) for a in w for b in w)
    else:
        var = sum((w[t] * float(mm["ann_vol"][t])) ** 2 for t in w)
    return math.sqrt(max(var, 0.0))
