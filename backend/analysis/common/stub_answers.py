"""stub 모드용 '스마트 stub': 고정 파일로는 맞출 수 없는 LLM 응답(후보 분류·뷰·근거)을 프롬프트 내용에서 규칙으로 만든다.

API 호출 없이 파이프라인 전체를 돌리기 위한 개발·테스트 장치다. 실제 분석에는 쓰지 않는다 (llm.mode=api).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from backend.analysis.common.llm import Message

_TICKER_LINE = re.compile(r"^([A-Z0-9.\-]+) \| ", re.M)
_EV_LINE = re.compile(r"^((?:ev|dc)\d+) \| (\S+) \| [^|]* \| [^|]* \| ([A-Z0-9.\-]+) \| ", re.M)  # 뉴스(ev)·공시(dc) 줄: 5번째 칸이 ticker
_SEL_LINE = re.compile(r"^(\d+) \| ([A-Z0-9.\-]+) \| ([^|]*) \|.*?근거: (.*)$", re.M)
from backend.analysis.common.citations import CITE_RE as _CITE  # noqa: E402


def _user(messages: Sequence[Message]) -> str:
    """사용자 메시지 전부 (재시도 때는 사실 묶음 뒤에 피드백 메시지가 하나 더 붙으므로 마지막 것만 보면 근거 id 를 놓친다)."""
    return "\n".join(m["content"] for m in messages if m["role"] == "user")


def stub_classify(messages: Sequence[Message]) -> dict[str, Any]:
    """후보 목록의 모든 종목을 테마 해당(0.8)으로 분류. 세부산업 이름에 'Semiconductor' 가 있으면 0.9."""
    u = _user(messages)
    block = u.split("## 후보 종목", 1)[-1]
    theme_ids = re.findall(r"- `([a-z0-9_]+)`", u.split("## 테마", 1)[-1].split("## 제외", 1)[0])
    theme = theme_ids[0] if theme_ids else "theme"
    results = []
    for line in block.splitlines():
        m = _TICKER_LINE.match(line.strip())
        if not m:
            continue
        conf = 0.9 if "semiconductor" in line.lower() else 0.8
        results.append({"ticker": m.group(1), "in_theme": True, "themes": [theme], "confidence": conf,
                        "reason_ko": "stub: 후보 검색 규칙에 맞아 테마 해당으로 분류", "excluded_theme": None})  # fmt: skip
    return {"results": results}


def stub_views(messages: Sequence[Message]) -> dict[str, Any]:
    """근거 목록에서 종목별 첫 ev id 를 모아 절대 뷰 1개 + 상대 뷰 1개를 만든 세트 1개."""
    u = _user(messages)
    ev_by_ticker: dict[str, str] = {}
    for m in _EV_LINE.finditer(u):
        ev_by_ticker.setdefault(m.group(3), m.group(1))
    tickers = [m.group(1) for m in _TICKER_LINE.finditer(re.split(r"\n## (?:공시 사건|뉴스 근거)", u.split("## 종목", 1)[-1], maxsplit=1)[0])]
    with_news = [t for t in tickers if t in ev_by_ticker]
    views: list[dict[str, Any]] = []
    if with_news:
        t0 = with_news[0]
        views.append({"type": "absolute", "long": [t0], "short": [], "expected_return_annual": 0.15, "confidence": 0.3, "horizon_months": 12,
                      "rationale_ko": f"stub: {t0} 헤드라인({ev_by_ticker[t0]}) 근거", "evidence_type": "news", "evidence_ids": [ev_by_ticker[t0]]})  # fmt: skip
        others = [t for t in tickers if t != t0]
        if len(with_news) >= 2 and others:
            t1 = with_news[1]
            short = next((t for t in others if t != t1), None)
            if short:
                views.append({"type": "relative", "long": [t1], "short": [short], "expected_return_annual": 0.05, "confidence": 0.25, "horizon_months": 12,
                              "rationale_ko": f"stub: {t1} 가 {short} 대비 우위 ({ev_by_ticker[t1]})", "evidence_type": "news", "evidence_ids": [ev_by_ticker[t1]]})  # fmt: skip
    return {"sets": [{"scenario_id": "stub_news", "title_ko": "뉴스 근거 (stub)", "narrative_ko": "stub 모드: 헤드라인이 있는 종목에 작은 뷰를 둔다.", "views": views}]}


def stub_explain(messages: Sequence[Message]) -> dict[str, Any]:
    u = _user(messages)
    per = []
    for m in _SEL_LINE.finditer(u):
        ids = _CITE.findall(m.group(4))
        cite = f"[{ids[0]}]" if ids else ""
        per.append({"ticker": m.group(2), "rationale_ko": f"stub: 선정 지표 순위 {m.group(1)}위, {m.group(3).strip()} 섹터 {cite}."})
    return {"portfolio_summary_ko": "stub 모드 요약: 테마 후보를 정량 지표로 순위 매겨 고른 목록입니다.", "per_ticker": per, "warnings_ko": []}


_ID_BODY = {"ev": r"\d+", "dc": r"\d+"}  # ev/dc 는 숫자 id 만 (JSON 키 "event" 같은 것을 id 로 오인하지 않게)


def _ids(messages: Sequence[Message], prefix: str) -> list[str]:
    body = _ID_BODY.get(prefix, r'[^"\s]+')
    return sorted(set(re.findall(r'"(' + re.escape(prefix) + body + r')"', _user(messages))))


def stub_interpret(messages: Sequence[Message]) -> dict[str, Any]:
    calc = _ids(messages, "calc:")
    cite = f" [{calc[0]}]" if calc else ""
    return {"headline_ko": "백테스트 결과와 검증 판정을 바탕으로 한 선택안입니다.",
            "performance_ko": [f"백테스트 기간의 성과를 결과값 기준으로 설명합니다{cite}.", "강세·약세 구간과 최대낙폭은 표와 차트의 값을 참고합니다."],
            "risk_fit_ko": ["최대낙폭과 변동성이 손실 감내 수준에 맞는지는 검증 표의 판정을 따릅니다."],
            "validation_ko": ["검증 규칙 결과와 추천 여부는 검증 표에 정리되어 있습니다."],
            "view_review_ko": [], "next_actions_ko": ["손실 감내 수준을 다시 확인해 봅니다.", "테마 범위나 종목 수를 조정해 재분석해 봅니다."],
            "news_ko": [], "assessment": {"intent_fit": 0.7, "logic_consistency": 0.8, "comments_ko": ["stub 모드 평가"]}}


def stub_market(messages: Sequence[Message]) -> dict[str, Any]:
    evs = _ids(messages, "ev") or _ids(messages, "dc")
    if not evs:
        return {"market_ko": ["이 기간에는 팀 데이터베이스에 보유 종목 관련 뉴스 헤드라인이 없어 산업 흐름을 근거로 서술하지 않았습니다."], "evidence_ids_used": []}
    return {"market_ko": [f"수집된 헤드라인은 보유 종목 관련 사건의 존재를 알려 줍니다 [{evs[0]}]." + (f" 다른 기사도 같은 기간에 보고되었습니다 [{evs[1]}]." if len(evs) > 1 else ""),
                          "헤드라인만으로는 원인이나 전망을 말할 수 없으므로 산업 흐름은 참고 수준으로 봅니다."], "evidence_ids_used": evs[:2]}


def stub_narrate(messages: Sequence[Message]) -> dict[str, Any]:
    fins = _ids(messages, "fin:")
    cite = f" [{fins[0]}]" if fins else ""
    return {"overview_ko": ["요청한 테마의 후보를 정량 지표로 골라 포트폴리오를 만들고 과거 자료로 검증한 결과입니다.", "핵심 수치와 추천 여부는 위 지표 카드와 검증 결과를 따릅니다.", "과거 성과는 미래 성과를 뜻하지 않습니다."],
            "request_interpretation_ko": ["아이디어를 테마와 조건으로 해석했습니다."],
            "selection_ko": [f"테마 관련 후보를 산업 분류와 키워드로 찾고 분석 모델이 테마 해당 여부를 판정한 뒤 선정 지표 순위로 골랐습니다{cite}.", "두 기준일의 목록 차이는 표에 정리했습니다."],
            "construction_ko": ["기준 비중에 종목·섹터 상한을 적용하고, 뉴스 근거가 충분한 날에는 Black-Litterman 으로 비중을 조정했습니다."],
            "assumptions_ko": ["백테스트는 거래비용·배당 재투자·소수 주식 허용 가정이며 세금과 슬리피지는 반영하지 않았습니다."],
            "reconsideration_ko": ["테마 해석이나 손실 감내 수준이 바뀌면 다시 분석해야 합니다."],
            "forward_ko": [], "glossary": [{"term": t, "explain_ko": f"{t} 의 뜻 (stub)"} for t in ["CAGR", "최대낙폭", "Sharpe", "비교지수", "리밸런싱"]]}


_TEMPLATE_WORDS = {"모멘텀": "momentum", "퀄리티": "quality", "저per": "low_per", "저변동": "low_volatility", "고배당": "high_dividend"}


def stub_revision(messages: Sequence[Message]) -> dict[str, Any]:
    """수정 요청 문장을 아주 단순한 규칙으로 필드 변경으로 바꾼다 (테스트·연습용).
    '빼/제외' + 티커 → exclude_tickers 추가, '종목 수 N' → num_holdings.target, 'N%' + '상한' → max_weight_per_stock,
    템플릿 단어 → template, '리밸런싱/적립/기간/투자금' → 바꿀 수 없음, 그 밖은 아이디어 보충."""
    import json as _json
    import re as _re

    u = _user(messages)
    text = u.split("수정 요청:", 1)[1].split("\n", 1)[0].strip() if "수정 요청:" in u else u
    base: dict[str, Any] = {}
    m = _re.search(r"```json\n(.*?)\n```", u, _re.S)
    if m:
        try:
            base = _json.loads(m.group(1))
        except ValueError:
            base = {}
    changes: list[dict[str, Any]] = []
    unsupported: list[str] = []
    tickers = _re.findall(r"(?<![A-Za-z0-9])([A-Z]{1,5}(?:\.[A-Z]{2})?|\d{6}\.KS)(?![A-Za-z0-9])", text)  # 한글이 바로 붙어도 잡는다 ("NVDA는")
    if tickers and _re.search(r"빼|제외|말고|없이", text):
        cur = list((base.get("constraints") or {}).get("exclude_tickers") or [])
        changes.append({"field": "constraints.exclude_tickers", "value": sorted(set(cur) | set(tickers)), "reason_ko": f"{', '.join(tickers)} 제외 요청"})
    elif tickers and _re.search(r"넣|포함|담", text):
        cur = list((base.get("constraints") or {}).get("must_include_tickers") or [])
        changes.append({"field": "constraints.must_include_tickers", "value": sorted(set(cur) | set(tickers)), "reason_ko": f"{', '.join(tickers)} 포함 요청"})
    m2 = _re.search(r"종목\s*(?:수|개수)?\s*(?:를|을|은|는)?\s*(\d+)\s*개", text)
    if m2:
        n = int(m2.group(1))
        nh = dict((base.get("constraints") or {}).get("num_holdings") or {"target": n, "min": n, "max": n})
        nh.update({"target": n, "min": min(nh.get("min", n), n), "max": max(nh.get("max", n), n)})
        changes.append({"field": "constraints.num_holdings", "value": nh, "reason_ko": f"종목 수 {n}개 요청"})
    m3 = _re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if m3 and _re.search(r"상한|최대|비중", text):
        changes.append({"field": "constraints.max_weight_per_stock", "value": float(m3.group(1)) / 100, "reason_ko": "종목 상한 변경 요청"})
    for w, tpl in _TEMPLATE_WORDS.items():
        if w in text.lower():
            changes.append({"field": "strategy_preference.template", "value": tpl, "reason_ko": f"선정 기준을 {w}로"})
            break
    if _re.search(r"리밸런싱|적립|기간|투자금|자본|비교지수|벤치마크", text):
        unsupported.append("수정안 비교에서는 원안과 같은 조건(기간·자본·적립·비교지수·리밸런싱)을 유지합니다. 조건 자체를 바꾸려면 새 분석을 시작해 주세요")
    idea = None
    if not changes and not unsupported:
        idea = text
    return {"summary_ko": f"수정 요청: {text[:60]}", "changes": changes, "idea_update_ko": idea, "unsupported_ko": unsupported}


SMART_STUBS = {"15_revision": stub_revision, "04_classify": stub_classify, "09_views_news": stub_views, "06_explain": stub_explain,
               "14a_interpret": stub_interpret, "14c_market": stub_market, "14b_narrate": stub_narrate}
