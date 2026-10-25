"""M3-05 종목별 근거 서술기 (LLM #3). 선정 결과 + 지표 사실(fin:*) + 뉴스 근거(ev*) 를 주고 인용 ID 를 붙인 한국어 설명을 받는다.

코드 검사: 인용 ID 는 전달한 것만, 종목은 선정 목록만. 위반은 피드백 재시도 → 실패 시 LlmOutputError.
"""

from __future__ import annotations

import re
from typing import Any

from backend.analysis.common.llm import LlmClient, messages_from_prompts
from backend.analysis.common.prompts import load_prompts
from backend.analysis.m2_data.news import EvidenceWindow
from backend.analysis.schemas.intent import IntentSpec
from backend.analysis.schemas.selection import Selection, Tagging

STAGE = "06_explain"
from backend.analysis.common.citations import CITE_RE  # 인용 ID 정규식은 한 곳에서


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
    fact_ids = {f["id"] for f in facts}
    by_ticker_facts: dict[str, list[dict[str, Any]]] = {}
    for f in facts:
        by_ticker_facts.setdefault(f["ticker"], []).append(f)
    news_ids = news.ids if news else set()
    lines = []
    for s in sel.selected:
        fl = " ".join(f"[{f['id']}] {f['metric']}={f['value']:.4f}" for f in by_ticker_facts.get(s.ticker, []))
        nl = ""
        if news and news.by_ticker.get(s.ticker):
            recs = [r for r in news.records if r["evidence_id"] in set(news.by_ticker[s.ticker][:5])]
            nl = " / 뉴스: " + "; ".join(f"[{r['evidence_id']}] {r['published_at']} {r['title'][:80]}" for r in recs)
        dl = ""
        if news and news.by_ticker_dc.get(s.ticker):
            counts = news.event_counts(s.ticker)
            recs = [r for r in news.disclosures if r["evidence_id"] in set(news.by_ticker_dc[s.ticker][:5])]
            dl = (f" / 공시({(news.end - news.dc_start).days if news.dc_start else 0}일): " + ", ".join(f"{k} {n}건" for k, n in counts.items()) + "; "
                  + "; ".join(f"[{r['evidence_id']}] {r['available_on']} {r['event_label_ko']} ({r['title'][:50]})" for r in recs))
        mv = f"{s.metric_value:.3f}" if s.metric_value == s.metric_value else "nan"
        lines.append(f"{s.rank} | {s.ticker} | {s.name} | {s.sector} | {mv} | {s.theme_confidence} | {reason.get(s.ticker, '')} | 근거: {fl}{nl}{dl}")
    system, user = load_prompts(
        STAGE, summary_ko=it["interpretation"]["summary_ko"], explanation_level=it["report_settings"]["explanation_level"],
        metric=sel.summary["metric"], direction=sel.summary["direction"], as_of=sel.summary["as_of"], selected_block="\n".join(lines),
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
