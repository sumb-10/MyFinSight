"""2026-11 시나리오 QA 라운드 13 (033~037) 회귀 테스트."""

from __future__ import annotations

from backend.analysis.m3_selection.intent import SECTOR_CODES, broaden_industry_agnostic


def test_industry_agnostic_theme_without_gics_searches_all_sectors():
    """037: '배당을 꾸준히 늘려 온 기업' 을 업종 코드 없이 키워드 'dividend growth' 와 예시 4종목으로만 찾아 후보가 4개, 25종목 요청이 3종목이 됐다.
    설명이 스스로 '업종에 관계없이' 라고 하면 11개 섹터에서 찾고 선정 지표가 순위를 정한다. 업종이 있는 테마·키워드 테마는 그대로."""
    themes = [{"id": "dividend_growth_income", "label_ko": "배당 성장 및 현금흐름 기업", "gics_codes": [],
               "description_ko": "업종에 관계없이 정기적으로 현금 배당을 지급하고 배당을 꾸준히 늘려 온 기업입니다."},
              {"id": "metaverse", "label_ko": "메타버스", "description_ko": "가상 세계 플랫폼 기업", "gics_codes": []},
              {"id": "semis", "label_ko": "반도체", "description_ko": "특정 산업에 한정하지 않고", "gics_codes": ["4530"]}]  # fmt: skip
    warns = broaden_industry_agnostic(themes)
    assert themes[0]["gics_codes"] == list(SECTOR_CODES) and len(SECTOR_CODES) == 11 and len(warns) == 1
    assert themes[1]["gics_codes"] == [] and themes[2]["gics_codes"] == ["4530"]
    assert broaden_industry_agnostic(themes) == []  # 다시 해도 그대로
    for text in ("업종과 상관없이 배당 성장", "모든 업종의 우량주", "산업 무관", "업종을 가리지 않고"):
        t = [{"id": "x", "description_ko": text, "gics_codes": []}]
        broaden_industry_agnostic(t)
        assert t[0]["gics_codes"], text


def test_reused_dialog_intent_is_broadened_too(monkeypatch):
    """다시 돌리기(대화에서 확정한 의도 재사용)도 같은 규칙을 적용한다."""
    from types import SimpleNamespace

    from backend.analysis.executor import stages

    intent = {"interpretation": {"themes": [{"id": "d", "label_ko": "배당 성장", "description_ko": "업종에 관계없이 배당을 늘려 온 기업", "gics_codes": []}]},
              "exclude_theme_rules": []}  # fmt: skip
    ctx = SimpleNamespace(intent=intent, outputs={}, warn_all=lambda stage, ws: None)
    assert "재사용" in stages.st_intent(ctx)
    assert ctx.outputs["02_intent"]["interpretation"]["themes"][0]["gics_codes"] == list(SECTOR_CODES)


def test_round13_report_texts(monkeypatch):
    """035·036·037: δ 는 배수를 곱한 값이 상한을 넘었는데 '시장 추정치가 상한을 넘어'. 037: 리밸런싱 없음인데 '리밸런싱마다 되돌렸습니다',
    R4b '752일' 을 JNJ 의 날 수로 읽음. 034: 초과 CAGR 서술 35.8%p vs 검증 35.9%p, '목표 5개와 같고, 최소 5개와 같습니다'.
    033: 해석 메모가 초보를 '해당하지 않는 입력' 이라 함, '제공된 모멘텀만으로', 숫자 대조가 +3,257.7% 를 못 찾음. 037: 깔때기가 예시 종목 4개를 'GICS·키워드 검색' 이라 함."""
    from backend.analysis.m5_backtest_report import collect as C
    from backend.analysis.m5_backtest_report import report as RP
    from backend.analysis.m5_backtest_report.report_blocks import _delta_src_ko, _notes_ko
    from backend.analysis.m5_backtest_report.report_check import known_numbers
    from backend.analysis.m5_backtest_report.validate import _drift_msg_ko, excess_pp_ko

    mm = {"delta_source": "market_implied", "delta_market": 7.0209, "delta_base": 1.5, "delta_multiplier": 1.5, "delta_dd_multiplier": 1.5, "delta_capped": True}
    assert _delta_src_ko(mm) == "시장 추정치 7.021 × 성향 배수 1.5 × 낙폭 배수 1.5 = 15.8 → 상한 8 적용"
    assert RP._rebalance_targets_ko({"mode": "static"}, False).startswith("리밸런싱 없이 백테스트 시작일 비중으로 산 뒤 그대로 보유했습니다")
    assert RP._rebalances({"portfolio": {"backtest_spec": {"rebalance_rule": {"enabled": False}}}}) is False
    comp = {"max_stock_weight": 0.35, "max_stock_weight_ticker": "JNJ", "days_above_stock_cap": 752, "days_above_stock_tol": 56, "n_days": 754, "breaches": ["stock_cap:JNJ"]}
    msg = _drift_msg_ko("stock", comp, 0.27, 0.25, ["JNJ"], rebal=False)
    assert msg.startswith("보유 기간 중 최대 종목 비중 35.0%(JNJ) — 상한 27%를 넘은 종목이 있던 날이 754거래일 중 752일") and msg.endswith("리밸런싱을 하면 완화됩니다")
    assert excess_pp_ko(0.3374, -0.0214, 0.3588) == "+35.8%p" and excess_pp_ko(None, None, 0.3588) == "+35.9%p"
    monkeypatch.setattr(RP.B, "current_composition", lambda R, c: ({f"T{i}": 0.1 for i in range(5)}, 0.5, "x"))
    assert RP._holdings_vs_request({"request": {"constraints": {"num_holdings": {"target": 5, "min": 5}}}}, "x") == "지금 구성은 5종목으로 목표·최소 5개와 같습니다."
    assert _notes_ko("변동성은 중간으로 봤습니다. 초보 투자 경험에 해당하지 않는 입력을 반영해 낙폭 맞춤 목표는 조정하지 않았습니다.") == "변동성은 중간으로 봤습니다."
    assert RP._plain_llm({"a": ["53개는 라벨에 적힌 대로 나눴고 제공된 모멘텀만으로 보면"]}) == {"a": ["53개는 나눴고 모멘텀만으로 보면"]}
    acc: set[float] = set()
    known_numbers({"m": 32.5773}, acc)
    assert 3257.7 in acc
    assert C._matched_label_ko({"by_rule": {"example_match": 4, "must_include": 1}}) == "테마 관련 종목 (예시 종목으로 4개 걸린 종목)"
    assert C._matched_label_ko({"by_rule": {"gics_match": 19, "keyword_match": 18}}) == "테마 관련 종목 (산업 분류로 19개, 키워드로 18개 걸린 종목, 한 종목이 여러 방법에 걸릴 수 있음)"


def test_round13_replay_leftovers():
    """033 재실행: '제시된 모멘텀 지표만으로' 가 남았다(자료를 가리킬 때만 지운다). 036 재실행: '2026 회계연도' 를 '2026회' 로 읽어 숫자 대조 메모가 생겼다."""
    from backend.analysis.m5_backtest_report import report as RP
    from backend.analysis.m5_backtest_report.report_check import NUM_RE

    assert RP._plain_llm("제시된 자료로는 판단하기 어렵고, 가이던스에 제시된 목표는 유지") == "자료로는 판단하기 어렵고, 가이던스에 제시된 목표는 유지"
    assert [m.group(2) for m in NUM_RE.finditer("2026 회계연도 전망, 리밸런싱 3회") if m.group(1).strip(",")] == [None, "회"]


def test_view_horizon_beyond_schema_is_clipped_not_fatal():
    """045: 투자기간 15년이라 LLM 이 뷰 기간을 180개월로 적었고, 형식(1~60개월) 검사에서 10 단계 전체가 멈췄다."""
    from backend.analysis.m4_portfolio.views import _horizon_months
    from backend.analysis.schemas.portfolio import View

    w: list[str] = []
    assert _horizon_months(180, w, "s") == 60 and _horizon_months(None, w, "s") == 12 and _horizon_months("x", w, "s") == 12 and _horizon_months(0, w, "s") == 1
    assert len(w) == 2 and "clipped" in w[0]
    assert View.model_fields["horizon_months"].metadata  # 형식 한도는 그대로 (1~60)


def test_round15_report_texts(monkeypatch):
    """045: 머리말이 아이디어의 '약 15년' (분석은 10년). 044: '백테스트 시작 시 … 60%만 운용하길 원합니다'. 046: '投자', 빈 변화 자료 키,
    맞춤안 타임라인 비중 차이가 줄이기 전 값. 043: 깔때기가 테마 판정 탈락 1개를 숨김."""
    from types import SimpleNamespace

    from backend.analysis.m5_backtest_report import collect as C
    from backend.analysis.m5_backtest_report import report as RP
    from backend.analysis.m5_backtest_report import report_blocks as RB

    R = {"request": {"horizon": {"target_years": 10.0}, "constraints": {"min_cash_ratio": 0.05}},
         "intent": {"interpretation": {"summary_ko": "미국 결제 기업을 고릅니다. 투자 기간은 약 15년으로 해석합니다. 백테스트 시작 시에는 4종목으로 60%만 운용하길 원합니다. 배당은 보지 않습니다."}}}  # fmt: skip
    monkeypatch.setattr(RP.B, "current_composition", lambda R_, c: None)
    assert RP._subtitle_ko(R, "x") == "미국 결제 기업을 고릅니다. 투자 기간은 10년으로 해석합니다. 배당은 보지 않습니다."
    # 045 재실행: 테마와 기간이 한 문장이면 문장째 빼지 않고 기간만 확정값으로
    R["intent"]["interpretation"]["summary_ko"] = "미국 결제·핀테크 기업 중 수익성을 중시해 투자하고, 투자 기간은 약 15년으로 해석합니다. 마스터카드(MA)는 반드시 포함합니다."
    assert RP._subtitle_ko(R, "x") == "미국 결제·핀테크 기업 중 수익성을 중시해 투자하고, 투자 기간은 10년으로 해석합니다. 마스터카드(MA)는 반드시 포함합니다."
    # 시작일 조건을 사실로 적은 문장은 둔다 (같은 문장에 필수 포함이 있다 — 032)
    R["intent"]["interpretation"]["summary_ko"] = "셰브론(CVX)을 반드시 포함하며, 목표 종목 수는 15개이고 백테스트 시작 시점에는 선정 가능한 11개 종목으로 평가합니다."
    assert RP._subtitle_ko(R, "x") == R["intent"]["interpretation"]["summary_ko"]
    assert RP._plain_llm("投자 기간") == "투자 기간"
    wf = {"portfolios": [{"id": "wf_bl_news", "kind": "black_litterman", "weights_by_date": {}}]}
    assert RP._wf_changes_facts({"portfolio": {"walkforward": wf, "targets": {"baseline": {"id": "equal_weight"}}}, "backtest": {"portfolios": []}}, "x", "") == {}
    tag = {"passed_tickers": ["A"], "excluded_by_theme": [{"ticker": "B"}], "tagged": [{"ticker": "A"}, {"ticker": "B"}, {"ticker": "PWR"}], "theme_filter_applied": True}
    desc = SimpleNamespace(by_ticker=lambda t: {"name": "Quanta Services"} if t == "PWR" else {})
    assert C._theme_fail_ko(tag, desc) == " · 테마에 해당하지 않는다고 판정된 1개: Quanta Services"
    assert C._theme_fail_ko({**tag, "theme_filter_applied": False}, desc) == ""


def test_opposite_views_on_one_stock_are_both_dropped(monkeypatch):
    """045: 같은 세트에 COIN 오름(0.25)·내림(0.30) — 먼저 나온 약한 '오름' 만 남아 순서가 결론을 정했다."""
    import datetime as dt
    from types import SimpleNamespace

    from backend.analysis.m4_portfolio import views as V
    from backend.analysis.settings import AnalysisSettings

    class Ev:
        ids = {"ev1", "ev2"}
        records = [{"evidence_id": i, "ticker": "COIN", "published_at": "2024-12-30", "title": "t", "source": "s", "language": "en", "publisher": "p"} for i in ("ev1", "ev2")]
        disclosures = []
        by_ticker = {"COIN": records}
        start = end = dt.date(2025, 1, 1)
        dc_start = None

        def has_evidence(self, t):
            return t == "COIN"

        def disclosure_lines(self):
            return []

    sets_in = {"sets": [{"scenario_id": "s", "title_ko": "t", "narrative_ko": "n", "views": [
        {"type": "absolute", "long": ["COIN"], "short": [], "direction": "up", "strength": "weak", "confidence": 0.25, "evidence_ids": ["ev1"]},
        {"type": "absolute", "long": ["COIN"], "short": [], "direction": "down", "strength": "medium", "confidence": 0.3, "evidence_ids": ["ev2"]}]}]}  # fmt: skip

    class Llm:
        def complete_json(self, *a, **k):
            return sets_in

    mm = {"tickers": ["COIN"], "implied_returns": {"COIN": 0.1}, "ann_vol": {"COIN": 0.5}, "cov": [[0.25]], "cap_weights": {"COIN": 1.0}, "delta": 2.5, "tau": 0.05}
    monkeypatch.setattr(V, "load_prompts", lambda *a, **k: ("s", "u"))
    import pandas as pd

    view = SimpleNamespace(as_of=dt.date(2025, 1, 1), adj_close=lambda *a, **k: pd.DataFrame())
    intent = {"interpretation": {"summary_ko": "s", "themes": []}, "news_tilt": {"max_view_confidence": 0.5}}
    sets, warns = V.generate_views(view, ["COIN"], mm, {"COIN": 1.0}, intent, SimpleNamespace(by_ticker=lambda t: {"name": t}), AnalysisSettings(), Llm(), Ev(),
                                   n_sets=1, views_per_set=4, stage_tag="t")  # fmt: skip
    assert not any(v["long"] == ["COIN"] for s_ in sets for v in s_["views"]) and any("opposite views" in w for w in warns)
    # 다른 뷰가 남은 세트는 설명에 뺀 사실을 덧붙인다 (045 재실행: 둘 다 뺐는데 '상반된 신호로 반영했습니다')
    Ev.records = [*Ev.records, {"evidence_id": "ev3", "ticker": "V", "published_at": "2024-12-30", "title": "t", "source": "s", "language": "en", "publisher": "p"}]
    Ev.ids = {"ev1", "ev2", "ev3"}
    Ev.by_ticker = {"COIN": Ev.records[:2], "V": Ev.records[2:]}
    Ev.has_evidence = lambda self, t: t in ("COIN", "V")
    sets_in["sets"][0]["views"].append({"type": "absolute", "long": ["V"], "short": [], "direction": "up", "strength": "weak", "confidence": 0.25, "evidence_ids": ["ev3"]})
    mm2 = {"tickers": ["COIN", "V"], "implied_returns": {"COIN": 0.1, "V": 0.08}, "ann_vol": {"COIN": 0.5, "V": 0.2}, "cov": [[0.25, 0.02], [0.02, 0.04]],
           "cap_weights": {"COIN": 0.5, "V": 0.5}, "delta": 2.5, "tau": 0.05}  # fmt: skip
    sets, _w = V.generate_views(view, ["COIN", "V"], mm2, {"COIN": 0.5, "V": 0.5}, intent, SimpleNamespace(by_ticker=lambda t: {"name": t}), AnalysisSettings(), Llm(), Ev(),
                                n_sets=1, views_per_set=4, stage_tag="t")  # fmt: skip
    assert [v["long"] for v in sets[0]["views"]] == [["V"]]
    assert sets[0]["narrative_ko"] == "n 같은 종목(COIN)에 오름·내림 뷰가 함께 나와 그 종목의 두 뷰는 반영하지 않았습니다."


def test_sector_preference_skipped_when_plain_ranks_already_fill_the_caps(monkeypatch):
    """043: 리츠 21 + 유틸리티 9 로 섹터 상한 45% + 45% = 90% 를 다 담을 수 있었는데 섹터당 15개로 잘라,
    '투자금을 다 배분하려고' 라는 공지와 달리 순위가 낮은 변동성 큰 종목이 저변동성 요청에 들어왔다. 상위 n 개로 다 담기면 순위대로만 고른다."""
    import datetime as dt
    from types import SimpleNamespace

    import pandas as pd_

    from backend.analysis.m2_data import metrics as Mx
    from backend.analysis.m3_selection.screen import screen

    vals = {"A1": 0.9, "A2": 0.8, "A3": 0.7, "B1": 0.6, "B2": 0.5, "C1": 0.4}
    monkeypatch.setitem(Mx.METRICS, "return_12m_1m", lambda view, tks: (pd_.Series({t: vals[t] for t in tks}, dtype=float), []))
    sec = {"A": ("60", "Real Estate"), "B": ("55", "Utilities"), "C": ("20", "Industrials")}
    monkeypatch.setattr("backend.analysis.m3_selection.screen.D.gics_model",
                        lambda e: SimpleNamespace(sector=SimpleNamespace(code=sec[e["ticker"][0]][0], name=sec[e["ticker"][0]][1])))  # fmt: skip
    desc = SimpleNamespace(by_ticker=lambda t: {"ticker": t, "name": t, "market": "US", "gics": {}})
    tagging = SimpleNamespace(tagged=[SimpleNamespace(ticker=t, confidence=0.9) for t in vals], passed_tickers=list(vals))
    intent = {"screen": {"metric": "return_12m_1m", "direction": "desc"}}

    def run(stock_cap):
        cons = {"num_holdings": {"min": 1, "target": 4, "max": 4}, "max_weight_per_stock": stock_cap, "max_weight_per_sector": 0.6, "min_cash_ratio": 0.0}
        sel, _ = screen(SimpleNamespace(as_of=dt.date(2025, 6, 25)), desc, tagging, intent, cons, request_id="r")
        return [s.ticker for s in sel.selected], {r.ticker: r.reason for r in sel.rejected}, sel.warnings

    # 종목당 40%: 상위 4개(리츠 3 + 유틸리티 1)로 60% + 40% = 100% → 섹터 선호(섹터당 2개)를 쓰지 않는다
    picked, reasons, warns = run(0.4)
    assert picked == ["A1", "A2", "A3", "B1"] and "sector_preference" not in reasons.values()
    assert not any(w.startswith("sector count preference") for w in warns)
    # 종목당 30%: 상위 4개로는 60% + 30% = 90% 뿐 → 예전처럼 섹터당 2개로 고르고 A3 이 자리를 내준다
    picked, reasons, _ = run(0.3)
    assert sorted(picked) == ["A1", "A2", "B1", "B2"] and reasons["A3"] == "sector_preference"


def test_round15_047_stuck_views_listing_market_and_labels():
    """047: 선택안 bl_03 의 MSFT·GOOGL '오름' 뷰는 두 종목이 이미 상한 15% 라 비중이 그대로였는데 '관점이 맞았다' 로만 읽혔다 →
    한 BL 구성에서 비중을 바꾸지 못한 뷰를 센다 (방향별 이유: 상대 뷰가 끼면 '상한·섹터 예산'). 상장 시장 ≠ 국적.
    맞춤안 이름은 walk-forward BL 이라고 밝히고, 정적 BL 선택안의 시작일 타임라인 줄에 그날의 뷰를 보인다."""
    from backend.analysis.m5_backtest_report import matched as MX
    from backend.analysis.m5_backtest_report import report as RP
    from backend.analysis.m5_backtest_report import report_blocks as RB

    R = {"request": {"constraints": {"max_weight_per_stock": 0.15}},
         "selection": {"table": [{"ticker": "MSFT", "name": "Microsoft"}, {"ticker": "GOOGL", "name": "Alphabet"}]}}  # fmt: skip
    up = lambda t: {"type": "absolute", "long": [t], "short": [], "direction": "up"}  # noqa: E731
    p = {"views_applied": [up("MSFT"), up("GOOGL"), {"type": "relative", "long": ["MSFT"], "short": ["ADBE"], "direction": "up"}],
         "weights": {"MSFT": 0.15, "GOOGL": 0.15, "ADBE": 0.05, "INTU": 0.1}, "delta_vs_baseline": {"MSFT": 0.0, "GOOGL": 0.0, "ADBE": -0.05, "INTU": 0.05}}
    assert RB.view_stuck_note(R, p) == "뉴스 뷰 3개 중 2개는 뷰가 걸린 종목(Microsoft·Alphabet)이 종목당 상한(15%)에 묶여 있어 그 종목 비중을 바꾸지 못했습니다 (기준 비중과 같음)"
    p2 = {**p, "views_applied": [*p["views_applied"], {"type": "relative", "long": ["GOOGL"], "short": ["INTU0"], "direction": "up"}]}
    assert "상한·섹터 예산 같은 제약 때문에" in RB.view_stuck_note(R, p2)  # 상대 뷰의 약한 쪽은 종목당 상한 탓이 아니다
    assert RB.view_stuck_note(R, {**p, "views_applied": p["views_applied"][2:]}) is None
    assert RP._stuck_fact(R, p) == {"views_not_moving_ko": RB.view_stuck_note(R, p)} and RP._stuck_fact(R, {"views_applied": []}) == {}
    assert RP._LISTED_KO["US"].startswith("미국 시장 상장")
    assert MX.matched_name(MX.BASE_LABEL_BL, 0.495) == "낙폭 맞춤안 (주식 49.5% + 현금 50.5%, walk-forward 뉴스 뷰 BL 기준)"
    # 정적 BL 선택안: 시작일 줄에 뷰
    cp = lambda d: {"seq": 0, "date": d, "kind": "rebalance", "n_trading_days_to_date": 0, "money": {"value_usd": 1, "benchmark_value_usd": 1, "net_invested_usd": 1},  # noqa: E731
                    "since_last": None, "trades": [], "weights": {}}
    R2 = {"backtest": {"portfolios": [{"id": "bl_03", "kind": "black_litterman", "mode": "static", "name_ko": "BL 타겟 3", "checkpoints": [cp("2022-08-29"), cp("2022-10-03")]}],
                       "benchmarks": [], "benchmark": {"id": "SPY"}}, "validation": {},
          "portfolio": {"walkforward": None, "targets": {"as_of": "2022-08-29", "baseline": {"id": "market_cap"},
                                                          "portfolios": [{"id": "bl_03", "views_applied": [{**up("MSFT"), "summary_ko": "MSFT 오름", "confidence": 0.25}]}]},
                        "backtest_spec": {"rebalance_rule": {"enabled": True}}}}  # fmt: skip
    tl = RB.timeline(R2, "bl_03")
    assert [len(x["views"]) for x in tl["items"]] == [1, 0] and tl["items"][0]["views"][0]["summary_ko"] == "MSFT 오름"


def test_tied_candidates_do_not_claim_the_highest_sharpe():
    """049: 시작일 5종목 × 상한 10% 라 14개 후보가 모두 같은 비중·성과(Sharpe 0.388246~0.388249)였고 사용자가 고른 기준 비중이 1위였는데
    추천 사유가 'Sharpe 0.39로 가장 높음'. 순위 키와 같은 반올림으로 동점을 세고 실제로 순위를 정한 규칙을 적는다."""
    from backend.analysis.m5_backtest_report.validate import validate
    from backend.analysis.settings import AnalysisSettings
    from backend.tests.analysis.test_qa_round9_selection import REQ, _intent_answer, _port

    n = 60
    mine = _port("equal_weight", "template", {"A": 0.5, "B": 0.5}, -0.10, 0.3882461, n, "동일비중")
    other = _port("market_cap", "template", {"A": 0.5, "B": 0.5}, -0.10, 0.3882489, n, "시가총액비중")
    bench = {"id": "SPY", "kind": "benchmark", "name_ko": "SPY", "metrics": {"risk": {"max_drawdown": -0.25, "ann_vol": 0.15}, "return": {"cagr": 0.09}},
             "headline": {"sharpe": 0.4, "final_value_usd": 12_000.0, "view_hit_ratio": None}, "money": {"irr_annual": 0.09}}  # fmt: skip
    res = {"request_id": "r", "period": {"trading_days": n}, "portfolios": [other, mine], "benchmark": bench, "benchmarks": [bench]}
    req = {**REQ, "constraints": {**REQ["constraints"], "max_weight_per_stock": 0.5, "max_weight_per_sector": 1.0, "min_cash_ratio": 0.0}}
    out = validate(res, {"baseline": {"id": "equal_weight"}, "backtest_spec": {"selection": {}}}, _intent_answer([], 10.0), req, {}, lambda t: t, AnalysisSettings())
    assert out["chosen_id"] == "equal_weight"
    assert "성과가 같은 후보 2개 중 사용자가 고른 기준 비중이라 1위" in out["recommended"]["reason_ko"] and "가장 높음" not in out["recommended"]["reason_ko"]


def test_start_shortfall_reason_names_the_real_filters():
    """049: 시작일 종목이 5개뿐인 이유를 대화가 '상장 전이거나 재무 지표가 없던 종목' 이라고 했는데, 빠진 9개 중 8개는 그날 시가총액이
    사용자의 최소 시가총액(500억 달러)에 못 미친 것이었다. 실행 전 점검이 사유별 수를 세고 질문 설명이 그 수를 쓴다."""
    from types import SimpleNamespace as NS

    from backend.analysis.m1_request.dialog import _start_why_ko
    from backend.analysis.m1_request.precheck import _dropped_by

    cand = NS(filtered_out=[NS(ticker="AEP", reason="min_market_cap_usd"), NS(ticker="D", reason="min_market_cap_usd(estimated)")],
              candidates=[NS(ticker="AMT"), NS(ticker="NEE")])  # fmt: skip
    sel = NS(selected=[NS(ticker="NEE")], rejected=[NS(ticker="AMT", reason="metric_missing (eps<=0 or no financials)")])
    by = _dropped_by(["AEP", "D", "AMT", "NEE", "XYZ"], cand, sel)
    assert by == {"min_market_cap_usd": 2, "metric_missing": 1, "not_in_candidates": 1}
    assert _start_why_ko({"dropped_by": by}, {"min_market_cap_usd": 5e10}) == (
        "분석 기준일 선정 종목 중 4개를 시작일에는 고를 수 없습니다: 그날 시가총액이 최소 시가총액(500억 달러)에 못 미침 2개, "
        "그날 선정 지표 자료 없음 1개, 그날 후보 검색에 없음(상장 전이거나 조건 밖) 1개.")
    assert _start_why_ko({}, {}).startswith("과거에는 상장 전이거나")  # 사유를 모르면 예전 문장


def test_round16_financing_filings_and_scaled_walkforward_deltas():
    """048: Vistra 의 사채 발행 8-K(1.01 + 2.03)를 수집기가 '주요 계약' 으로 저장해 뷰 LLM 이 'VST 오름' 근거로 썼다 → 읽을 때 '채무·보증 부담'.
    048: 서술의 날짜별 차이가 뉴스 반영 구성(투자 70%) 값이라 바로 아래 맞춤안(주식 35%) 타임라인의 두 배였다 → 같은 비율로 줄인다."""
    from backend.analysis.m2_data.disclosure_labels import event_type_of
    from backend.analysis.m5_backtest_report import report as RP
    from backend.analysis.m5_backtest_report import report_blocks as RB

    sec = {"source": "SEC", "form": "8-K", "event_type": "material_agreement"}
    assert event_type_of({**sec, "items": "1.01,2.03,9.01"}) == "debt_obligation"
    assert event_type_of({**sec, "items": "1.01,9.01"}) == "material_agreement"
    assert event_type_of({**sec, "source": "DART", "items": "1.01,2.03"}) == "material_agreement"
    d = "2024-01-02"
    R = {"portfolio": {"walkforward": {"portfolios": [{"id": "wf_bl_news", "kind": "black_litterman", "weights_by_date": {d: {"A": 0.40, "B": 0.30}}},
                                                     {"id": "wf_equal_weight", "kind": "template", "weights_by_date": {d: {"A": 0.35, "B": 0.35}}}]},
                       "targets": {"baseline": {"id": "equal_weight"}}},
         "backtest": {"portfolios": [{"id": "dd_match_wf_bl_news", "kind": "matched", "base_id": "wf_bl_news", "name_ko": "낙폭 맞춤안",
                                      "weights_by_date": {d: {"A": 0.20, "B": 0.15}}}, {"id": "equal_weight", "kind": "template"}]}}  # fmt: skip
    assert RB.walkforward_top_deltas(R) == {d: ["A +5.0%p", "B -5.0%p"]}
    assert RB.walkforward_top_deltas(R, chosen="dd_match_wf_bl_news") == {d: ["A +2.5%p", "B -2.5%p"]}
    f = RP._top_delta_facts(R, "dd_match_wf_bl_news")
    assert f["top_delta_by_date"] == {d: ["A +2.5%p", "B -2.5%p"]} and "주식 비율로 줄인 차이" in f["top_delta_note"]
    assert "top_delta_note" not in RP._top_delta_facts(R, "equal_weight")


def test_stored_weights_never_eat_into_minimum_cash():
    """041 최종 재실행: walk-forward 동일비중 25종목을 소수 6자리로 반올림해 합이 0.85001 → 현금 14.999% < 최소 현금 15%. 내림으로 저장한다."""
    import numpy as np

    from backend.analysis.m4_portfolio.math import weights_out

    w = np.array([1.0] * 22 + [0.6, 0.6, 0.6])
    w = w / w.sum() * 0.85
    out, cash = weights_out([f"T{i}" for i in range(25)], w)
    assert sum(out.values()) <= 0.85 + 1e-12 and cash >= 0.15 and cash - 0.15 < 25e-6
    assert weights_out(["A", "B"], np.array([0.034, -1e-17])) == ({"A": 0.034, "B": 0.0}, 0.966)


def test_round17_decisions_fossil_utilities_news_minimum_broad_start_pool(monkeypatch):
    """사용자 결정(2026-11-05, 판단 위임) 세 가지.
    4) 화석연료 제외는 석유·가스·석탄 생산·정제·운송 회사 — 전기·가스 유틸리티(GICS 55)는 빼지 않고 알린다 (024: 유틸리티 13개 제외).
    5) 뉴스 뷰에 필요한 근거 있는 종목 수는 종목 수의 절반(올림)까지 낮춘다 (2종목이면 3개를 영영 못 채웠다).
    6) 넓은 테마의 시작일 재선정은 그날 후보 전체에서 (기준일 지표 순으로 자른 후보와의 교집합은 선견)."""
    import datetime as dt
    from types import SimpleNamespace as NS

    from backend.analysis.common.llm import StubLlm
    from backend.analysis.common.warnings import from_text
    from backend.analysis.m3_selection.classify import classify
    from backend.analysis.m4_portfolio import spec as S
    from backend.analysis.m4_portfolio.construct import news_min_tickers
    from backend.analysis.schemas.selection import Candidates

    def cand(t, sec):
        return {"ticker": t, "name": t, "market": "US", "gics": {"sector": {"code": sec, "name": "x"}, "industry_group": {"code": sec + "10", "name": "x"},
                "industry": {"code": sec + "1010", "name": "x"}, "sub_industry": {"code": sec + "101010", "name": "x"}}, "company_summary": "s",
                "matched_by": ["gics"], "matched_themes": ["inc"], "forced": False}  # fmt: skip

    cands = Candidates.model_validate({"request_id": "r", "as_of": "2025-06-25", "candidates": [cand("ED", "55"), cand("XOM", "10")], "filtered_out": [], "stats": {}, "warnings": []})
    intent = {"interpretation": {"themes": [{"id": "inc", "label_ko": "인컴", "description_ko": "d"}]}, "screen": {"theme_filter": {"min_confidence": 0.5}},
              "exclude_theme_rules": [{"theme": "fossil_fuels", "keywords": ["oil", "natural gas"]}]}  # fmt: skip
    ans = {"results": [{"ticker": t, "in_theme": True, "themes": ["inc"], "confidence": 0.9, "reason_ko": "", "excluded_theme": "fossil_fuels"} for t in ("ED", "XOM")]}
    tag = classify(cands, intent, StubLlm({"04_classify": ans}))
    assert tag.passed_tickers == ["ED"] and [r.ticker for r in tag.excluded_by_theme] == ["XOM"]
    w = from_text("04_tagging", next(x for x in tag.warnings if "utility kept" in x))
    assert w.code == "utility_not_fossil" and w.level == "user" and "ED" in w.message_ko

    assert [news_min_tickers(3, n) for n in (1, 2, 3, 4, 5, 20)] == [1, 1, 2, 2, 3, 3]

    seen = {}
    monkeypatch.setattr(S, "retrieve", lambda view, desc, it, cons, **k: NS(candidates=[NS(ticker=t) for t in ("A", "B", "C", "D", "E")], filtered_out=[], stats={}))
    monkeypatch.setattr(S, "_exclude_keyword_hits", lambda desc, kws: {"D": {"oil"}, "A": {"oil"}})
    monkeypatch.setattr(S, "mcap_warnings", lambda *a, **k: [])

    def fake_screen(view, desc, tag_, it, cons, request_id):
        seen["pool"] = list(tag_.passed_tickers)
        return NS(summary={}, warnings=[]), []

    monkeypatch.setattr(S, "screen", fake_screen)
    md = NS(view=lambda d: NS(as_of=d), s=NS(market=NS(mcap_fallback_max_days=730)))
    it2 = {"exclude_theme_rules": [{"theme": "fossil_fuels", "keywords": ["oil"]}]}
    S.selectable_at(md, dt.date(2023, 1, 3), None, it2, {}, ["A", "B"], "r")
    assert seen["pool"] == ["A", "B"]  # 테마 판정이 있는 테마: 기준일 통과 종목만 (그대로)
    S.selectable_at(md, dt.date(2023, 1, 3), None, it2, {}, ["A", "B"], "r", broad=True, excluded=["E"])
    assert seen["pool"] == ["A", "B", "C"]  # 넓은 테마: 그날 후보 전체 − 기준일 제외 판정(E) − 판정 없이 제외 키워드가 맞은 D (A 는 기준일 판정을 통과)


def test_round17_ties_lookahead_labels_and_small_texts():
    """055: MDD 0.300550 vs 0.300551 이 반올림 경계에서 갈려 같은 성과 14개 중 사용자 기준 비중이 졌다 → 허용 오차 단계.
    054: 시작일 재선정 없이 지금 목록으로 평가했는데 '백테스트용 재선정'·시작일 PER(기준일 값 복사)이 나왔다. 052: 원화 합 10,000,006원,
    뷰 설명의 남의 기사 id. 055: '매월 250 USD'(250.50)."""
    from backend.analysis.m4_portfolio.views import _strip_unlisted_ids
    from backend.analysis.m5_backtest_report import report_blocks as RB
    from backend.analysis.m5_backtest_report.validate import tie_levels

    lv = tie_levels({"bl_02": 0.300550, "market_cap": 0.300551, "eq": 0.300549, "x": 0.31}, 5e-5, higher_first=False)
    assert lv["bl_02"] == lv["market_cap"] == lv["eq"] == 0 and lv["x"] == 1
    lv = tie_levels({"a": 0.335931, "b": 0.335930, "c": 0.30}, 5e-5, higher_first=True)
    assert lv["a"] == lv["b"] == 0 and lv["c"] == 1
    assert _strip_unlisted_ids("섀시 모듈 공급 보도(ev2691369와 별개로 공급 내용을 다룬 ev2691378)", {"ev2691378"}) == "섀시 모듈 공급 보도(공급 내용을 다룬 ev2691378)"
    R = {"selection": {"backtest_reselected": False, "backtest_as_of": {"diff_vs_original": {"added": [], "removed": []}, "table": [{"ticker": "A"}, {"ticker": "B"}]}}}
    t = RB.diff_table(R)
    assert t["title_ko"] == "백테스트에 쓴 종목 목록" and "시작일 재선정 없음" in t["note_ko"] and t["rows"][0]["v"] == "A, B"
