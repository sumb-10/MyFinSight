"""홈 '요즘엔 뭐가 좋아요?' 섹터 성과 (2026-11-11): 판별 규칙, 성향별 추천, 계산 작업(진행률·저장), API."""

from __future__ import annotations

import datetime as dt
import threading
import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.analysis.api.app import API_PREFIX, create_analysis_app
from backend.analysis.common.llm import StubLlm
from backend.analysis.common.store import JsonStore
from backend.analysis.m2_data import sector_trends as ST
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.settings import AnalysisSettings, replace_settings
from backend.db import open_repository
from backend.tests.analysis.conftest import seed_repository

END = dt.date(2026, 11, 9)


def test_one_month_before():
    assert ST.one_month_before(dt.date(2026, 11, 9)) == dt.date(2026, 10, 9)
    assert ST.one_month_before(dt.date(2026, 3, 31)) == dt.date(2026, 2, 28)


def _market(returns: dict[str, list[float]], *, holiday: dt.date | None = None):
    """섹터별 종목 한 달 수익률대로 가격을 만든다. 한 달 전까지는 100, 그 뒤 기준일까지 일정하게 오른다."""
    days = [d for d in pd.bdate_range("2026-06-01", END) if d.date() != holiday]
    cal = pd.DatetimeIndex(days)
    base = cal[cal <= pd.Timestamp(ST.one_month_before(END))][-1]
    n_after = int((cal > base).sum())
    cols, stocks = {}, []
    for sec, rs in returns.items():
        for i, r in enumerate(rs):
            t = f"{sec}{i}"
            px = np.full(len(cal), 100.0)
            px[cal > base] = 100 * (1 + r) ** (np.arange(1, n_after + 1) / n_after)
            cols[t] = px
            stocks.append({"ticker": t, "name": f"{sec} 회사 {i}", "sector_code": sec, "sector_ko": f"섹터{sec}"})
    px = pd.DataFrame(cols, index=cal)
    bench = pd.Series(np.linspace(100, 103, len(cal)), index=cal, name="SPY")
    return px, bench, stocks, base


def test_good_sector_rules():
    rets = {
        "A": [0.10] * 6,                          # 좋음
        "B": [0.30, 0.05, 0.02, -0.01, -0.02],    # 평균 +6.8%, 5개 중 3개 상승 → 좋음
        "C": [0.20] * 4,                          # 종목 4개 → 뺌
        "D": [0.50, -0.05, -0.05, -0.05, -0.05],  # 평균 +6% 지만 1개만 상승 → 뺌
        "E": [-0.10] * 5,                         # 하락 → 뺌
        "F": [0.01] * 6,                          # 시장 평균(약 +5.2%)보다 낮음 → 뺌
    }
    px, bench, stocks, base = _market(rets)
    m = ST.summarize_market("US", px, bench, stocks, END)
    assert m["end_date"] == "2026-11-09" and m["base_date"] == str(base.date()) == "2026-10-09"
    assert m["n"] == 31 and m["avg_return"] == pytest.approx(1.6 / 31, abs=1e-6)
    by = {s["code"]: s for s in m["sectors"]}
    assert [s["code"] for s in m["sectors"]] == ["C", "A", "B", "D", "F", "E"]  # 평균 순
    assert {c for c, s in by.items() if s["good"]} == {"A", "B"}
    assert m["top"] == ["A", "B"]
    assert by["B"]["avg_return"] == pytest.approx(0.068) and (by["B"]["n"], by["B"]["up"]) == (5, 3)
    assert [x["ticker"] for x in by["B"]["leaders"]] == ["B0", "B1", "B2"]
    assert by["A"]["prompt_ko"] == "요즘 많이 오른 미국 섹터A 기업에 나눠 투자하고 싶어요."
    assert m["benchmark"]["ticker"] == "SPY" and m["benchmark"]["label_ko"] == "S&P 500" and m["benchmark"]["return"] > 0


def test_top_is_at_most_three_and_base_day_skips_holiday():
    rets = {k: [0.05 + 0.01 * i] * 5 for i, k in enumerate("ABCDE")}
    rets["Z"] = [-0.30] * 10  # 시장 평균을 낮춘다
    px, bench, stocks, base = _market(rets, holiday=dt.date(2026, 10, 9))
    m = ST.summarize_market("KR", px, bench, stocks, END)
    assert m["base_date"] == "2026-10-08"  # 한 달 전 날이 휴장이면 그 전 거래일
    assert m["top"] == ["E", "D", "C"]
    assert m["label_ko"] == "한국"


def _mk(code: str, sectors: list[tuple[str, float, float | None]]) -> dict:
    rows = [{"code": c, "name_ko": f"섹터{c}", "avg_return": r, "vol_3m": v, "good": True} for c, r, v in sectors]
    return {"code": code, "label_ko": ST.MARKET_KO[code], "sectors": rows, "top": [c for c, _r, _v in sectors][:3]}


def test_pick_by_tendency():
    us = _mk("US", [("25", 0.106, 0.22), ("30", 0.099, 0.19), ("35", 0.095, 0.15)])
    p = ST.picks_for([us, _mk("KR", [])])
    assert p["US"]["안정형"]["code"] == "35" and p["US"]["안정추구형"]["code"] == "35"  # 변동성이 가장 작은 섹터
    assert p["US"]["위험중립형"]["code"] == "35"  # 0.095/0.15 = 0.63 > 0.099/0.19 = 0.52 > 0.106/0.22 = 0.48
    assert p["US"]["적극투자형"]["code"] == "25" and p["US"]["공격투자형"]["code"] == "25"  # 수익률 1위
    assert p["US"]["안정형"]["text_ko"] == "안정형에 맞는 섹터는 미국 섹터35입니다. 최근 한 달 +9.50% 올랐고, 성과가 좋았던 섹터 중 최근 3개월 주가 오르내림이 가장 작았습니다."
    assert p["US"]["위험중립형"]["text_ko"].endswith("주가 오르내림에 비해 오른 폭이 가장 컸습니다.")
    assert p["US"]["공격투자형"]["text_ko"] == "공격투자형에 맞는 섹터는 미국 섹터25입니다. 최근 한 달 +10.60% 올랐고, 성과가 좋았던 섹터 중 가장 많이 올랐습니다."
    assert p["KR"]["안정형"]["code"] is None and p["KR"]["안정형"]["text_ko"] == "최근 한 달은 시장 평균보다 많이 오른 섹터가 없습니다."


def test_pick_only_from_shown_sectors_and_all_scope():
    us = _mk("US", [("25", 0.10, 0.30), ("30", 0.09, 0.25), ("35", 0.08, 0.20), ("55", 0.07, 0.05)])  # 55 는 4위라 상자에 없다
    kr = _mk("KR", [("35", 0.20, 0.40)])
    p = ST.picks_for([us, kr])
    assert p["US"]["안정형"]["code"] == "35"  # 변동성이 더 작은 55 는 상자에 보이지 않아 고르지 않는다
    assert (p["ALL"]["공격투자형"]["market"], p["ALL"]["공격투자형"]["code"]) == ("KR", "35")  # 미국·한국 함께
    assert p["ALL"]["공격투자형"]["text_ko"].startswith("공격투자형에 맞는 섹터는 한국 섹터35입니다.")
    assert (p["ALL"]["안정형"]["market"], p["ALL"]["안정형"]["code"]) == ("US", "35")


def test_compute_on_seeded_repo(seeded_repo, descriptor_dir):
    s = AnalysisSettings()
    s = replace_settings(s, market=replace_settings(s.market, descriptor_dir=str(descriptor_dir)))
    md = MarketData(seeded_repo, s)
    steps: list[float] = []
    out = ST.compute_sector_trends(md, s, progress=steps.append, now=lambda: dt.datetime(2026, 1, 5, 9, 0))
    assert out["as_of"] == str(md.ceiling) == "2025-12-31" and out["rule_version"] == ST.RULE_VERSION
    assert steps == sorted(steps) and steps[-1] == 1.0 and len(steps) >= 4  # 진행률은 늘기만 하고 1 로 끝난다
    us, kr = (next(m for m in out["markets"] if m["code"] == c) for c in ("US", "KR"))
    assert us["base_date"] == "2025-11-28"  # 11-30 은 일요일 (11-27 은 미국 휴장)
    assert us["n"] == 16 and kr["n"] == 4
    it = next(x for x in us["sectors"] if x["code"] == "45")
    assert it["name_ko"] == "정보기술" and it["n"] == 6
    assert all(x["n"] >= ST.MIN_STOCKS for x in us["sectors"] if x["good"])  # 종목 5개 이상만
    assert kr["top"] == [] and out["picks"]["KR"]["안정형"]["code"] is None  # 한국은 섹터마다 종목이 5개 미만
    assert set(out["picks"]) == {"US", "KR", "ALL"} and set(out["picks"]["US"]) == set(ST.TENDENCIES)


class _Gate:
    """계산 작업 흉내: 열릴 때까지 진행률 0.5 에서 기다린다."""

    def __init__(self, fail: bool = False) -> None:
        self.open, self.calls, self.fail = threading.Event(), 0, fail

    def __call__(self, progress):
        self.calls += 1
        progress(0.5)
        assert self.open.wait(5)
        if self.fail:
            raise RuntimeError("DB 연결 끊김")
        return {"rule_version": ST.RULE_VERSION, "as_of": "2026-11-09", "markets": [], "picks": {}}


def _until(f, timeout=5.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        v = f()
        if v:
            return v
        time.sleep(0.01)
    raise AssertionError("시간 안에 끝나지 않음")


def test_job_loading_then_ready_and_cache(tmp_path):
    store, gate = JsonStore(tmp_path), _Gate()
    job = ST.SectorTrendsJob(store, gate)
    first = job.status(END)
    assert first["status"] == "loading" and first["data"] is None
    _until(lambda: job.status(END)["progress"] == 0.5)
    gate.open.set(); job.wait()
    ready = job.status(END)
    assert ready["status"] == "ready" and ready["progress"] == 1.0 and ready["data"]["as_of"] == "2026-11-09"
    assert store.read(ST.STORE_REL)["as_of"] == "2026-11-09"
    assert ST.SectorTrendsJob(store, gate).status(END)["status"] == "ready" and gate.calls == 1  # 서버를 다시 켜도 저장해 둔 결과
    assert job.status(None)["status"] == "ready"  # DB 에 닿지 못하면 저장해 둔 결과 그대로
    gate.open.clear()
    newer = job.status(dt.date(2026, 11, 10))  # 새 거래일 → 다시 계산, 그동안 지난 결과를 함께 준다
    assert newer["status"] == "loading" and newer["data"]["as_of"] == "2026-11-09"
    _until(lambda: gate.calls == 2)
    gate.open.set(); job.wait()


def test_job_error_then_retry(tmp_path):
    now = [0.0]
    gate = _Gate(fail=True)
    gate.open.set()
    job = ST.SectorTrendsJob(JsonStore(tmp_path), gate, retry_after_s=30, clock=lambda: now[0])
    job.status(END); job.wait()
    err = job.status(END)
    assert err["status"] == "error" and "DB 연결 끊김" in err["error"] and gate.calls == 1
    now[0] = 31.0
    assert job.status(END)["status"] == "loading"  # 30초가 지나면 다시 시도
    job.wait()
    assert gate.calls == 2


def test_job_asks_latest_day_only_when_needed(tmp_path):
    """계산 중에는 최신 거래일을 묻지 않고, 결과가 있으면 1분에 한 번만 묻는다 (화면이 0.4초마다 진행률을 묻는다)."""
    now, asked = [0.0], []
    store, gate = JsonStore(tmp_path), _Gate()
    job = ST.SectorTrendsJob(store, gate, clock=lambda: now[0])

    def latest():
        asked.append(now[0])
        return END

    assert job.status(latest)["status"] == "loading" and asked == []  # 결과가 없으면 묻지 않고 바로 계산
    assert job.status(latest)["status"] == "loading" and asked == []
    gate.open.set(); job.wait()
    assert job.status(latest)["status"] == "ready" and asked == [0.0]
    now[0] = 59.0
    assert job.status(latest)["status"] == "ready" and asked == [0.0]
    now[0] = 61.0
    assert job.status(latest)["status"] == "ready" and asked == [0.0, 61.0]
    now[0] = 130.0
    assert job.status(lambda: (_ for _ in ()).throw(RuntimeError("DB 끊김")))["status"] == "ready"  # 못 물어보면 저장해 둔 결과 그대로


@pytest.fixture(scope="module")
def trends_api(descriptor_dir, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("trends_api")
    repo = open_repository(f"sqlite:///{tmp / 'api.db'}", clock=lambda: dt.datetime(2026, 1, 5, tzinfo=dt.UTC))  # 파일 DB: 계산은 다른 스레드에서 돈다
    seed_repository(repo)
    s = AnalysisSettings()
    s = replace_settings(s, market=replace_settings(s.market, valuation_max_staleness_days=10, descriptor_dir=str(descriptor_dir)))
    app = create_analysis_app(lambda: repo, store_dir=tmp / "store", settings=s, llm=lambda: StubLlm(), cors_origins=["http://localhost:5173"])
    return TestClient(app, raise_server_exceptions=False), JsonStore(tmp / "store"), repo, s


def test_api_sector_trends(trends_api):
    client, store, *_ = trends_api
    url = f"{API_PREFIX}/market/sector-trends"
    first = client.get(url).json()
    assert first["status"] in ("loading", "ready") and 0 <= first["progress"] <= 1
    body = _until(lambda: (r := client.get(url).json())["status"] == "ready" and r)
    assert body["error"] is None and body["data"]["as_of"] == "2025-12-31"
    assert {m["code"] for m in body["data"]["markets"]} == {"US", "KR"}
    assert store.read(ST.STORE_REL)["as_of"] == "2025-12-31"
    assert client.get(url).json()["status"] == "ready"


def test_api_warms_on_start(trends_api, tmp_path):
    """uvicorn 이 쓰는 앱(warm=True)은 켜질 때 뒤에서 미리 계산한다. 테스트·다른 앱(warm=False)은 하지 않는다."""
    _c, _s, repo, s = trends_api
    cold = create_analysis_app(lambda: repo, store_dir=tmp_path / "cold", settings=s, llm=lambda: StubLlm())
    with TestClient(cold):
        time.sleep(0.3)
    assert JsonStore(tmp_path / "cold").read(ST.STORE_REL) is None
    warm = create_analysis_app(lambda: repo, store_dir=tmp_path / "warm", settings=s, llm=lambda: StubLlm(), warm=True)
    with TestClient(warm) as client:
        doc = _until(lambda: JsonStore(tmp_path / "warm").read(ST.STORE_REL))
        assert doc["as_of"] == "2025-12-31"
        assert client.get(f"{API_PREFIX}/market/sector-trends").json()["status"] == "ready"  # 홈을 열면 바로
