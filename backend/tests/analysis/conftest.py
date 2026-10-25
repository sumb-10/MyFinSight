"""분석 패키지 테스트 공통 픽스처: 합성 자료로 채운 sqlite Repository, 디스크립터 파일, 설정, stub LLM.

네트워크 없음 (backend/tests/conftest.py 가 차단). 가격은 종목별 고정 시드 GBM, 미국·한국 거래일은 평일에서
각기 다른 휴장일을 빼서 혼합 달력(합집합·직전값 유지)을 시험할 수 있게 한다.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pytest

from backend.analysis.common.llm import StubLlm
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.settings import AnalysisSettings, MarketSettings, replace_settings
from backend.db import open_repository
from backend.db.readers import descriptor_inputs
from backend.pipeline.descriptor import build_descriptors, write_descriptors
from backend.pipeline.gics import load_taxonomy
from backend.schemas.market import FxRate, IndexCode, IndexConstituent, PriceBar
from backend.schemas.market_ext import DisclosureRow, AssetInfo, NewsRow

AT = dt.datetime(2026, 1, 5, tzinfo=dt.UTC)
START = dt.date(2021, 1, 4)
END = dt.date(2025, 12, 31)  # 마지막 거래일 2025-12-31 (수)
US_HOLIDAYS = {dt.date(y, 7, 4) for y in range(2021, 2026)} | {dt.date(2025, 11, 27)}
KR_HOLIDAYS = {dt.date(y, 10, 3) for y in range(2021, 2026)} | {dt.date(2025, 12, 25), dt.date(2025, 10, 6)}

# (yfinance 표기, 이름, GICS 세부산업 8자리, 키워드/소개)
US_STOCKS = [
    ("NVDA", "NVIDIA", "45301020", "GPU and AI accelerator designer."),
    ("AMD", "Advanced Micro Devices", "45301020", "CPU and GPU semiconductor company."),
    ("AVGO", "Broadcom", "45301020", "Semiconductor and infrastructure software."),
    ("MU", "Micron Technology", "45301020", "Memory chips: DRAM and NAND."),
    ("AMAT", "Applied Materials", "45301010", "Semiconductor equipment maker."),
    ("MSFT", "Microsoft", "45103020", "Cloud computing and software."),
    ("GOOGL", "Alphabet Class A", "50203010", "Search, advertising and cloud."),
    ("GOOG", "Alphabet Class C", "50203010", "Search, advertising and cloud."),
    ("AMZN", "Amazon", "25503030", "E-commerce and cloud computing."),
    ("JNJ", "Johnson & Johnson", "35202010", "Pharmaceuticals and medical devices."),
    ("PFE", "Pfizer", "35202010", "Pharmaceutical company."),
    ("XOM", "Exxon Mobil", "10102010", "Integrated oil and gas."),
    ("JPM", "JPMorgan Chase", "40101010", "Diversified bank."),
    ("PG", "Procter & Gamble", "30301010", "Household products."),
    ("KO", "Coca-Cola", "30201030", "Soft drinks."),
    ("CAT", "Caterpillar", "20106010", "Construction machinery."),
]
KR_STOCKS = [
    ("005930.KS", "삼성전자", "45301020", "메모리 반도체와 스마트폰을 만드는 회사."),
    ("000660.KS", "SK하이닉스", "45301020", "DRAM·NAND 메모리 반도체 회사."),
    ("005380.KS", "현대차", "25102010", "자동차 제조사."),
    ("035420.KS", "NAVER", "50203010", "검색 포털과 커머스."),
]
ETFS = [("SPY", "SPDR S&P 500 ETF", "US"), ("QQQ", "Invesco QQQ", "US"), ("069500.KS", "KODEX 200", "KR")]


def business_days(start: dt.date, end: dt.date, holidays: set[dt.date]) -> list[dt.date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5 and d not in holidays:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def gbm(ticker: str, n: int, start_price: float) -> np.ndarray:
    rng = np.random.default_rng(abs(hash(ticker)) % (2**32))
    r = rng.normal(0.0004, 0.015, n)
    return start_price * np.exp(np.cumsum(r))


def _asset(sym: str, name: str, market: str, kind: str = "STOCK") -> AssetInfo:
    if market == "KR":
        code = sym[:-3]
        return AssetInfo(asset_id=f"KR-{code}", ticker=code, name=name, market="KR", exchange="KOSPI", currency="KRW",
                         yfinance_symbol=sym, asset_type=kind)  # fmt: skip
    return AssetInfo(asset_id=f"US-{sym}", ticker=sym, name=name, market="US", currency="USD", yfinance_symbol=sym, asset_type=kind)


def seed_repository(repo, *, start: dt.date = START, end: dt.date = END) -> dict:
    tax = load_taxonomy()
    repo.sync_gics_taxonomy(tax.rows())
    assets = [_asset(s, n, "US") for s, n, _c, _i in US_STOCKS] + [_asset(s, n, "KR") for s, n, _c, _i in KR_STOCKS]
    assets += [_asset(s, n, m, "ETF") for s, n, m in ETFS]
    repo.upsert_assets(assets)

    us_days, kr_days = business_days(start, end, US_HOLIDAYS), business_days(start, end, KR_HOLIDAYS)
    bars: list[PriceBar] = []
    for sym, _n, _c, _i in US_STOCKS + [(s, n, None, None) for s, n, m in ETFS if m == "US"]:
        px = gbm(sym, len(us_days), 50 + abs(hash(sym)) % 300)
        bars += [PriceBar(ticker=sym, date=d, adj_close=float(p), close=float(p) * 1.02, volume=1_000_000 + (abs(hash(sym + str(i))) % 500_000),
                          currency="USD", source="YFINANCE", fetched_at=AT) for i, (d, p) in enumerate(zip(us_days, px, strict=True))]  # fmt: skip
    for sym, _n, _c, _i in KR_STOCKS + [(s, n, None, None) for s, n, m in ETFS if m == "KR"]:
        px = gbm(sym, len(kr_days), 30_000 + abs(hash(sym)) % 100_000)
        bars += [PriceBar(ticker=sym, date=d, adj_close=float(p), close=float(p), volume=500_000, currency="KRW",
                          source="KIS", fetched_at=AT) for d, p in zip(kr_days, px, strict=True)]  # fmt: skip
    for i in range(0, len(bars), 5000):
        repo.upsert_prices(bars[i : i + 5000])

    all_days = business_days(start - dt.timedelta(days=14), end, set())
    rng = np.random.default_rng(7)
    fx = 1300 * np.exp(np.cumsum(rng.normal(0, 0.003, len(all_days))))
    repo.upsert_fx([FxRate(date=d, rate=float(r), source="YFINANCE", fetched_at=AT) for d, r in zip(all_days, fx, strict=True)])

    snap = dt.date(2024, 6, 21)  # 유일한 스냅샷 (실제 DB 처럼 하나)
    rows = []
    for sym, name, code, _intro in US_STOCKS:
        lv = tax.four_levels(code)
        rows.append(IndexConstituent(index_code=IndexCode.SP500, ticker=sym, name=name, sector=lv["sector"].name_en,
                                     industry=lv["sub_industry"].name_en, snapshot_date=snap, source="test", fetched_at=AT,
                                     gics_sub_industry_code=code))  # fmt: skip
        if sym in ("NVDA", "AMD", "AVGO", "MU", "AMAT", "MSFT", "GOOGL", "GOOG", "AMZN"):
            rows.append(rows[-1].model_copy(update={"index_code": IndexCode.NDX}))
    for sym, name, code, _intro in KR_STOCKS:
        lv = tax.four_levels(code)
        rows.append(IndexConstituent(index_code=IndexCode.KOSPI200, ticker=sym, name=name, sector=lv["sector"].name_en,
                                     industry=lv["sub_industry"].name_en, snapshot_date=snap, source="test", fetched_at=AT,
                                     gics_sub_industry_code=code))  # fmt: skip
    repo.save_constituents(rows)

    profiles = []
    for sym, _name, code, intro in US_STOCKS + KR_STOCKS:
        a = _asset(sym, _name, "KR" if sym.endswith(".KS") else "US")
        lv = tax.four_levels(code)
        profiles.append({"asset_id": a.asset_id, **tax.asset_columns(code), "gics_source": "KR_MAP_REVIEWED" if a.market == "KR" else "WIKIPEDIA_SP500",
                         "business_summary": intro, "business_summary_source": "TEST"})  # fmt: skip
    repo.update_asset_profiles(profiles)

    # 가치평가: 5거래일마다 한 행 (PER·ROE·배당수익률·시총·주식수)
    vrows = []
    for sym, _n, _c, _i in US_STOCKS + KR_STOCKS:
        a = _asset(sym, _n, "KR" if sym.endswith(".KS") else "US")
        days = kr_days if a.market == "KR" else us_days
        px = gbm(sym, len(days), 50 + abs(hash(sym)) % 300 if a.market == "US" else 30_000 + abs(hash(sym)) % 100_000)
        shares = 1e9 + (abs(hash(sym)) % 5) * 1e9
        per = 10 + (abs(hash(sym)) % 30)
        for i in range(0, len(days), 5):
            close = float(px[i]) * (1.02 if a.market == "US" else 1.0)
            vrows.append({"asset_id": a.asset_id, "date": days[i], "ticker": sym, "currency": a.currency, "close": close, "split_factor": 1.0,
                          "shares_outstanding": shares, "market_cap": close * shares, "net_income_ttm": close * shares / per,
                          "eps_ttm": close / per, "per": None if sym == "PFE" else per, "bps": close / 3, "pbr": 3.0,
                          "roe_ttm": 0.05 + (abs(hash(sym)) % 20) / 100, "dps_ttm": close * 0.02, "dividend_yield": 0.02 + (abs(hash(sym)) % 5) / 100,
                          "fin_period_end": days[i] - dt.timedelta(days=60), "fin_disclosed_at": days[i] - dt.timedelta(days=20),
                          "shares_as_of": days[i], "method": "TEST"})  # fmt: skip
    repo.upsert_valuation(vrows)

    # 뉴스: 2025-12-01 ~ 2025-12-30 사이 미국 8 + 한국 2 종목, 종목당 6건 (중복 제목 1건 포함)
    news = []
    for sym in ["NVDA", "AMD", "AVGO", "MU", "MSFT", "AMZN", "JNJ", "XOM", "005930.KS", "000660.KS"]:
        a = _asset(sym, sym, "KR" if sym.endswith(".KS") else "US")
        lang = "ko" if a.market == "KR" else "en"
        for k in range(6):
            day = dt.date(2025, 12, 1) + dt.timedelta(days=4 * k)
            title = f"{sym} headline {k if k < 5 else 4}"  # k=5 는 k=4 와 같은 제목 (중복)
            news.append(NewsRow(asset_id=a.asset_id, source="GOOGLE_RSS", url=f"https://news.test/{sym}/{k}", title=title,
                                publisher="Test Wire", published_at=dt.datetime(day.year, day.month, day.day, 13, tzinfo=dt.UTC),
                                language=lang, fetched_at=AT))  # fmt: skip
    repo.upsert_news(news)
    # 공시 (라운드 4): 2025-12 창에 사건 종류별로, 걸러져야 할 것(대량보유·수정 공시·ELS)도 함께. JPM 은 뉴스 없이 공시만.
    # 백테스트 시작 창(2023-12)에는 NVDA·AMD 두 종목만 → test_targets_constraints 의 "시작일 fallback" 단언 유지.
    discl = []

    def _d(sym, source, form, items, title, filed, avail, et, *, amend=False, fid=None):
        a = _asset(sym, sym, "KR" if sym.endswith(".KS") else "US")
        discl.append(DisclosureRow(asset_id=a.asset_id, source=source, filing_id=fid or f"{sym}-{filed:%Y%m%d}-{et}", form=form, items=items, title=title,
                                   filed_at=dt.datetime(filed.year, filed.month, filed.day, 21, tzinfo=dt.UTC), available_on=avail, is_amendment=amend,
                                   url=f"https://filings.test/{sym}/{filed:%Y%m%d}", event_type=et, rule_version="test", fetched_at=AT))  # fmt: skip

    for sym in ["NVDA", "AMD", "AVGO", "MU", "MSFT", "JPM"]:
        _d(sym, "SEC_EDGAR", "8-K", "2.02,9.01", "8-K", dt.date(2025, 12, 10), dt.date(2025, 12, 11), "earnings")
        _d(sym, "SEC_EDGAR", "8-K", "5.02", "8-K", dt.date(2025, 11, 20), dt.date(2025, 11, 21), "executive_change")
        _d(sym, "SEC_EDGAR", "SC 13G/A", None, "SC 13G/A", dt.date(2025, 12, 5), dt.date(2025, 12, 8), "major_holder")  # 제외 대상
    _d("NVDA", "SEC_EDGAR", "8-K/A", "2.02", "8-K/A", dt.date(2025, 12, 12), dt.date(2025, 12, 15), "earnings", amend=True)  # 수정 공시 제외
    _d("NVDA", "SEC_EDGAR", "8-K", "8.01", "8-K", dt.date(2025, 12, 30), dt.date(2025, 12, 31), "other_event")  # 이용 가능일 = 기준일 → 창 밖
    for sym in ["005930.KS", "000660.KS"]:
        _d(sym, "DART", "주요사항보고서(자기주식취득결정)", None, "주요사항보고서(자기주식취득결정)", dt.date(2025, 12, 3), dt.date(2025, 12, 4), "buyback")
        _d(sym, "DART", "연결재무제표기준영업(잠정)실적(공정공시)", None, "연결재무제표기준영업(잠정)실적(공정공시)", dt.date(2025, 11, 25), dt.date(2025, 11, 26), "earnings")
        _d(sym, "DART", "투자설명서(일괄신고)", None, "투자설명서(일괄신고)", dt.date(2025, 12, 1), dt.date(2025, 12, 2), "derivative_offering")  # 제외 대상
    for sym in ["NVDA", "AMD"]:  # 백테스트 시작 창
        _d(sym, "SEC_EDGAR", "8-K", "1.01", "8-K", dt.date(2023, 12, 12), dt.date(2023, 12, 13), "material_agreement")
    repo.upsert_disclosures(discl)
    return {"us_days": us_days, "kr_days": kr_days, "snapshot": snap}


@pytest.fixture(scope="session")
def seeded() -> tuple:
    repo = open_repository("sqlite://", clock=lambda: AT)
    info = seed_repository(repo)
    return repo, info


@pytest.fixture(scope="session")
def seeded_repo(seeded):
    return seeded[0]


@pytest.fixture(scope="session")
def seed_info(seeded):
    return seeded[1]


@pytest.fixture(scope="session")
def descriptor_dir(seeded_repo, tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("descriptor")
    with seeded_repo.engine.connect() as conn:
        inputs = descriptor_inputs(conn, list(IndexCode))
    docs = build_descriptors(inputs, "ALL")
    write_descriptors(docs, out, "ALL")
    return out


@pytest.fixture
def settings() -> AnalysisSettings:
    s = AnalysisSettings()
    return replace_settings(s, market=replace_settings(s.market, valuation_max_staleness_days=10))


@pytest.fixture
def market_data(seeded_repo, settings) -> MarketData:
    return MarketData(seeded_repo, settings)


@pytest.fixture
def stub_llm() -> StubLlm:
    return StubLlm()


__all__ = ["MarketSettings"]


@pytest.fixture(scope="session")
def e2e_results(seeded_repo, descriptor_dir, tmp_path_factory):
    """13_results 묶음 하나 (리포트 단계 시험용). e2e 픽스처와 같은 설정으로 14 직전까지 돈다."""
    from backend.analysis.common.llm import StubLlm
    from backend.analysis.executor.context import RunContext
    from backend.analysis.executor.runner import run
    from backend.analysis.executor.stages import STAGES
    from backend.tests.analysis.test_pipeline_e2e import INTENT_STUB, REQUEST

    s = AnalysisSettings()
    s = replace_settings(s, portfolio=replace_settings(s.portfolio, lookback_days=252, min_history_days_for_model=120),
                         market=replace_settings(s.market, valuation_max_staleness_days=10, descriptor_dir=str(descriptor_dir)))  # fmt: skip
    md = MarketData(seeded_repo, s)
    run_dir = tmp_path_factory.mktemp("run_results")
    ctx = RunContext(run_id="run_results_fixture", request=dict(REQUEST), repo=seeded_repo, md=md, llm=StubLlm({"02_intent": INTENT_STUB}, run_dir=run_dir), settings=s, run_dir=run_dir)
    out = run(ctx, stages=[st for st in STAGES if st.name != "14_report"], dump=False)
    assert out.status in ("success", "partial"), out.to_dict()
    return ctx.outputs["13_results"], s
