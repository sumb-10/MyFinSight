"""M02-04 MarketDataRepository 인터페이스 (C-10: 다른 모듈은 이것만 안다).

다른 모듈은 SQL·테이블 이름을 모른다. 구현은 sql.py 의 SqlRepository 하나로 PostgreSQL(기본)과
SQLite 를 모두 지원한다. 만들기는 `open_repository()` 를 쓴다.

명세 메서드 13개 + 캐시 판단 needs_fetch. 확장(종목 마스터·재무·뉴스)은 ExtendedRepository.
실행 기록(run_artifact·run_step·report)은 데이터 계약(module_prototype2 2.2절 (b)) 모양이다.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable

import pandas as pd

from backend.schemas.market import (
    FxRate,
    IndexCode,
    IndexConstituent,
    PriceBar,
    PriceMeta,
)
from backend.schemas.market_ext import DisclosureRecord, AssetInfo, DisclosureRow, FinancialRow, NewsRecord, NewsRow
from backend.schemas.runlog import StepRecord


@runtime_checkable
class MarketDataRepository(Protocol):
    """시장 데이터·실행 기록 저장소 (명세 M02-04 메서드 13개 + 캐시 판단 헬퍼)."""

    # ---- 가격 ----
    def upsert_prices(self, bars: list[PriceBar]) -> int:
        """가격 저장 (출처별 원본 + 계약 price_daily). 같은 키·같은 값이면 건너뜀. 반영 행 수."""
        ...

    def get_prices(
        self, tickers: list[str], start: date, end: date
    ) -> tuple[pd.DataFrame, PriceMeta]:
        """[start, end] 계약 price_daily 수정종가를 PriceFrame 계약(0-4) 모양으로. 없는 칸은 NaN."""
        ...

    def covered_range(self, ticker: str) -> tuple[date, date] | None:
        """저장된 첫 날짜·마지막 날짜. 없으면 None."""
        ...

    def needs_fetch(
        self, ticker: str, start: date, end: date, *, today: date | None = None
    ) -> bool:
        """저장 범위가 요청 범위를 덮고 마지막 저장일 ≥ 직전 거래일이면 False."""
        ...

    # ---- 환율 ----
    def upsert_fx(self, rates: list[FxRate]) -> int:
        """환율 저장 (키: 통화쌍·날짜). 반영 행 수."""
        ...

    def get_fx_on_or_before(self, d: date) -> FxRate | None:
        """d 이전(포함) 가장 최근 USD/KRW 환율."""
        ...

    # ---- 실행 산출물 (계약 run_artifact) ----
    def save_run_artifact(
        self,
        run_id: str,
        request_id: str,
        results: dict[str, Any],
        params: dict[str, Any],
        llm_usage: dict[str, Any] | None = None,
    ) -> None:
        """결과 통합 JSON·파라미터 스냅샷·LLM 사용량 저장. 같은 run_id 면 바꿈."""
        ...

    def get_run_artifact(self, run_id: str) -> dict[str, Any] | None:
        """저장된 실행 산출물 (results·params·llm_usage 는 dict). 없으면 None."""
        ...

    # ---- 구성종목 ----
    def save_constituents(self, rows: list[IndexConstituent]) -> None:
        """구성종목 스냅샷 저장. 같은 (지수, 스냅샷 날짜) 는 통째로 바꿈."""
        ...

    def latest_constituents(self, index: IndexCode) -> list[IndexConstituent]:
        """가장 최근 스냅샷 (티커 오름차순). 없으면 빈 목록."""
        ...

    # ---- 수집 이력 ----
    def log_fetch(
        self,
        source: str,
        target: str,
        start: date | None,
        end: date | None,
        status: str,
        fetched_at: datetime,
        error: str | None,
    ) -> None:
        """수집 이력 한 줄 추가 (덮어쓰지 않고 누적)."""
        ...

    # ---- 실행 단계·리포트 (계약 run_step·report, 분석 쪽 쓰기 계정) ----
    def save_step(self, rec: StepRecord) -> None:
        """단계 기록 저장. 같은 (run_id, step) 은 최신 상태로 바꿈."""
        ...

    def get_steps(self, run_id: str) -> list[StepRecord]:
        """실행의 단계 기록 (시작 시각 순)."""
        ...

    def save_report(
        self,
        report_id: str,
        doc: dict[str, Any],
        *,
        strategy_name: str | None,
        request_summary: str | None,
        as_of: date,
    ) -> None:
        """리포트 저장 (report_id = run_id, run_artifact 먼저). 이미 있으면 거부 (불변)."""
        ...

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        """저장된 리포트 (doc 은 dict). 없으면 None."""
        ...


@runtime_checkable
class ExtendedRepository(MarketDataRepository, Protocol):
    """명세 밖 확장 (추가 테이블: 종목 마스터·재무·뉴스). 역할 A 수집기가 쓴다."""

    def upsert_assets(self, assets: list[AssetInfo]) -> int:
        """종목 마스터 저장. 반영 행 수."""
        ...

    def get_assets(self, symbols: list[str] | None = None) -> list[AssetInfo]:
        """종목 마스터 조회 (symbols = yfinance 표기)."""
        ...

    def asset_key_map(self, column: str) -> dict[str, str]:
        """출처 코드(dart_corp_code·sec_cik 등) → asset_id."""
        ...

    def upsert_financials(self, rows: list[FinancialRow]) -> int:
        """재무 지표 저장. 반영 행 수."""
        ...

    def get_financials_as_of(
        self, asset_id: str, as_of: date, metrics: list[str] | None = None
    ) -> list[FinancialRow]:
        """as_of 까지 공시된 지표의 최신 값."""
        ...

    def annual_report_dates(self, asset_ids: Sequence[str]) -> dict[str, dict[str, date]]:
        """asset_id → {결산년월: DART 사업보고서 최초 접수일}."""
        ...

    def upsert_disclosures(self, rows: list[DisclosureRow]) -> int:
        """공시 저장 (출처·공시 번호·종목 기준). 반영 행 수."""
        ...

    def upsert_news(self, rows: list[NewsRow]) -> int:
        """뉴스 저장. 반영 행 수."""
        ...

    def get_news(self, asset_id: str, start: datetime, end: datetime) -> list[NewsRow]:
        """기간 안 발행 기사."""
        ...

    def covered_ranges(
        self, tickers: Sequence[str], *, source: str | None = None
    ) -> dict[str, tuple[date, date]]:
        """여러 티커의 저장 범위 (쿼리 한 번, source 를 주면 그 출처만)."""
        ...

    def tickers_needing_fetch(
        self, tickers: Sequence[str], start: date, end: date, *, today: date | None = None
    ) -> list[str]:
        """needs_fetch 가 참인 티커들."""
        ...

    def log_fetches(self, source: str, rows: Sequence[dict[str, Any]]) -> None:
        """한 출처의 수집 이력 여러 줄을 한 번에 추가."""
        ...

    def fetch_attempts(
        self,
        source: str,
        targets: Sequence[str],
        *,
        start_on_or_before: date | None = None,
        end_on_or_after: date | None = None,
    ) -> dict[str, dict[str, Any]]:
        """출처·대상별 최근 성공 시각과 실패 횟수."""
        ...

    def prune_news(self, published_before: datetime) -> int:
        """보관 기간이 지난 기사 삭제."""
        ...

    # ---- 교차검증 (M02-06) ----
    def pending_verification(self, *, limit: int = 2000) -> list[tuple[str, date]]:
        """교차검증을 아직 안 받은 (티커, 날짜)."""
        ...

    def price_rows(self, keys: Sequence[tuple[str, date]]) -> list[dict[str, Any]]:
        """(티커, 날짜) 들의 출처별 가격 행."""
        ...

    def save_verification(
        self,
        consensus: list[dict[str, Any]],
        marks: list[dict[str, Any]],
        *,
        drop_consensus: Sequence[tuple[str, date]] = (),
    ) -> int:
        """CONSENSUS 행과 출처별 검증 표시 저장."""
        ...

    def mismatch_days(self, tickers: Sequence[str], start: date, end: date) -> dict[str, int]:
        """기간 안 MISMATCH 거래일 수 (품질 판정 경고용)."""
        ...

    def reset_verification(
        self, start: date, end: date, *, tickers: Sequence[str] | None = None
    ) -> int:
        """기간의 검증 표시를 지워 다시 계산하게 함."""
        ...

    def add_extra_tickers(self, tickers: Iterable[str], *, added_by: str = "API") -> int:
        """서비스 요청으로 처음 받은 종목을 정기 수집 대상에 올림. 추가 수."""
        ...

    def extra_tickers(self, *, since: datetime | None = None) -> list[str]:
        """요청으로 늘어난 종목 (추가 순서)."""
        ...

    # ------------------------------------------------------------ 분석 패키지 읽기 (backend/db/analysis_readers.py)
    def get_price_bars(self, tickers: Sequence[str], start: date, end: date) -> pd.DataFrame:
        """[start, end] 가격 행 long 형식 (ticker, date, open, high, low, close, adj_close, volume, currency, source)."""
        ...

    def get_fx_range(self, start: date, end: date, pair: str = "USDKRW") -> list[FxRate]:
        """[start, end] 환율 (날짜 순)."""
        ...

    def get_valuation_asof(
        self, asset_ids: Sequence[str], d: date, *, max_staleness_days: int = 10
    ) -> dict[str, dict[str, Any]]:
        """종목별 d 이하 최신 valuation_daily 행 (per, pbr, roe_ttm, dividend_yield, market_cap, shares_outstanding …)."""
        ...

    def constituents_at(
        self, index: IndexCode | str, d: date
    ) -> tuple[date | None, list[IndexConstituent], list[str]]:
        """d 이하 최신 스냅샷 (없으면 최초 스냅샷 + 경고)."""
        ...

    def get_news_batch(
        self,
        asset_ids: Sequence[str],
        start: datetime,
        end: datetime,
        *,
        languages: Sequence[str] | None = None,
        per_asset: int | None = None,
    ) -> list[NewsRecord]:
        """여러 종목 기사, [start, end) 반개구간, 종목별 최신순 per_asset 개."""
        ...

    def get_disclosures_batch(
        self,
        asset_ids: Sequence[str],
        start: date,
        end: date,
        *,
        event_types: Sequence[str] | None = None,
        per_asset: int | None = None,
        include_amendments: bool = False,
    ) -> list[DisclosureRecord]:
        """여러 종목 공시, 이용 가능일 [start, end) 반개구간, 수정 공시 제외, 종목별 중요도·최신순 per_asset 개."""
        ...

    def asset_map(self, symbols: Sequence[str] | None = None) -> dict[str, dict[str, Any]]:
        """yfinance 표기 → 종목 마스터 요약."""
        ...
