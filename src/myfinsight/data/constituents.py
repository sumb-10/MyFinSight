"""M02-05 지수 구성종목 수집기: 정기 변경일 기준 갱신 판단 → 수집 → 검사 → 저장.

    from myfinsight.data.constituents import ConstituentCollector
    from myfinsight.data.constituent_source import WikipediaConstituentSource
    collector = ConstituentCollector(WikipediaConstituentSource(), repo)
    results = collector.update(config.universe.indices, today=date.today())
    results[IndexCode.SP500].rows        # 최신 list[IndexConstituent]
    results[IndexCode.SP500].warnings    # 갱신 실패 시 Report 한계에 넣을 문장

규칙
1. 갱신 필요: 최신 스냅샷이 없거나, 스냅샷 날짜 < 직전 정기 변경일. force=True 면 항상 수집.
   - SP500·NDX: 3·6·9·12월 셋째 금요일 (명세, Nasdaq-100 도 같은 기준)
   - KOSPI200: 6·12월 둘째 목요일(선물·옵션 만기일) 다음 날 (추가, 한국거래소 정기 변경)
2. 결과 검사: 행 수(SP500 495~510, NDX 98~105, KOSPI200 198~202), 티커 중복 없음,
   sector·industry 비어 있지 않음, sector 는 GICS 11개 섹터 이름 중 하나.
3. 통과하면 snapshot_date = today 로 저장. 실패(수집 오류·검사 불통과)하면 기존 스냅샷을 쓰고
   경고를 남긴다. 기존 스냅샷도 없으면 DataSourceError(DATA_CONSTITUENTS_UNAVAILABLE).
4. 수집 시도는 성공·실패 모두 fetch_log 에 남긴다.

한계: 정기 변경 사이의 수시 변경은 반영하지 않는다.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from enum import Enum

from pydantic import BaseModel, ConfigDict

from myfinsight.data.constituent_source import ConstituentSource
from myfinsight.data.repository.base import MarketDataRepository
from myfinsight.schemas.errors import DataSourceError
from myfinsight.schemas.market import IndexCode, IndexConstituent

logger = logging.getLogger(__name__)

ROW_BOUNDS: Mapping[IndexCode, tuple[int, int]] = {
    IndexCode.SP500: (495, 510),
    IndexCode.NDX: (98, 105),
    IndexCode.KOSPI200: (198, 202),
}
"""지수별 허용 행 수 (보통주 다중 클래스 고려)."""

GICS_SECTORS = frozenset(
    {
        "Energy",
        "Materials",
        "Industrials",
        "Consumer Discretionary",
        "Consumer Staples",
        "Health Care",
        "Financials",
        "Information Technology",
        "Communication Services",
        "Utilities",
        "Real Estate",
    }
)


class RefreshStatus(str, Enum):
    REFRESHED = "REFRESHED"  # 새로 받아 저장함
    UP_TO_DATE = "UP_TO_DATE"  # 정기 변경 이후 스냅샷이 있어 받지 않음
    KEPT_OLD = "KEPT_OLD"  # 받으려 했으나 실패, 기존 스냅샷 사용


class IndexRefresh(BaseModel):
    """지수 하나의 처리 결과."""

    model_config = ConfigDict(extra="forbid")

    index_code: IndexCode
    status: RefreshStatus
    snapshot_date: date
    rows: list[IndexConstituent]
    warnings: list[str] = []


def third_friday(year: int, month: int) -> date:
    """그 달 셋째 금요일."""
    first = date(year, month, 1)
    offset = (4 - first.weekday()) % 7  # 금요일 = 4
    return first + timedelta(days=offset + 14)


def second_thursday(year: int, month: int) -> date:
    """그 달 둘째 목요일 (한국 선물·옵션 만기일)."""
    first = date(year, month, 1)
    offset = (3 - first.weekday()) % 7  # 목요일 = 3
    return first + timedelta(days=offset + 7)


def _kospi200_rebalance(today: date) -> date:
    """KOSPI200 정기 변경일: 6·12월 둘째 목요일 다음 날 (공휴일은 고려하지 않음)."""
    candidates = [
        second_thursday(y, m) + timedelta(days=1)
        for y in (today.year - 1, today.year)
        for m in (6, 12)
    ]
    return max(d for d in candidates if d <= today)


def last_rebalance_date(today: date, index: IndexCode | str = IndexCode.SP500) -> date:
    """today 이전(포함) 가장 최근 정기 변경일.

    SP500·NDX 는 3·6·9·12월 셋째 금요일, KOSPI200 은 6·12월 둘째 목요일 다음 날.
    """
    if IndexCode(index) == IndexCode.KOSPI200:
        return _kospi200_rebalance(today)
    y, m = today.year, today.month - today.month % 3  # 이번 달 이하 가장 가까운 분기 말 달
    if m == 0:
        y, m = y - 1, 12
    d = third_friday(y, m)
    if d <= today:
        return d
    if m == 3:
        return third_friday(y - 1, 12)
    return third_friday(y, m - 3)


def needs_refresh(
    latest_snapshot: date | None, today: date, index: IndexCode | str = IndexCode.SP500
) -> bool:
    """최신 스냅샷이 없거나 그 지수의 직전 정기 변경일보다 이르면 True."""
    return latest_snapshot is None or latest_snapshot < last_rebalance_date(today, index)


def validate_constituents(
    index: IndexCode,
    rows: list[IndexConstituent],
    *,
    row_bounds: Mapping[IndexCode, tuple[int, int]] = ROW_BOUNDS,
) -> list[str]:
    """결과 검사. 문제 목록을 돌려준다 (빈 목록이면 통과)."""
    code = IndexCode(index)
    problems: list[str] = []
    lo, hi = row_bounds[code]
    if not lo <= len(rows) <= hi:
        problems.append(f"행 수 {len(rows)} 가 허용 범위 {lo}~{hi} 밖")
    other = sorted({r.index_code.value for r in rows if r.index_code != code})
    if other:
        problems.append(f"다른 지수 행이 섞임: {other}")
    dups = sorted(t for t, n in Counter(r.ticker for r in rows).items() if n > 1)
    if dups:
        problems.append(f"티커 중복: {dups}")
    blank = sorted(r.ticker for r in rows if not r.sector.strip() or not r.industry.strip())
    if blank:
        problems.append(f"sector·industry 빈 칸 {len(blank)}개: {blank[:20]}")
    odd = sorted({r.sector for r in rows if r.sector.strip() and r.sector not in GICS_SECTORS})
    if odd:
        problems.append(f"GICS 섹터 이름이 아님: {odd}")
    return problems


class ConstituentCollector:
    """출처(ConstituentSource) 와 저장소(M02-04) 를 묶어 지수별 최신 구성종목을 돌려준다."""

    def __init__(
        self,
        source: ConstituentSource,
        repository: MarketDataRepository,
        *,
        row_bounds: Mapping[IndexCode, tuple[int, int]] = ROW_BOUNDS,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.source = source
        self.repository = repository
        self.row_bounds = row_bounds
        self._clock = clock

    @property
    def _source_name(self) -> str:
        return str(getattr(self.source, "source_name", type(self.source).__name__))

    def update_one(
        self, index: IndexCode | str, today: date, *, force: bool = False
    ) -> IndexRefresh:
        """지수 하나: 필요하면 수집·검사·저장하고 최신 구성종목을 돌려준다."""
        code = IndexCode(index)
        current = self.repository.latest_constituents(code)
        current_date = current[0].snapshot_date if current else None
        if not force and not needs_refresh(current_date, today, code):
            assert current_date is not None
            return IndexRefresh(
                index_code=code,
                status=RefreshStatus.UP_TO_DATE,
                snapshot_date=current_date,
                rows=current,
            )

        problems: list[str]
        fetched: list[IndexConstituent] = []
        try:
            fetched = self.source.fetch(code)
            problems = validate_constituents(code, fetched, row_bounds=self.row_bounds)
        except Exception as exc:  # noqa: BLE001 - 출처 오류는 기존 스냅샷으로 대체
            problems = [f"수집 실패: {type(exc).__name__}: {exc}"]
        status = "SUCCESS" if not problems else "FAILED"
        self.repository.log_fetch(
            self._source_name,
            f"constituents:{code.value}",
            None,
            None,
            status,
            self._clock(),
            "; ".join(problems) or None,
        )

        if not problems:
            rows = [r.model_copy(update={"snapshot_date": today}) for r in fetched]
            rows.sort(key=lambda r: r.ticker)
            self.repository.save_constituents(rows)
            logger.info("%s 구성종목 %d개 저장 (%s)", code.value, len(rows), today)
            return IndexRefresh(
                index_code=code, status=RefreshStatus.REFRESHED, snapshot_date=today, rows=rows
            )

        reason = "; ".join(problems)
        if not current:
            raise DataSourceError(
                f"{code.value} 구성종목을 받지 못했고 저장된 스냅샷도 없음: {reason}",
                code="DATA_CONSTITUENTS_UNAVAILABLE",
                details={"index": code.value, "problems": problems},
            )
        assert current_date is not None
        warning = (
            f"{code.value} 구성종목 갱신 실패, {current_date} 스냅샷 사용 "
            f"(직전 정기 변경일 {last_rebalance_date(today, code)}): {reason}"
        )
        logger.warning(warning)
        return IndexRefresh(
            index_code=code,
            status=RefreshStatus.KEPT_OLD,
            snapshot_date=current_date,
            rows=current,
            warnings=[warning],
        )

    def update(
        self, indices: Iterable[IndexCode | str], today: date, *, force: bool = False
    ) -> dict[IndexCode, IndexRefresh]:
        """AppConfig.universe.indices 의 지수마다 update_one."""
        return {IndexCode(i): self.update_one(i, today, force=force) for i in indices}
