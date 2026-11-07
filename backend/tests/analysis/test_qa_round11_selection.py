"""시나리오 QA 라운드 11 (023~032): 고르는 종목을 바꾸는 충돌(선정 기준·유니버스)을 점검 질문보다 먼저 묻기, 시가총액 자료가 없는 종목이
시가총액비중에서 최소 비중만 받은 사실을 알리기(날짜별 반복은 한 번으로), 배당수익률 선정 카드의 '12개월 수익률' → '최근 12개월 배당수익률'."""

from __future__ import annotations

import datetime as dt
import json
from importlib import import_module
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.analysis.common.warnings import from_text, merge, render
from backend.analysis.schemas.dialog import AnalysisRequestDoc, QuestionProposal
from backend.analysis.settings import AnalysisSettings
from backend.tests.analysis.test_pipeline_e2e import REQUEST

C = import_module("backend.analysis.m4_portfolio.construct")  # 패키지가 같은 이름의 함수를 내보내 'import construct as C' 는 함수가 된다


# ───────────────────────── 024: 질문 순서 ─────────────────────────
def _pick(proposals: list[QuestionProposal]) -> QuestionProposal | None:
    """저장소·DB 없이 질문 고르기만 (설정만 쓴다)."""
    from backend.analysis.m1_request.dialog import DialogService

    svc = DialogService.__new__(DialogService)
    svc.s = AnalysisSettings()
    req = json.loads(json.dumps(REQUEST))
    req["strategy_preference"]["template"] = "low_volatility"
    req["constraints"].update({"max_weight_per_sector": 0.35, "min_cash_ratio": 0.1})
    doc = AnalysisRequestDoc(request_id=req["request_id"], created_at=req["created_at"], profile_version=1, idea="생활비에 보탤 배당 현금흐름을 원해요")
    return svc._pick_question(doc, proposals, req)


def _q(field: str, kind: str, values: list, priority: int = 1, **kw) -> QuestionProposal:
    return QuestionProposal(field=field, kind=kind, priority=priority, question_ko=f"{field}?", options=[{"value": v, "label_ko": str(v)} for v in values],
                            allow_free_text=False, **kw)  # fmt: skip


SECTOR_CAP = QuestionProposal(field="constraints.max_weight_per_sector", kind="feasibility", priority=1,
                              question_ko="예상 선정 종목 10개가 유틸리티 7개, 부동산 3개로 몰려 있어 섹터당 상한 35%로는 70%만 투자되고 현금이 30% 남습니다. 어떻게 할까요?",
                              options=[{"value": 0.45, "label_ko": "섹터 상한을 45%로 올려 투자 비율 90%를 모두 배분"}, {"value": 0.35, "label_ko": "섹터 상한 35% 유지 (현금 30%)"}],
                              allow_free_text=False)  # fmt: skip
START = QuestionProposal(field="horizon.backtest_years", kind="feasibility", priority=1, question_ko="백테스트 시작일에 선정할 수 있는 종목이 8개로 최소 10개에 못 미칩니다.",
                         options=[{"value": "keep_window", "label_ko": "기간 유지", "patch": {"_allow_fewer_at_start": True}},
                                  {"value": "shorten_2.1", "label_ko": "2.1년으로 줄임", "patch": {"horizon.backtest_years": 2.1}}],
                         allow_free_text=False)  # fmt: skip


def _template_conflict(priority: int = 1) -> QuestionProposal:
    return QuestionProposal(field="strategy_preference.template", kind="conflict", priority=priority,
                            question_ko="아이디어와 프로필의 '선정 기준(템플릿)' 이(가) 다릅니다. 어느 쪽으로 할까요?",
                            options=[{"value": "high_dividend", "label_ko": "아이디어대로: 고배당"}, {"value": "low_volatility", "label_ko": "프로필대로: 저변동성"}],
                            allow_free_text=False)  # fmt: skip


@pytest.mark.parametrize("priority", [1, 2, 5])
def test_template_conflict_is_asked_before_precheck_questions(priority):
    """024: 첫 질문(섹터 상한)의 '유틸리티 7개, 부동산 3개' 는 저변동성 기준 예상 종목이었는데, 다음 질문(템플릿 충돌)에 '아이디어대로: 고배당' 을 골라
    예상 종목이 부동산 8개·유틸리티 2개로 바뀌었다 (029·032: 섹터 상한·시작일 질문 뒤에 템플릿 충돌). 점검 질문이 우선순위가 같거나 더 높아도 충돌을 먼저 묻는다."""
    tmpl = _template_conflict(priority)
    reb = _q("constraints.rebalance", "ambiguous", [{"count": 1, "unit": "1m"}, {"count": 1, "unit": "1q"}], priority=2)
    # 마지막 경우: 점검 질문이 첫 순서라서, 점검보다 뒤였던 다른 질문(우선순위 2)보다도 먼저 묻는다 (점검 질문 바로 앞으로 옮기는 셈)
    for proposals in ([SECTOR_CAP, tmpl], [tmpl, SECTOR_CAP], [SECTOR_CAP, START, tmpl], [SECTOR_CAP, reb, tmpl]):
        q = _pick(proposals)
        assert q is not None and q.field == "strategy_preference.template" and q.kind == "conflict"


def test_universe_conflict_is_asked_before_precheck_question():
    universe = _q("constraints.universe", "conflict", [["SP500", "NASDAQ100"], ["SP500", "NASDAQ100", "KOSPI200"]], priority=2)
    assert _pick([SECTOR_CAP, universe]).field == "constraints.universe"


def test_other_question_order_is_unchanged():
    """좁은 변경: 고르는 종목을 바꾸지 않는 충돌이나 LLM 의 선호 질문은 예전처럼 점검 질문 뒤, 점검 질문이 없으면 (우선순위, 종류) 순서 그대로."""
    pref = _q("strategy_preference.template", "preference", ["momentum", "quality"])  # 라운드 5 테스트의 Q_TEMPLATE 과 같은 선호 질문
    reb_conflict = _q("constraints.rebalance", "conflict", [{"count": 1, "unit": "1m"}, {"count": 1, "unit": "1q"}])
    assert _pick([SECTOR_CAP, pref]).field == "constraints.max_weight_per_sector"
    assert _pick([pref, SECTOR_CAP]).field == "constraints.max_weight_per_sector"
    assert _pick([SECTOR_CAP, reb_conflict]).field == "constraints.max_weight_per_sector"
    reb = _q("constraints.rebalance", "ambiguous", [{"count": 1, "unit": "1m"}, {"count": 1, "unit": "1q"}], priority=1)
    assert _pick([_template_conflict(2), reb]).field == "constraints.rebalance"  # 점검 질문이 첫 순서가 아니면 바꾸지 않는다


# ───────────────────────── 025: 시가총액 자료 없음 공지 ─────────────────────────
NOTE = "market cap missing for ['XOM']: treated as 0 in market_cap weights"


def test_market_cap_missing_note_is_a_user_notice_with_tickers_only():
    """025: 시가총액 자료가 없는 필수 포함 XOM 이 시가총액비중 1.4~1.7%(최소 비중 1% + 남은 몫), 더 작은 CVX 는 상한 25% 였는데 공지가 없었다.
    예전 정규식은 종목 칸에 뒤의 ': treated as 0 in market_cap weights' 까지 담았다."""
    w = from_text("10w_paths", NOTE, dates=["2022-03-01"])
    assert w.code == "market_cap_missing" and w.level == "user" and w.details["key"] == "XOM"
    assert w.message_ko == ("시가총액 자료가 없는 1개 종목(XOM)은 시가총액비중 구성에서 시가총액을 0으로 계산했습니다. 그래서 회사 크기와 상관없이 "
                            "최소 비중(상한 때문에 남은 비중이 있으면 그 일부를 더함)만 받았고, 이 구성의 해당 종목 비중은 실제 회사 규모를 반영하지 않습니다.")  # fmt: skip
    many = from_text("10f_current", f"market cap missing for {['A', 'B', 'C', 'D', 'E', 'F', 'G']}: treated as 0 in market_cap weights")
    assert many.message_ko.startswith("시가총액 자료가 없는 7개 종목(A, B, C, D, E 외 2개)은") and "treated" not in many.message_ko
    start = from_text("10_targets", f"start@2021-12-16: {NOTE}")  # 10 단계(백테스트 시작일 구성)는 시점을 붙인다
    assert start.dates == ["2021-12-16"] and start.message_ko.startswith("백테스트 시작일(2021-12-16) 기준: 시가총액 자료가 없는 1개 종목(XOM)은")
    old = from_text("08_market_model", "market cap unavailable from valuation_daily for all candidates")  # 예전 원문 (종목 목록 없음)
    assert old.code == "market_cap_missing" and old.message_ko == "시가총액 자료가 있는 후보가 하나도 없었습니다."


def _construct_with(monkeypatch, cap_weights: dict[str, float], mc_weights: dict[str, float], note: str = NOTE):
    model = {"tickers": list(cap_weights), "cap_weights": cap_weights, "notes": [note, "cap_weights use valuation_daily market_cap (shares × close) as of the day before construction, USD converted"]}
    base = {"chosen_baseline": "equal_weight", "portfolios": [{"id": "equal_weight", "weights": {t: round(1 / len(cap_weights), 6) for t in cap_weights}},
                                                              {"id": "market_cap", "weights": mc_weights}]}  # fmt: skip
    monkeypatch.setattr(C, "build_market_model", lambda *a, **kw: (model, base))
    view = SimpleNamespace(as_of=dt.date(2024, 12, 16))
    return C.construct(view, list(cap_weights), {"request_id": "r"}, {"news_tilt": {"enabled": False}}, AnalysisSettings(), None, None, mode="current")


def test_construct_forwards_market_cap_note_only_when_the_name_is_held_small(monkeypatch):
    # 025: XOM 은 시가총액이 0 이라 최소 비중 + 남은 몫 1.4%, CVX 는 상한 25% → 알린다 (다른 시장모형 참고는 그대로 파일에만)
    res = _construct_with(monkeypatch, {"CVX": 0.31, "KMI": 0.2, "OKE": 0.19, "WMB": 0.3, "XOM": 0.0}, {"CVX": 0.25, "KMI": 0.2, "OKE": 0.19, "WMB": 0.25, "XOM": 0.014})
    assert res.warnings == [NOTE] and res.fallback
    # 모든 종목이 상한에 걸려 비중이 같으면(종목 수 축소 보기: 9종목 × 10%) 회사 크기와 무관 → 알리지 않는다
    res2 = _construct_with(monkeypatch, {"CVX": 0.6, "KMI": 0.4, "XOM": 0.0}, {"CVX": 0.3, "KMI": 0.3, "XOM": 0.3})
    assert res2.warnings == []
    # 모두 비면 시가총액비중은 동일비중으로 돌아가 '최소 비중' 이 사실이 아니다 → 알리지 않는다
    res3 = _construct_with(monkeypatch, {"CVX": 0.5, "XOM": 0.5}, {"CVX": 0.5, "XOM": 0.5}, note="market cap missing for ['CVX', 'XOM']: treated as 0 in market_cap weights")
    assert res3.warnings == []


def test_walkforward_market_cap_notice_is_merged_into_one_with_count_and_dates(monkeypatch, tmp_path):
    """리밸런싱일마다 같은 공지가 나와도 한 번 (횟수·기간). 10f(지금 구성)는 같은 공지에 합치고, 백테스트 시작일 구성(10)은 다른 시작일 공지처럼 따로 둔다."""
    from backend.analysis.executor import stages
    from backend.analysis.executor.context import RunContext

    dates = [dt.date(2022, 3, 1), dt.date(2022, 6, 1), dt.date(2022, 9, 1)]
    res = SimpleNamespace(market_model={"delta": 2.5, "delta_source": "fixed", "lookback": {}, "implied_returns": {}}, baselines={"portfolios": []},
                          evidence_summary=lambda: None, evidence=None, warnings=[NOTE], bl_portfolios=[], view_sets=[], baseline_weights={"CVX": 0.5, "XOM": 0.5},
                          applied_bl=[], fallback=True, fallback_reason_ko="뉴스 반영을 꺼서 기준 비중을 사용")  # fmt: skip
    monkeypatch.setattr(stages, "construct", lambda *a, **k: res)
    monkeypatch.setattr(stages, "trade_schedule", lambda md, spec, settings: {"rb": [pd.Timestamp(d) for d in dates]})
    ctx = RunContext("run_t", {"request_id": "r"}, None, SimpleNamespace(view=lambda x: SimpleNamespace(as_of=x)), None, AnalysisSettings(), tmp_path)
    ctx.outputs.update({"02_intent": {"news_tilt": {"enabled": False}}, "07_backtest_spec": {"selection": {"tickers": ["CVX", "XOM"]}}})
    stages.st_walkforward(ctx)
    assert ctx.out("10w_target_paths")["warnings"] == [f"{d}: {NOTE}" for d in dates]  # 파일에는 날짜별 원문
    m = [w for w in merge(ctx.warnings) if w.code == "market_cap_missing"]
    assert len(m) == 1 and m[0].level == "user" and m[0].count == 3 and m[0].dates == ["2022-03-01", "2022-06-01", "2022-09-01"]
    assert render(m[0]).endswith("반영하지 않습니다. (3회, 2022-03-01~2022-09-01)")
    ctx.warn_all("10f_current", [NOTE], dates=["2024-12-16"])  # st_forward 와 같은 방식
    ctx.warn_all("10_targets", [f"start@2021-12-16: {NOTE}"])  # st_targets 와 같은 방식
    m = [w for w in merge(ctx.warnings) if w.code == "market_cap_missing"]
    assert [(w.count, w.dates[0], w.dates[-1], w.message_ko.startswith("백테스트 시작일")) for w in m] == [(4, "2022-03-01", "2024-12-16", False), (1, "2021-12-16", "2021-12-16", True)]


# ───────────────────────── 027: 배당수익률을 '12개월 수익률' 로 ─────────────────────────
CCI_FACT = "fin:US-CCI:dividend_yield_ttm:2025-02-11"
CARD = (f"셀타워를 보유해 통신사에 임대하는 사업으로 '리츠 배당' 테마에 해당합니다. 선정 종목 중 배당수익률 순위는 1위이며, 최근 12개월 수익률은 6.86%입니다 [{CCI_FACT}].\n\n"
        f"12개월 수익률 기준으로 보면 선정 종목 중 가장 높습니다 [{CCI_FACT}]. 최근 12개월 배당수익률·배당수익률(최근 12개월)이라는 이름은 이미 맞습니다.\n\n"
        "최근 12개월 수익률이 40%에 달했다는 보도가 있습니다 [ev123].")  # fmt: skip


def _explain(metric: str, card: str) -> dict:
    from backend.analysis.m3_selection.explain import explain
    from backend.analysis.schemas.selection import Selected

    sel = SimpleNamespace(request_id="r", summary={"metric": metric, "direction": "desc", "as_of": "2025-02-12"},
                          selected=[Selected(ticker="CCI", name="Crown Castle", sector="Real Estate", sector_code="60", rank=1, metric_name=metric, metric_value=0.0686)])  # fmt: skip

    class Llm:
        def complete_json(self, stage, messages, validator=None):
            return {"portfolio_summary_ko": "요약", "per_ticker": [{"ticker": "CCI", "rationale_ko": card}]}

    facts = [{"id": CCI_FACT, "ticker": "CCI", "metric": metric, "value": 0.0686}]
    return explain(sel, SimpleNamespace(tagged=[]), {"interpretation": {"summary_ko": "s"}, "report_settings": {"explanation_level": "beginner"}}, Llm(), facts=facts)


def test_dividend_cards_do_not_call_the_yield_a_12_month_return():
    """027: 25개 카드 모두 '배당수익률 순위는 1위이며, 최근 12개월 수익률은 6.86%입니다' — '12개월 수익률' 은 모멘텀 지표의 이름이라 주가 수익률로 읽힌다."""
    text = _explain("dividend_yield_ttm", CARD)["per_ticker"][0]["rationale_ko"]
    assert f"배당수익률 순위는 1위이며, 최근 12개월 배당수익률은 6.86%입니다 [{CCI_FACT}]." in text
    assert f"최근 12개월 배당수익률 기준으로 보면 선정 종목 중 가장 높습니다 [{CCI_FACT}]." in text
    assert "최근 12개월 배당수익률·배당수익률(최근 12개월)이라는 이름은 이미 맞습니다." in text  # 이미 맞는 이름은 그대로
    assert "최근 12개월 수익률이 40%에 달했다는 보도가 있습니다 [ev123]." in text  # 뉴스만 인용한 문장은 기사 속 주가 수익률일 수 있다
    assert text.count("배당배당") == 0 and text.count("최근 최근") == 0


def test_momentum_cards_keep_the_12_month_return_wording():
    """모멘텀 선정(return_12m_1m)에서는 '12개월 수익률' 이 맞는 이름 → 건드리지 않는다."""
    assert _explain("return_12m_1m", CARD)["per_ticker"][0]["rationale_ko"] == CARD


def test_cards_drop_words_pointing_at_hidden_inputs():
    """030 '입력된 관련 뉴스', 033 '제공된 모멘텀', 043 '주어진 뉴스에는' — 사용자가 보지 못하는 입력을 가리키는 말만 지운다 ('주어진 기간' 같은 말은 그대로)."""
    card = f"주어진 뉴스에는 사업 내용이 없고 제공된 자료로 보면 배당이 높습니다 [{CCI_FACT}]. 주어진 기간 동안 꾸준했습니다 [{CCI_FACT}]."
    text = _explain("dividend_yield_ttm", card)["per_ticker"][0]["rationale_ko"]
    assert text == f"뉴스에는 사업 내용이 없고 자료로 보면 배당이 높습니다 [{CCI_FACT}]. 주어진 기간 동안 꾸준했습니다 [{CCI_FACT}]."


def test_unknown_citation_after_retry_is_stripped_not_fatal():
    """000 최종 재실행: BMY 카드가 근거 ID ev1858785 를 ev1878791 로 잘못 옮기고 재시도에서도 같아 실행 전체가 멈췄다.
    처음 답은 되돌려 다시 받고(그대로), 재시도 답에서도 모르는 ID 면 그 ID 만 지우고 기록한다."""
    from backend.analysis.errors import LlmOutputError
    from backend.analysis.m3_selection.explain import explain
    from backend.analysis.schemas.selection import Selected

    sel = SimpleNamespace(request_id="r", summary={"metric": "dividend_yield_ttm", "direction": "desc", "as_of": "2025-02-12"},
                          selected=[Selected(ticker="CCI", name="Crown Castle", sector="Real Estate", sector_code="60", rank=1, metric_name="dividend_yield_ttm", metric_value=0.0686)])  # fmt: skip
    bad = f"배당수익률이 높습니다 [{CCI_FACT}]. 소송 보도가 있습니다 [ev999]."

    class RetryLlm:  # LlmClient.complete_json 처럼: 검증 → 실패하면 한 번 다시 → 또 실패하면 LlmOutputError
        def __init__(self, answers):
            self.answers = list(answers)

        def complete_json(self, stage, messages, validator=None):
            for i, card in enumerate(self.answers):
                ans = {"portfolio_summary_ko": "요약", "per_ticker": [{"ticker": "CCI", "rationale_ko": card}]}
                try:
                    validator(ans)
                    return ans
                except ValueError as e:
                    if i == len(self.answers) - 1:
                        raise LlmOutputError(str(e)) from e
            raise AssertionError

    facts = [{"id": CCI_FACT, "ticker": "CCI", "metric": "dividend_yield_ttm", "value": 0.0686}]
    it = {"interpretation": {"summary_ko": "s"}, "report_settings": {"explanation_level": "beginner"}}
    out = explain(sel, SimpleNamespace(tagged=[]), it, RetryLlm([bad, bad]), facts=facts)
    assert out["per_ticker"][0]["rationale_ko"] == f"배당수익률이 높습니다 [{CCI_FACT}]. 소송 보도가 있습니다." and out["citation_fixes"] == {"CCI": ["ev999"]}
    good = f"배당수익률이 높습니다 [{CCI_FACT}]."
    out = explain(sel, SimpleNamespace(tagged=[]), it, RetryLlm([bad, good]), facts=facts)  # 재시도에서 고치면 그대로
    assert out["per_ticker"][0]["rationale_ko"] == good and "citation_fixes" not in out
