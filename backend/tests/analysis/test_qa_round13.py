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
