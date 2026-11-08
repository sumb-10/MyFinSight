"""2026-11 속도 개선: 가격 원자료 캐시, 리포트의 단계별 모델 표기."""

from __future__ import annotations

import datetime as dt

import pandas as pd

from backend.analysis.m2_data.price_cache import PriceBarCache
from backend.db.analysis_readers import PRICE_BAR_COLS


class _Repo:
    """get_price_bars 만 있는 가짜 저장소 (읽기 함수와 같은 모양: 범위 필터, (종목, 날짜) 순, float 열)."""

    def __init__(self) -> None:
        days = pd.bdate_range("2019-01-01", "2026-10-30")
        rows = [(t, d, 100.0 + i, 99.0 + i, 1e6, "USD") for t in ("AAA", "BBB", "CCC") for i, d in enumerate(days) if not (t == "CCC" and d < pd.Timestamp("2023-01-01"))]
        self.df = pd.DataFrame(rows, columns=list(PRICE_BAR_COLS))
        self.calls: list[tuple[tuple[str, ...], dt.date, dt.date]] = []

    def get_price_bars(self, tickers, start, end):
        self.calls.append((tuple(sorted(tickers)), start, end))
        m = self.df["ticker"].isin(list(tickers)) & (self.df["date"] >= pd.Timestamp(start)) & (self.df["date"] <= pd.Timestamp(end))
        out = self.df.loc[m]
        if not len(out):
            return pd.DataFrame([], columns=list(PRICE_BAR_COLS))
        return out.sort_values(["ticker", "date"]).reset_index(drop=True)

    def other(self) -> str:
        return "delegated"


def test_price_cache_same_rows_and_fetches_only_missing_segments():
    repo, cache = _Repo(), PriceBarCache(recent_days=14)
    today = dt.date(2026, 11, 8)
    get = lambda tk, a, b: cache.get_price_bars(repo, tk, dt.date.fromisoformat(a), dt.date.fromisoformat(b), today=today)  # noqa: E731
    direct = lambda tk, a, b: _Repo().get_price_bars(tk, dt.date.fromisoformat(a), dt.date.fromisoformat(b))  # noqa: E731
    pd.testing.assert_frame_equal(get(["AAA", "BBB"], "2021-01-04", "2023-06-30"), direct(["AAA", "BBB"], "2021-01-04", "2023-06-30"))
    assert len(repo.calls) == 1
    # 안쪽 범위 → DB 를 부르지 않음
    pd.testing.assert_frame_equal(get(["BBB", "AAA"], "2022-01-03", "2022-12-30"), direct(["AAA", "BBB"], "2022-01-03", "2022-12-30"))
    assert len(repo.calls) == 1
    # 앞·뒤로 넓히고 새 종목(상장 전 구간 포함)·없는 종목 → 모자란 구간만
    pd.testing.assert_frame_equal(get(["AAA", "BBB", "CCC", "ZZZ"], "2020-06-01", "2024-03-29"), direct(["AAA", "BBB", "CCC", "ZZZ"], "2020-06-01", "2024-03-29"))
    assert sorted(repo.calls[1:]) == [(("AAA", "BBB"), dt.date(2020, 6, 1), dt.date(2021, 1, 3)), (("AAA", "BBB"), dt.date(2023, 7, 1), dt.date(2024, 3, 29)),
                                      (("CCC", "ZZZ"), dt.date(2020, 6, 1), dt.date(2024, 3, 29))]  # fmt: skip
    n = len(repo.calls)
    assert get(["ZZZ"], "2021-01-04", "2021-12-31").empty and len(repo.calls) == n  # 행이 없던 종목도 다시 묻지 않음
    # 최근 14일(2026-10-25 이후)은 캐시하지 않고 늘 DB 에서
    pd.testing.assert_frame_equal(get(["AAA"], "2026-09-01", "2026-10-30"), direct(["AAA"], "2026-09-01", "2026-10-30"))
    pd.testing.assert_frame_equal(get(["AAA"], "2026-09-01", "2026-10-30"), direct(["AAA"], "2026-09-01", "2026-10-30"))
    tails = [c for c in repo.calls[n:] if c[1] == dt.date(2026, 10, 26)]
    assert len(tails) == 2 and all(c[2] == dt.date(2026, 10, 30) for c in tails)
    # 다른 저장소면 비운다 (시험마다 다른 자료)
    repo2 = _Repo()
    cache.get_price_bars(repo2, ["AAA"], dt.date(2022, 1, 3), dt.date(2022, 12, 30), today=today)
    assert len(repo2.calls) == 1
    # 감싼 저장소: 가격 조회만 캐시, 나머지는 그대로
    w = cache.wrap(repo2)
    assert w.other() == "delegated"
    w.get_price_bars(["AAA"], dt.date(2022, 3, 1), dt.date(2022, 6, 30))
    assert len(repo2.calls) == 1


def test_models_ko_lists_stage_models():
    from backend.analysis.m5_backtest_report.report_blocks import _models_ko

    base = {"model": "gpt-6-luna", "mode": "api"}
    assert _models_ko(base) == "gpt-6-luna (api 모드; 의도 해석·보충 질문·테마 분류·뉴스 뷰·서술)"  # 예전 결과 묶음(stage_models 없음)도 같은 문장
    assert _models_ko({**base, "stage_models": {"09_views_news": "gpt-4o-mini"}}) == "gpt-6-luna (api 모드; 의도 해석·보충 질문·테마 분류·서술) / 뉴스 뷰: gpt-4o-mini"
