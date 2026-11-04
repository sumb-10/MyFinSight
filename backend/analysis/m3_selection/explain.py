"""M3-05 종목별 근거 서술기 (LLM #3). 선정 결과 + 지표 사실(fin:*) + 뉴스 근거(ev*) 를 주고 인용 ID 를 붙인 한국어 설명을 받는다.

코드 검사: 인용 ID 는 전달한 것만, 종목은 선정 목록만. 위반은 피드백 재시도 → 실패 시 LlmOutputError.
"""

from __future__ import annotations

import math
import re
from typing import Any

from backend.analysis.common.labels import theme_ko
from backend.analysis.common.llm import LlmClient, messages_from_prompts
from backend.analysis.common.prompts import load_prompts
from backend.analysis.m2_data.news import EvidenceWindow
from backend.analysis.schemas.intent import IntentSpec
from backend.analysis.schemas.selection import Selection, Tagging

STAGE = "06_explain"
from backend.analysis.common.citations import CITE_RE  # 인용 ID 정규식은 한 곳에서


def _dc_date(r: dict[str, Any]) -> str:
    """공시 날짜 = 접수일(시장 현지). 이용 가능일(그 공시를 쓸 수 있는 첫 거래일)이 다르면 괄호로 덧붙인다 (예전에는 이용 가능일만 적어 3~4일 늦게 보였다, 003)."""
    filed, avail = r.get("filed_at") or r["available_on"], r["available_on"]
    return filed if filed == avail else f"{filed}(이용 가능일 {avail})"
from backend.analysis.m2_data import metrics as M


def explain(
    sel: Selection,
    tagging: Tagging,
    intent: IntentSpec | dict[str, Any],
    llm: LlmClient,
    *,
    facts: list[dict[str, Any]],
    news: EvidenceWindow | None = None, warnings_ko: list[str] | None = None) -> dict[str, Any]:
    it = intent.model_dump(mode="json") if isinstance(intent, IntentSpec) else intent
    reason = {r.ticker: r.reason_ko for r in tagging.tagged}
    # 판정 테마는 의도의 한국어 테마 이름으로 (013: theme_ko 는 제외 테마만 알아 'us high dividend income' 을 넘겼고, 설명이 없는 테마 '미국 고배당 소득' 을 지어냈다)
    label = {t["id"]: t.get("label_ko") or theme_ko(t["id"]) for t in (it.get("interpretation") or {}).get("themes") or [] if t.get("id")}
    themes = {r.ticker: ", ".join(label.get(t) or theme_ko(t) for t in r.themes) for r in tagging.tagged}
    asc = sel.summary.get("direction") == "asc"

    def _mk(x) -> float:
        v = x.metric_value
        return float("inf") if v is None or not math.isfinite(float(v)) else (float(v) if asc else -float(v))

    # 순위 = 선정 종목 안의 지표 순위 (선정 순서가 아니라). 필수 포함 종목은 선정 순서상 맨 앞이라 '첫 순위' 라고 썼다 (010 VRTX, 실제 5위).
    # 지표 자료가 없는 필수 포함 종목은 순위가 없다('–'): 꼴찌 순위를 주면 '순위를 매기지 못했다' 는 공지와 어긋난다
    mrank = {x.ticker: i + 1 for i, x in enumerate(sorted((x for x in sel.selected if math.isfinite(_mk(x))), key=_mk))}
    fact_ids = {f["id"] for f in facts}
    by_ticker_facts: dict[str, list[dict[str, Any]]] = {}
    for f in facts:
        by_ticker_facts.setdefault(f["ticker"], []).append(f)
    news_ids = news.ids if news else set()
    lines = []
    for s in sel.selected:
        fl = " ".join(f"[{f['id']}] {M.METRIC_KO.get(f['metric'], f['metric'])} {M.display_metric(f['metric'], f['value'])}" for f in by_ticker_facts.get(s.ticker, []))
        nl = ""
        if news and news.by_ticker.get(s.ticker):
            recs = [r for r in news.records if r["evidence_id"] in set(news.by_ticker[s.ticker][:5])]
            nl = " / 뉴스: " + "; ".join(f"[{r['evidence_id']}] {r['published_at']} {r['title'][:80]}" for r in recs)
        dl = ""
        if news and news.by_ticker_dc.get(s.ticker):
            counts = news.event_counts(s.ticker)
            recs = [r for r in news.disclosures if r["evidence_id"] in set(news.by_ticker_dc[s.ticker][:5])]
            dl = (f" / 공시({(news.end - news.dc_start).days if news.dc_start else 0}일): " + ", ".join(f"{k} {n}건" for k, n in counts.items()) + "; "
                  + "; ".join(f"[{r['evidence_id']}] {_dc_date(r)} {r['event_label_ko']} ({r['title'][:50]})" for r in recs))
        mv = M.display_metric(s.metric_name, s.metric_value)
        rk = (str(mrank[s.ticker]) if s.ticker in mrank else "–") + (" (필수 포함)" if s.forced else "")
        lines.append(f"{rk} | {s.ticker} | {s.name} | {s.sector} | {mv} | {s.theme_confidence} | {themes.get(s.ticker, '')} | {reason.get(s.ticker, '')} | 근거: {fl}{nl}{dl}")
    system, user = load_prompts(
        STAGE, summary_ko=it["interpretation"]["summary_ko"], explanation_level=it["report_settings"]["explanation_level"],
        metric=M.METRIC_KO.get(sel.summary["metric"], sel.summary["metric"]), direction=sel.summary["direction"], as_of=sel.summary["as_of"], selected_block="\n".join(lines),
        warnings_block="\n".join(f"- {w}" for w in (warnings_ko if warnings_ko is not None else [])) or "- 없음",  # 한국어 공지만 (영어 개발 문구는 LLM 에 주지 않음)
    )  # fmt: skip
    allowed = fact_ids | news_ids
    tickers = {s.ticker for s in sel.selected}

    def _check(a: dict[str, Any]) -> None:
        if not isinstance(a.get("per_ticker"), list) or not a.get("portfolio_summary_ko"):
            raise ValueError("need portfolio_summary_ko and per_ticker[]")
        for row in a["per_ticker"]:
            if row.get("ticker") not in tickers:
                raise ValueError(f"unknown ticker {row.get('ticker')!r} in per_ticker")
            bad = [c for c in CITE_RE.findall(row.get("rationale_ko", "")) if c not in allowed]
            if bad:
                raise ValueError(f"{row['ticker']}: unknown citation ids {bad}; cite only the given ids")
            if allowed and not CITE_RE.search(row.get("rationale_ko", "")):
                raise ValueError(f"{row['ticker']}: rationale must cite at least one given id like [fin:...] or [ev123]")

    ans = llm.complete_json(STAGE, messages_from_prompts(system, user), validator=_check)
    return {"request_id": sel.request_id, "stage": "06_selection_explained", **ans,
            "citations_available": sorted(allowed)}  # fmt: skip
