"""라운드 4 피드백: 검증 규칙 정리 — 사용자 기준(R1·R2·R3·R7)과 내부 점검(R4·R5·R8) 분리, 드리프트·투자 비율은 정보, 목표수익은 투자기간 구간 비율, 변동성은 비교지수 대비, 추천 순위."""

from __future__ import annotations

import numpy as np

from backend.analysis.m1_request.conditions import condition_rows
from backend.analysis.m5_backtest_report.validate import target_window_ratio
from backend.tests.analysis.test_pipeline_e2e import REQUEST, e2e  # noqa: F401


def test_target_window_ratio():
    idx = list(100 * (1.0 + 0.10) ** (np.arange(0, 252 * 4) / 252))  # 매년 10% 꾸준히
    r = target_window_ratio(idx, 1.0, 0.08, 252)
    assert r and r["ratio"] == 1.0 and abs(r["median"] - 0.10) < 1e-6 and r["n"] == 252 * 3
    assert target_window_ratio(idx, 1.0, 0.12, 252)["ratio"] == 0.0
    assert target_window_ratio(idx[:100], 1.0, 0.08, 252) is None  # 창이 투자기간보다 짧음


def test_user_rules_and_integrity_are_separated(e2e):
    ctx, _ = e2e
    val = ctx.outputs["12_validation"]
    for r in val["results"]:
        rules = {c["rule"]: c for c in r["checks"]}
        assert set(rules) >= {"R1", "R2", "R3", "R7", "R4b", "R5b", "R9"} and not {"R4", "R5", "R8", "R6"} & set(rules)
        assert {c["rule"] for c in r["integrity"]} == {"R4", "R5", "R8"} and all(c["status"] == "pass" for c in r["integrity"])
        assert rules["R4b"]["level"] == "info" and rules["R5b"]["level"] == "info" and rules["R9"]["level"] == "info"
        assert all("ok" in c for c in r["checks"])
        assert "같은 기간" in rules["R1"]["message_ko"]  # 비교지수 낙폭 동반
        if "R1b" in rules:
            assert rules["R1b"]["level"] == "info"
        assert "구간" in rules["R2"]["message_ko"] or "전체 CAGR" in rules["R2"]["message_ko"]
        assert "비교지수" in rules["R7"]["message_ko"] or "상한을 두지" in rules["R7"]["message_ko"]
    s = val["summary"]
    assert s["n_pass"] + s["n_warn"] + s["n_fail"] == len(val["results"])
    rec = val.get("recommended")
    assert rec and val["chosen_id"] == rec["id"] and val["alternatives"] == []  # 라운드 5: 추천은 항상 하나, 현금 혼합안 없음
    assert rec["verdict"]["status"] in ("recommended", "recommended_warn", "insufficient") and rec["reason_ko"].startswith("후보 ")
    assert ("여유" in rec["reason_ko"]) or ("초과" in rec["reason_ko"])
    assert "조건을 만족하고" not in rec["reason_ko"]
    for r in val["results"]:
        r1 = next(c for c in r["checks"] if c["rule"] == "R1")
        assert r1["level"] == "flag" and r1["status"] in ("pass", "flag") and r["status"] != "fail"  # 낙폭은 합격 기준이 아니다
    # 리포트: 대시보드 규칙 목록은 정보 제외, 실행 기록에 내부 점검 한 줄
    doc = ctx.outputs["14_report"]
    v = doc["summary"]["validation"]
    assert v["rules_ko"] and all(x["level"] != "info" for x in v["rules_ko"]) and {x["rule"] for x in v["rules_ko"]} <= {"R1", "R2", "R3", "R7"}
    assert v["tolerance_note_ko"].startswith("손실 감내 수준") or "입력" in v["tolerance_note_ko"]
    ex = next(b for s_ in doc["sections"] for b in s_["blocks"] if b["type"] == "table" and b.get("title_ko") == "실행 기록")
    assert any(r["stage"] == "내부 점검" and "통과" in r["what"] for r in ex["rows"])
    t1 = next(b for s_ in doc["sections"] for b in s_["blocks"] if b["type"] == "table" and str(b.get("title_ko", "")).startswith("검증 규칙"))
    assert not any(r["rule"] in ("R4", "R5", "R8") for r in t1["rows"]) and "표시 = " in (t1.get("note_ko") or "")


def test_effective_tolerance_row_appears_only_when_adjusted():
    import copy

    req = copy.deepcopy(REQUEST)
    rows = {r.field: r for r in condition_rows(req, req)}
    assert "derived.effective_max_drawdown" not in rows  # hold + beginner: 보정 없음
    req2 = copy.deepcopy(REQUEST)
    req2["risk"]["loss_reaction"] = "sell"
    req2["profile"]["investment_experience"] = "none"
    r = {r.field: r for r in condition_rows(req2, req2)}["derived.effective_max_drawdown"]
    assert r.group_ko == "위험" and r.label_ko == "낙폭 맞춤안 목표" and "25.2%" in r.value_ko and "35.0%" in r.value_ko and "0.8배" in r.value_ko and "0.9배" in r.value_ko and r.source == "derived"
