"""투자성향 → 추천 전략 (GET /strategy/recommendation): 고정 규칙 표, 서버가 아는 전략 값, 프런트 목업 표와 같은지, API 422."""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import pytest
from fastapi.testclient import TestClient

from backend.analysis.api.app import API_PREFIX as P
from backend.analysis.api.app import create_analysis_app
from backend.analysis.common.llm import StubLlm
from backend.analysis.m1_request.strategy_recommendation import NOTE_KO, Tendency, recommend
from backend.analysis.schemas import request as R
from backend.analysis.settings import AnalysisSettings

TENDENCIES = get_args(Tendency)
MOCK_TABLE = Path(__file__).resolve().parents[3] / "Front" / "src" / "mocks" / "data" / "strategy.ts"
KEYS = ("template", "baseline_weighting", "use_news_tilt")


def _combo(x: dict) -> tuple:
    return tuple(x[k] for k in KEYS)


@pytest.mark.parametrize("tendency", TENDENCIES)
def test_every_tendency_gives_valid_distinct_strategies(tendency):
    r = recommend(tendency)
    assert r["tendency"] == tendency and r["note_ko"] == NOTE_KO
    assert len(r["reasons_ko"]) == 3 and all(r["reasons_ko"])
    assert len(r["alternatives"]) == 2 and all(a["diff_ko"] for a in r["alternatives"])
    assert "diff_ko" not in r["recommended"]
    for s in (r["recommended"], *r["alternatives"]):  # 저장할 때 서버 검증(StrategyPreference)을 통과하는 값만
        assert R.StrategyPreference(**{k: s[k] for k in KEYS}).model_dump() == {k: s[k] for k in KEYS}
    combos = [_combo(r["recommended"]), *map(_combo, r["alternatives"])]
    assert len(set(combos)) == 3  # 다른 전략은 추천과도, 서로도 다르다


def test_rule_values():
    """팀이 고른 고정 규칙 (2026-11-10). 바꾸려면 이 표와 프런트 목업 표를 함께 바꾼다."""
    assert {t: _combo(recommend(t)["recommended"]) for t in TENDENCIES} == {
        "안정형": ("high_dividend", "min_variance", False),
        "안정추구형": ("low_volatility", "inverse_volatility", False),
        "위험중립형": ("quality", "equal_weight", True),
        "적극투자형": ("momentum", "market_cap", True),
        "공격투자형": ("momentum", "equal_weight", True),
    }


def test_result_is_a_copy():
    r = recommend("안정형")
    r["recommended"]["template"] = "momentum"
    r["reasons_ko"].clear()
    r["alternatives"][0]["diff_ko"] = ""
    again = recommend("안정형")
    assert again["recommended"]["template"] == "high_dividend" and len(again["reasons_ko"]) == 3 and again["alternatives"][0]["diff_ko"]


@pytest.mark.skipif(not MOCK_TABLE.exists(), reason="프런트 소스가 없는 배포본")
def test_same_as_front_mock_table():
    """목업(?mock=1)과 실제 서버가 같은 추천을 보이도록, 서버 표의 조합·문장이 목업 표에 그대로 있는지 본다."""
    src = MOCK_TABLE.read_text(encoding="utf-8")
    js = {True: "true", False: "false"}
    for t in TENDENCIES:
        r = recommend(t)
        block = src.split(f"  {t}: {{", 1)[1].split("\n  },", 1)[0]  # 목업 표에서 이 성향의 칸
        rec = r["recommended"]
        assert f'rec: s("{rec["template"]}", "{rec["baseline_weighting"]}", {js[rec["use_news_tilt"]]})' in block, t
        for a in r["alternatives"]:
            assert f's("{a["template"]}", "{a["baseline_weighting"]}", {js[a["use_news_tilt"]]}), diff_ko: "{a["diff_ko"]}"' in block, t
        for reason in r["reasons_ko"]:
            assert f'"{reason}"' in block, t


def test_api(tmp_path):
    def no_db():
        raise AssertionError("추천은 DB 를 읽지 않는다")

    c = TestClient(create_analysis_app(no_db, store_dir=tmp_path / "store", settings=AnalysisSettings(), llm=lambda: StubLlm()))
    r = c.get(f"{P}/strategy/recommendation", params={"tendency": "위험중립형"})
    assert r.status_code == 200 and r.json() == recommend("위험중립형")
    for params in ({}, {"tendency": "moderate"}, {"tendency": "중립형"}):
        r = c.get(f"{P}/strategy/recommendation", params=params)
        assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR", params


# ───────────────────────── 투자 목적 규칙 (2026-11-11, docs/update_hojin_11.11.md) ─────────────────────────
from backend.analysis.m1_request.strategy_recommendation import _PURPOSE, PURPOSE_ALT_DIFF  # noqa: E402


@pytest.mark.parametrize("tendency", TENDENCIES)
def test_purpose_rules(tendency):
    base = recommend(tendency)
    assert recommend(tendency, "wealth_growth") == base == recommend(tendency, None)  # 자산 증식은 성향 표 그대로
    assert recommend(tendency, "income")["recommended"] == {**base["recommended"], "template": "high_dividend"}
    assert recommend(tendency, "capital_preservation")["recommended"] == {"template": "low_volatility", "baseline_weighting": "min_variance", "use_news_tilt": False}
    ret = recommend(tendency, "retirement")["recommended"]
    assert ret == ({**base["recommended"], "template": "quality"} if tendency in ("위험중립형", "적극투자형", "공격투자형") else base["recommended"])
    for p in ("income", "capital_preservation", "retirement"):
        r = recommend(tendency, p)
        if r["recommended"] == base["recommended"]:
            assert r == base  # 바뀌지 않으면 이유·다른 전략도 그대로
            continue
        assert r["reasons_ko"][0] == _PURPOSE[p]["reasons"]["template"]
        assert r["alternatives"][0] == {**base["recommended"], "diff_ko": PURPOSE_ALT_DIFF}  # 성향만 본 추천을 첫 번째 다른 전략으로
        assert r["recommended"] not in [{k: a[k] for k in ("template", "baseline_weighting", "use_news_tilt")} for a in r["alternatives"]]


def test_purpose_rules_same_as_front_mock():
    src = MOCK_TABLE.read_text(encoding="utf-8")
    assert f'const PURPOSE_ALT_DIFF = "{PURPOSE_ALT_DIFF}"' in src
    for p, rule in _PURPOSE.items():
        block = src.split(f"  {p}: {{", 1)[1].split("\n", 1)[0]
        for k, v in rule["set"].items():
            assert (f"{k}: {str(v).lower()}" if isinstance(v, bool) else f'{k}: "{v}"') in block, (p, k)
        for k, text in rule["reasons"].items():
            assert f'{k}: "{text}"' in block, (p, k)
        if "only" in rule:
            assert "only: " + json.dumps(list(rule["only"]), ensure_ascii=False).replace('","', '", "') in block, p


def test_api_purpose(tmp_path):
    def no_db():
        raise AssertionError("추천은 DB 를 읽지 않는다")

    c = TestClient(create_analysis_app(no_db, store_dir=tmp_path / "store", settings=AnalysisSettings(), llm=lambda: StubLlm()))
    r = c.get(f"{P}/strategy/recommendation", params={"tendency": "공격투자형", "purpose": "income"})
    assert r.status_code == 200 and r.json() == recommend("공격투자형", "income")
    r = c.get(f"{P}/strategy/recommendation", params={"tendency": "공격투자형", "purpose": "travel"})
    assert r.status_code == 422
