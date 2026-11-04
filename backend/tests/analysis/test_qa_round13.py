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
    assert C._matched_label_ko({"by_rule": {"example_match": 4, "must_include": 1}}) == "테마 관련 종목 (찾은 방법: 예시 종목 4개)"


def test_round13_replay_leftovers():
    """033 재실행: '제시된 모멘텀 지표만으로' 가 남았다(자료를 가리킬 때만 지운다). 036 재실행: '2026 회계연도' 를 '2026회' 로 읽어 숫자 대조 메모가 생겼다."""
    from backend.analysis.m5_backtest_report import report as RP
    from backend.analysis.m5_backtest_report.report_check import NUM_RE

    assert RP._plain_llm("제시된 자료로는 판단하기 어렵고, 가이던스에 제시된 목표는 유지") == "자료로는 판단하기 어렵고, 가이던스에 제시된 목표는 유지"
    assert [m.group(2) for m in NUM_RE.finditer("2026 회계연도 전망, 리밸런싱 3회") if m.group(1).strip(",")] == [None, "회"]
