"""시나리오 QA 라운드 9 (013·015·016): 검증 투자기간 = 확정 요청, 넓은 테마 판단을 03 과 같은 기준으로, GICS 업종이 없는 제외 테마는 키워드로만,
섹터 선호 종목 수는 투자 가능 비율로, 06 판정 테마는 의도의 한국어 이름, 낙폭 맞춤안 비중은 소수 한 자리."""

from __future__ import annotations

import copy
import datetime as dt
from types import SimpleNamespace

import pandas as pd

from backend.analysis.settings import AnalysisSettings

REQ = {
    "request_id": "req_q9", "profile": {"investment_experience": "beginner"}, "derived": {"as_of": "2026-07-16", "initial_amount_usd": 10_000},
    "horizon": {"target_years": 10.0, "backtest_years": 3.0},
    "risk": {"risk_tolerance": "conservative", "max_drawdown_tolerance": 0.08, "loss_reaction": "hold", "target_annual_return": 0.07, "benchmark": "SPY"},
    "constraints": {"num_holdings": {"target": 25, "min": 22, "max": 35}, "max_weight_per_stock": 0.1, "max_weight_per_sector": 0.3, "min_cash_ratio": 0.2},
    "strategy_preference": {"template": "high_dividend", "baseline_weighting": "market_cap", "use_news_tilt": False},
}  # fmt: skip

# 013 의 실제 테마: 4·6자리 코드 25개가 11개 섹터에 걸친다 (2자리 코드는 하나도 없다)
HD_013 = ["101020", "1510", "2010", "2020", "2030", "2510", "2520", "2530", "2550", "3010", "3020", "3030", "3510", "3520", "4010", "4020", "4030",
          "4510", "4520", "4530", "5010", "5020", "5510", "6010", "6020"]  # fmt: skip


def _intent_answer(rules: list[dict], horizon_years: float = 15.0) -> dict:
    return {
        "request_id": "x", "spec_version": "1.0",
        "interpretation": {"summary_ko": "미국 고배당", "themes": [{"id": "us_high_dividend_income", "label_ko": "미국 고배당 현금흐름", "description_ko": "d",
                                                               "gics_codes": list(HD_013), "keywords": ["dividend"], "example_tickers": ["PG", "O"]}]},
        "exclude_theme_rules": rules,
        "screen": {"template": "high_dividend", "metric": "dividend_yield_ttm", "direction": "desc", "as_of": "2026-07-16", "theme_filter": {"min_confidence": 0.5}, "select_top_n": 25},
        "risk_params": {"risk_tolerance": "conservative", "effective_max_drawdown": 0.08, "volatility_preference": "low", "notes_ko": ""},
        "news_tilt": {"enabled": False, "max_view_confidence": 0.3, "max_tilt_per_stock": 0.03},
        "validation_criteria": {"benchmark": "SPY", "max_drawdown": 0.08, "target_annual_return": 0.07, "horizon_years": horizon_years},
        "report_settings": {"language": "ko", "explanation_level": "beginner"}, "questions": [],
    }  # fmt: skip


def _interpret(rules: list[dict], req: dict | None = None, horizon_years: float = 15.0):
    from backend.analysis.common.llm import StubLlm
    from backend.analysis.m3_selection.intent import interpret
    from backend.pipeline.gics import load_taxonomy

    desc = SimpleNamespace(tax=load_taxonomy(), stocks=[{"yfinance_symbol": "PG"}, {"yfinance_symbol": "O"}])
    llm = StubLlm({"02_intent": _intent_answer(copy.deepcopy(rules), horizon_years)})
    spec, warns, _ = interpret(req or REQ, desc, llm, AnalysisSettings(), messages=[{"role": "user", "content": "q9"}])
    return spec.model_dump(mode="json"), warns


def test_intent_validation_horizon_follows_confirmed_request():
    """013: 요청 투자기간 10년인데 02 LLM 이 아이디어의 '약 15년' 을 적어 R2 가 '투자기간 15년' 으로 판정했다 → 요청값으로 덮어쓰고 경고를 남긴다."""
    out, warns = _interpret([])
    assert out["validation_criteria"]["horizon_years"] == 10.0
    assert "validation_criteria.horizon_years: LLM gave 15.0, enforced 10.0" in warns
    same, warns2 = _interpret([], horizon_years=10)
    assert same["validation_criteria"]["horizon_years"] == 10.0 and not any("horizon_years" in w for w in warns2)


def test_exclude_themes_without_gics_industry_use_keywords_only():
    """013: '성인 산업' 을 영화·엔터테인먼트·인터랙티브 미디어 업종 전체로 옮겨 DIS·GOOGL·META·NFLX 가 빠졌다. 017 은 '도박' 에도 같은 업종을 붙였다.
    맞는 세부 업종이 없는 테마는 키워드로만, 맞는 업종이 있는 테마는 그 업종만 남긴다. 표에 없는 테마(화석연료)는 LLM 코드 그대로."""
    media = ["50202010", "50203010"]
    rules = [{"theme": "adult_entertainment", "gics_codes": media, "keywords": ["adult entertainment", "pornography"]},
             {"theme": "gambling", "gics_codes": ["25301010", *media], "keywords": ["casino", "sports betting"]},
             {"theme": "tobacco", "gics_codes": ["30203010"], "keywords": ["tobacco", "cigarette"]},
             {"theme": "fossil_fuels", "gics_codes": ["101020", "55102010"], "keywords": ["oil and gas", "coal"]},
             {"theme": "성인 콘텐츠", "gics_codes": ["50203010"], "keywords": ["adult content"]},
             {"theme": "Casinos", "gics_codes": ["253010"], "keywords": ["casino"]}]  # fmt: skip
    out, warns = _interpret(rules)
    got = {r["theme"]: r for r in out["exclude_theme_rules"]}
    assert got["adult_entertainment"]["gics_codes"] == [] and got["adult_entertainment"]["keywords"] == ["adult entertainment", "pornography"]
    assert "exclude theme adult_entertainment: GICS codes ['50202010', '50203010'] dropped (no matching GICS sub-industry)" in warns
    assert got["gambling"]["gics_codes"] == ["25301010"]
    assert any(w.startswith("exclude theme gambling: GICS codes ['50202010', '50203010'] dropped (only ['25301010'] match the theme") for w in warns)
    assert got["tobacco"]["gics_codes"] == ["30203010"] and got["fossil_fuels"]["gics_codes"] == ["101020", "55102010"]
    assert not any(w.startswith(("exclude theme tobacco", "exclude theme fossil_fuels")) for w in warns)
    assert got["성인 콘텐츠"]["gics_codes"] == []  # 한국어 이름도 같은 표
    assert got["Casinos"]["gics_codes"] == ["25301010"]  # 상위 코드(호텔·식당·레저 산업)는 카지노·게이밍만 남긴다


def test_exclude_theme_key_aliases():
    from backend.analysis.m3_selection.intent import exclude_theme_key

    assert exclude_theme_key("Adult Entertainment") == exclude_theme_key("성인 산업") == exclude_theme_key("adult-content") == "adult_entertainment"
    assert exclude_theme_key("tobacco_products") == "tobacco" and exclude_theme_key("alcoholic_beverages") == "alcohol"
    assert exclude_theme_key("furniture") is None and exclude_theme_key("fossil_fuels") is None and exclude_theme_key(None) is None


def test_broad_theme_counts_sector_prefixes_within_each_theme():
    """013: 한 테마의 4·6자리 코드 25개가 11개 섹터에 걸쳤는데 2자리 코드만 세어 04 는 좁은 테마로, 03 은 넓은 테마로 판단했다.
    테마마다 앞 2자리 섹터 수를 센다 — 여러 테마를 합쳐야 섹터가 많아지는 가치사슬 아이디어는 여전히 좁은 테마 (Q-010 보정 유지)."""
    from backend.analysis.m3_selection.classify import is_broad_theme

    assert is_broad_theme([{"id": "us_high_dividend_income", "gics_codes": HD_013}], 6)  # 013
    assert is_broad_theme([{"id": "high_dividend_income", "gics_codes": ["10", "15", "20", "25", "30", "35", "40", "45", "50", "55", "60"]}], 6)  # 000·014
    assert not is_broad_theme([{"id": "five", "gics_codes": ["1010", "151010", "2010", "25102010", "3010"]}], 6)  # 5개 섹터 → 좁음
    chain = [{"id": "battery_materials", "gics_codes": ["15101050", "15104050"]}, {"id": "ev_makers", "gics_codes": ["25102010"]},
             {"id": "charging", "gics_codes": ["20104010"]}, {"id": "power_semis", "gics_codes": ["45301020"]},
             {"id": "grid", "gics_codes": ["55101010"]}, {"id": "auto_finance", "gics_codes": ["40202010"]}]  # fmt: skip
    assert len({c[:2] for th in chain for c in th["gics_codes"]}) == 6 and not is_broad_theme(chain, 6)
    # 001(AI 반도체 + 데이터센터): 테마별 1·3개 섹터
    assert not is_broad_theme([{"id": "ai_semiconductors", "gics_codes": ["453010", "45301020"]},
                               {"id": "data_centers", "gics_codes": ["60108010", "45102010", "451020", "45202030", "20104010", "201040", "60108020"]}], 6)  # fmt: skip


def _screen(monkeypatch, n_names: int, cons: dict):
    from backend.analysis.m2_data import metrics as Mx
    from backend.analysis.m3_selection.screen import screen

    vals = {f"H{i:02d}": 1.0 - i * 0.01 for i in range(n_names)}
    monkeypatch.setitem(Mx.METRICS, "return_12m_1m", lambda view, tks: (pd.Series({t: vals[t] for t in tks}, dtype=float), []))
    monkeypatch.setattr("backend.analysis.m3_selection.screen.D.gics_model", lambda e: SimpleNamespace(sector=SimpleNamespace(code="35", name="Health Care")))
    desc = SimpleNamespace(by_ticker=lambda t: {"ticker": t, "name": t, "market": "US", "gics": {}})
    tagging = SimpleNamespace(tagged=[SimpleNamespace(ticker=t, confidence=0.9) for t in vals], passed_tickers=list(vals))
    sel, _ = screen(SimpleNamespace(as_of=dt.date(2026, 6, 1)), desc, tagging, {"screen": {"metric": "return_12m_1m", "direction": "desc"}}, cons, request_id="r")
    return sel


def test_sector_preference_counts_names_on_investable_share(monkeypatch):
    """016: 최소 현금 15%·섹터 상한 85% 면 20종목 × 4.25% = 85% 로 다 들어가는데 floor(0.85 × 20) = 17 로 세어 3종목을 '초과' 로 표시했다
    (리포트에 '섹터 상한이 비중을 누른 부분' 이 거짓으로 떴다). 동일비중은 투자 가능 비율 ÷ n 이다."""
    cons = {"num_holdings": {"min": 17, "target": 20, "max": 23}, "max_weight_per_stock": 0.1, "max_weight_per_sector": 0.85, "min_cash_ratio": 0.15}
    sel = _screen(monkeypatch, 25, cons)
    assert len(sel.selected) == 20 and sel.summary["sector_cap"] == 20 and sel.summary["sector_overflow"] is None
    assert not any(w.startswith("sector name preference") for w in sel.warnings)
    # 최소 현금이 없으면 동일비중 5% × 17종목 = 85% 까지가 섹터 상한 안 → 예전처럼 3종목 초과를 알린다
    sel0 = _screen(monkeypatch, 25, {**cons, "min_cash_ratio": 0.0})
    assert sel0.summary["sector_cap"] == 17 and sel0.summary["sector_overflow"]["tickers"] == ["H17", "H18", "H19"]


def test_explain_names_themes_with_intent_korean_labels():
    """013: 06 판정 테마에 'us high dividend income' 을 넘겨 설명이 없는 테마 '미국 고배당 소득' 을 지어냈다 → 의도의 한국어 테마 이름 (모르는 id 는 예전처럼)."""
    from backend.analysis.m3_selection.explain import explain
    from backend.analysis.schemas.selection import Selected

    sel = SimpleNamespace(request_id="r", summary={"metric": "dividend_yield_ttm", "direction": "desc", "as_of": "2026-07-16"},
                          selected=[Selected(ticker=t, name=t, sector="Real Estate", sector_code="60", rank=i + 1, metric_name="dividend_yield_ttm", metric_value=v)
                                    for i, (t, v) in enumerate([("O", 0.055), ("VZ", 0.065)])])  # fmt: skip
    tagging = SimpleNamespace(tagged=[SimpleNamespace(ticker="O", reason_ko="r", themes=["us_high_dividend_income"]),
                                      SimpleNamespace(ticker="VZ", reason_ko="r", themes=["legacy_theme"])])  # fmt: skip
    intent = {"interpretation": {"summary_ko": "s", "themes": [{"id": "us_high_dividend_income", "label_ko": "미국 고배당 현금흐름", "description_ko": "d"}]},
              "report_settings": {"explanation_level": "beginner"}}  # fmt: skip
    seen = {}

    class Llm:
        def complete_json(self, stage, messages, validator=None):
            seen["user"] = messages[-1]["content"]
            return {"portfolio_summary_ko": "s", "per_ticker": []}

    explain(sel, tagging, intent, Llm(), facts=[])
    rows = {ln.split(" | ")[1]: ln.split(" | ")[6] for ln in seen["user"].splitlines() if " | " in ln and not ln.startswith("##")}
    assert rows == {"O": "미국 고배당 현금흐름", "VZ": "legacy theme"} and "us high dividend income" not in seen["user"]


def test_matched_share_keeps_one_decimal():
    """015: 주식 98.5%(0.985001) 를 '주식 99% + 현금 1%'·'99%로 줄여' 로 적어 같은 리포트의 98.5%·1.5% 와 달랐다. 정수 근처(0.05%p 안)는 정수."""
    from backend.analysis.m5_backtest_report import matched as MX

    assert MX.matched_name("시가총액비중", 0.985001) == "낙폭 맞춤안 (주식 98.5% + 현금 1.5%, 시가총액비중 기준)"
    assert MX.matched_name("동일비중", 0.77) == "낙폭 맞춤안 (주식 77% + 현금 23%, 동일비중 기준)"
    assert MX.stock_cash_ko(0.7696) == "주식 77% + 현금 23%" and MX.stock_cash_ko(0.7694) == "주식 76.9% + 현금 23.1%"
    assert MX.share_pct(0.985001) == "98.5%" and MX.share_pct(0.5) == "50%"


def _port(pid: str, kind: str, w: dict[str, float], mdd: float, sharpe: float, n: int, name: str, base_id: str | None = None) -> dict:
    return {"id": pid, "kind": kind, "name_ko": name, "base_id": base_id, "cash_ratio": None, "target_weights": w,
            "metrics": {"risk": {"max_drawdown": mdd, "ann_vol": 0.08}, "return": {"cagr": 0.10, "total_return": 0.33}, "vs_benchmark": {"excess_cagr": 0.01},
                        "composition": {"breaches": [], "max_weight_drift": 0.0, "max_sector_drift": 0.0}, "trading": {"n_rebalances": 4}},
            "series": {"index": [100.0 + i for i in range(n)]}, "checkpoints": [{"kind": "rebalance", "weights": {"after": w}}],
            "headline": {"sharpe": sharpe, "final_value_usd": 13_000.0, "view_hit_ratio": None}, "money": {"irr_annual": 0.1}}  # fmt: skip


def test_validation_uses_request_horizon_and_one_decimal_matched_reason():
    """013: 12 검증의 투자기간이 02 LLM 값(15년)이었다 → 확정 요청(10년). 015: 추천 사유 '주식 비중을 99%로 줄여' → '98.5%로 줄여'."""
    from backend.analysis.m5_backtest_report.validate import validate

    n = 60
    base = _port("market_cap", "template", {"A": 0.5, "B": 0.5}, -0.20, 0.50, n, "시가총액비중")
    matched = _port("dd_match_market_cap", "matched", {"A": 0.4925005, "B": 0.4925005}, -0.17, 0.60, n, "낙폭 맞춤안", base_id="market_cap")
    bench = {"id": "SPY", "kind": "benchmark", "name_ko": "SPY", "metrics": {"risk": {"max_drawdown": -0.25, "ann_vol": 0.15}, "return": {"cagr": 0.09}},
             "headline": {"sharpe": 0.4, "final_value_usd": 12_000.0, "view_hit_ratio": None}, "money": {"irr_annual": 0.09}}  # fmt: skip
    res = {"request_id": "r", "period": {"trading_days": n}, "portfolios": [base, matched], "benchmark": bench, "benchmarks": [bench]}
    intent = _intent_answer([], horizon_years=15.0)
    intent["risk_params"]["effective_max_drawdown"] = 0.18
    req = {**REQ, "risk": {**REQ["risk"], "max_drawdown_tolerance": 0.18}, "constraints": {**REQ["constraints"], "max_weight_per_stock": 0.5,
                                                                                         "max_weight_per_sector": 1.0, "min_cash_ratio": 0.0}}  # fmt: skip
    targets = {"baseline": {"id": "market_cap"}, "backtest_spec": {"selection": {}}}
    out = validate(res, targets, intent, req, {}, lambda t: t, AnalysisSettings())
    assert out["criteria"]["horizon_years"] == 10.0
    r2 = next(c for c in out["results"][0]["checks"] if c["rule"] == "R2")
    assert "투자기간 10년" in r2["message_ko"] and "15년" not in r2["message_ko"]
    assert out["chosen_id"] == "dd_match_market_cap" and "시가총액비중의 주식 비중을 98.5%로 줄여" in out["recommended"]["reason_ko"]
