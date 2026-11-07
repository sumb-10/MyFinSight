"""M3-05 종목별 근거 서술기 (LLM #3). 선정 결과 + 지표 사실(fin:*) + 뉴스 근거(ev*) 를 주고 인용 ID 를 붙인 한국어 설명을 받는다.

코드 검사: 인용 ID 는 전달한 것만, 종목은 선정 목록만. 위반은 피드백 재시도 → 실패 시 LlmOutputError.
"""

from __future__ import annotations

import math
import re
from typing import Any

from backend.analysis.common.labels import sector_ko, theme_ko
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

# '12개월 수익률' 은 모멘텀 지표의 이름(M.METRIC_KO)이다. 배당수익률 선정에서 LLM 이 '배당수익률(최근 12개월)' 을 이렇게 줄여 써 주가 수익률처럼 읽혔다
# (027: 25개 카드 모두 '배당수익률 순위는 1위이며, 최근 12개월 수익률은 6.86%입니다 [fin:US-CCI:dividend_yield_ttm:2025-02-11]')
_DIV_AS_RETURN = re.compile(r"(?:(?:최근|직전|지난|과거)\s*)?12\s*개월간?\s*수익률")


def _dividend_wording(text: str) -> str:
    """배당수익률 선정의 '(최근) 12개월 수익률' → '최근 12개월 배당수익률' ('…배당수익률' 은 이미 맞아 걸리지 않는다).
    뉴스·공시만 인용한 문장은 기사 속 주가 수익률일 수 있어 그대로 둔다."""
    out = []
    for part in re.split(r"(?<=[.!?])(\s+)", text):  # 문장 단위 (구분 공백도 그대로 이어 붙인다)
        ids = CITE_RE.findall(part)
        news_only = bool(ids) and not any(i.startswith("fin:") for i in ids)
        out.append(part if news_only else _DIV_AS_RETURN.sub("최근 12개월 배당수익률", part))
    return "".join(out)


def explain(
    sel: Selection,
    tagging: Tagging,
    intent: IntentSpec | dict[str, Any],
    llm: LlmClient,
    *,
    facts: list[dict[str, Any]],
    news: EvidenceWindow | None = None, warnings_ko: list[str] | None = None, summaries: dict[str, str] | None = None) -> dict[str, Any]:
    """summaries = 종목별 회사 소개(후보 단계의 기업 개요). 넓은 테마는 분류 근거가 '넓은 테마라 …' 로 바뀌어 사업 설명이 없었다 (046 VMRK '사업 내용 확인 안 됨')."""
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
    # 필수 포함도 순위를 매기지 않는다 — 리포트 선정 표와 같게 (042: 후보 120개 중 꼴찌인 필수 포함 JNJ 가 '순위 20위' 로 읽혔다)
    mrank = {x.ticker: i + 1 for i, x in enumerate(sorted((x for x in sel.selected if math.isfinite(_mk(x)) and not x.forced), key=_mk))}
    fact_ids = {f["id"] for f in facts}
    by_ticker_facts: dict[str, list[dict[str, Any]]] = {}
    for f in facts:
        by_ticker_facts.setdefault(f["ticker"], []).append(f)
    news_ids = news.ids if news else set()
    lines = []
    # 행도 지표 순위 순으로 (순위 없는 필수 포함은 맨 뒤). 019: 선정 순서(필수 포함 → 섹터 선호)로 넘겨 LLM 이 첫 칸 대신 줄 수를 세어 20종목 중 13개 순위를 틀렸다('21위')
    for s in sorted(sel.selected, key=lambda x: mrank.get(x.ticker, len(mrank) + 1)):
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
        # PER 은 소수 둘째 자리까지 (041: 12.41 과 12.37 이 둘 다 '12.4배' 로 보여 '공동 열여섯 번째' 라고 썼다)
        mv = f"{float(s.metric_value):.2f}배" if s.metric_name == "pe_ttm" and s.metric_value is not None and math.isfinite(float(s.metric_value)) else M.display_metric(s.metric_name, s.metric_value)
        rk = (str(mrank[s.ticker]) if s.ticker in mrank else "–") + (" (필수 포함)" if s.forced else "")
        # 섹터는 한국어 이름으로 (053: 카드에 'Communication Services 섹터', 055: 요약에 'Financials' 가 그대로 나왔다)
        lines.append(f"{rk} | {s.ticker} | {s.name} | {sector_ko(s.sector)} | {mv} | {s.theme_confidence} | {themes.get(s.ticker, '')} | {reason.get(s.ticker, '')} | "
                     f"{((summaries or {}).get(s.ticker) or '')[:200]} | 근거: {fl}{nl}{dl}")  # fmt: skip
    # 요청 요약에서 백테스트 시작 조건 문장은 뺀다 — 06 이 그것을 요청으로 읽었다 (055: '시작 시점에는 6종목을 골라…' 를 보고 '요청은 6종목이지만 7개가 담겼다')
    summary = " ".join(x for x in re.split(r"(?<=[.!?다])\s+", str(it["interpretation"]["summary_ko"]).strip()) if x and not re.search(r"백테스트|시작\s*(?:시점|때)", x))
    system, user = load_prompts(
        STAGE, summary_ko=summary or it["interpretation"]["summary_ko"], explanation_level=it["report_settings"]["explanation_level"],
        metric=M.METRIC_KO.get(sel.summary["metric"], sel.summary["metric"]), direction=sel.summary["direction"], as_of=sel.summary["as_of"], selected_block="\n".join(lines),
        warnings_block="\n".join(f"- {w}" for w in (warnings_ko if warnings_ko is not None else [])) or "- 없음",  # 한국어 공지만 (영어 개발 문구는 LLM 에 주지 않음)
    )  # fmt: skip
    allowed = fact_ids | news_ids
    tickers = {s.ticker for s in sel.selected}
    attempt = [0]
    unknown: dict[str, list[str]] = {}

    def _check(a: dict[str, Any]) -> None:
        attempt[0] += 1
        unknown.clear()
        if not isinstance(a.get("per_ticker"), list) or not a.get("portfolio_summary_ko"):
            raise ValueError("need portfolio_summary_ko and per_ticker[]")
        for row in a["per_ticker"]:
            if row.get("ticker") not in tickers:
                raise ValueError(f"unknown ticker {row.get('ticker')!r} in per_ticker")
            bad = [c for c in CITE_RE.findall(row.get("rationale_ko", "")) if c not in allowed]
            if bad:
                # 재시도 답에서도 모르는 ID 면 실행을 멈추지 않고 그 ID 만 지운다 (000 재실행: BMY 카드가 ev1858785 를 ev1878791 로 잘못 옮겨
                # 두 번 다 거절돼 실행 전체가 멈췄다). 처음 답은 그대로 되돌려 다시 받는다.
                if attempt[0] == 1:
                    raise ValueError(f"{row['ticker']}: unknown citation ids {bad}; cite only the given ids")
                unknown[row["ticker"]] = bad
            if allowed and not CITE_RE.search(row.get("rationale_ko", "")):
                raise ValueError(f"{row['ticker']}: rationale must cite at least one given id like [fin:...] or [ev123]")

    ans = llm.complete_json(STAGE, messages_from_prompts(system, user), validator=_check)
    if unknown and isinstance(ans.get("per_ticker"), list):
        def _strip(text: str, ids: list[str]) -> str:
            return re.sub(r"\s*\[(?:" + "|".join(map(re.escape, ids)) + r")\]", "", text)

        ans = {**ans, "per_ticker": [{**r, "rationale_ko": _strip(r["rationale_ko"], unknown[r["ticker"]])} if r.get("ticker") in unknown else r
                                     for r in ans["per_ticker"]],
               "citation_fixes": {t: ids for t, ids in unknown.items()}}  # fmt: skip
    # 사용자가 보지 못하는 입력을 가리키는 말은 지운다 (030 '입력된 관련 뉴스 제목은', 033 '제공된 모멘텀만으로', 043 '주어진 뉴스에는' — 06 규칙만으로는 새었다)
    if isinstance(ans.get("per_ticker"), list):
        ans = {**ans, "per_ticker": [{**r, "rationale_ko": re.sub(r"(?:제공된|입력된)\s+|(?:제시된|주어진)\s+(?=(?:모멘텀|지표|자료|정보|근거|수치|숫자|목록|헤드라인|뉴스|데이터))", "", r["rationale_ko"])} if isinstance(r.get("rationale_ko"), str) else r
                                     for r in ans["per_ticker"]]}  # fmt: skip
    # 입력 표의 칸 이름 '판정 테마' 가 문장에 새지 않게 (062: '판정 테마인 미국 유틸리티에 해당합니다')
    if isinstance(ans.get("per_ticker"), list):
        ans = {**ans, "per_ticker": [{**r, "rationale_ko": _no_column_name(r["rationale_ko"])} if isinstance(r.get("rationale_ko"), str) else r
                                     for r in ans["per_ticker"]]}  # fmt: skip
    if sel.summary.get("metric") == "dividend_yield_ttm" and isinstance(ans.get("per_ticker"), list):  # 모멘텀 선정(return_12m_1m)의 '12개월 수익률' 은 맞는 이름 (027)
        ans = {**ans, "per_ticker": [{**r, "rationale_ko": _dividend_wording(r["rationale_ko"])} if isinstance(r.get("rationale_ko"), str) else r
                                     for r in ans["per_ticker"]]}  # fmt: skip
    return {"request_id": sel.request_id, "stage": "06_selection_explained", **ans,
            "citations_available": sorted(allowed)}  # fmt: skip


def _no_column_name(text: str) -> str:
    """'판정 테마인 X에 해당' → 'X 테마에 해당', 남은 '판정 테마' → '테마'."""
    text = re.sub(r"판정\s*테마인\s+([^.,\n]+?)에\s*해당", r"\1 테마에 해당", text)
    return re.sub(r"판정\s*테마", "테마", text)
