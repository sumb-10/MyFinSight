"""API 가 공유하는 서비스 객체 (Repository, 로컬 저장소, 설정, MarketData, LLM, 대화 서비스, 큐)."""

from __future__ import annotations

import datetime as dt
import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from backend.analysis.common.llm import LlmClient, make_llm
from backend.analysis.common.store import JsonStore, ProfileStore, RequestStore
from backend.analysis.executor.queue import Queue
from backend.analysis.m1_request.dialog import DialogService
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.m2_data.price_cache import PriceBarCache
from backend.analysis.m2_data.sector_trends import SectorTrendsJob, compute_sector_trends
from backend.analysis.m2_data.stocks import load_stocks, lookup
from backend.analysis.m5_backtest_report.execution_orders import compute_execution, with_execution
from backend.analysis.m6_tracking.paper import PaperService
from backend.analysis.paths import output_root
from backend.analysis.settings import AnalysisSettings

log = logging.getLogger(__name__)


@dataclass
class Services:
    repo_factory: Callable[[], Any]
    store: JsonStore
    settings: AnalysisSettings
    llm_factory: Callable[[], LlmClient] | None = None
    _md: MarketData | None = field(default=None, repr=False)
    _prices: PriceBarCache = field(default_factory=PriceBarCache, repr=False)  # 범위·종목이 늘 때 받아 둔 가격을 다시 받지 않게 (예전에는 전체를 다시 받았다)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _results_cache: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)  # report_id → 13_results (불변; 최근 8개)
    _orders_cache: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)  # report_id → 예상 매수 주문 (기준일 값이라 불변; 최근 32개)
    _titles: dict[str, str | None] = field(default_factory=dict, repr=False)  # report_id → 리포트의 짧은 제목 (불변; 목록·모의투자 이름용)
    _stocks: tuple[dt.date, list[dict[str, Any]]] | None = field(default=None, repr=False)  # (읽은 날, 종목 찾기 목록) — 하루 한 번 다시 읽음
    _trends: SectorTrendsJob | None = field(default=None, repr=False)  # 홈 '요즘엔 뭐가 좋아요?' 섹터 성과 (새 거래일마다 한 번 계산)

    @property
    def repo(self) -> Any:
        return self.repo_factory()

    @property
    def profiles(self) -> ProfileStore:
        return ProfileStore(self.store)

    @property
    def requests(self) -> RequestStore:
        return RequestStore(self.store)

    @property
    def queue(self) -> Queue:
        return Queue(self.store)

    def llm(self) -> LlmClient:
        # 대화 단계 호출도 비용을 남긴다 (실행 폴더가 없어 예전에는 기록이 없었다 → 시나리오 QA 비용 상한 관리)
        return self.llm_factory() if self.llm_factory else make_llm(self.settings.llm, usage_log=output_root() / "llm_usage_dialog.jsonl")

    def market_data(self) -> MarketData:
        """프로세스 안에서 재사용. 새 거래일 자료가 들어오면 다시 만든다."""
        with self._lock:
            repo = self.repo
            if self._md is None:
                self._md = MarketData(self._prices.wrap(repo), self.settings)
            else:
                try:
                    latest = self._md.latest_trading_day()
                    if latest != self._md.ceiling:
                        self._md = MarketData(self._prices.wrap(repo), self.settings)
                except Exception:  # noqa: BLE001
                    self._md = MarketData(self._prices.wrap(repo), self.settings)
            return self._md

    def stocks(self) -> list[dict[str, Any]]:
        """종목 찾기·이름 목록 (지원 유니버스 구성종목). 구성종목은 가끔 바뀌므로 하루 한 번만 DB 에서 다시 읽는다."""
        today = dt.date.today()
        with self._lock:
            if self._stocks is None or self._stocks[0] != today:
                self._stocks = (today, load_stocks(self.repo, today))
            return self._stocks[1]

    def stock_label(self, ticker: str) -> str:
        """티커 → 「회사명 (티커)」 (조건 표). 종목 목록을 못 읽었거나 목록에 없는 티커면 티커 그대로 (이름은 보조 정보)."""
        try:
            hit = lookup(self.stocks(), [ticker])
        except Exception:  # noqa: BLE001
            log.warning("stock names unavailable", exc_info=True)
            return ticker
        return f"{hit[0]['name_ko']} ({ticker})" if hit else ticker

    def sector_trends(self) -> SectorTrendsJob:
        with self._lock:
            if self._trends is None:
                self._trends = SectorTrendsJob(self.store, lambda progress: compute_sector_trends(self.market_data(), self.settings, progress=progress))
            return self._trends

    def dialog(self) -> DialogService:
        return DialogService(self.store, self.repo, self.market_data(), self.llm(), self.settings, stock_label=self.stock_label)

    def paper(self) -> PaperService:
        return PaperService(self.store, self.repo, self.market_data(), self.llm(), self.settings)

    def with_orders(self, report_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        """저장 문서에 예상 매수 주문이 없으면(예전 리포트) 계산해 응답에만 붙인다. 계산하지 못하면 문서 그대로."""
        if (doc.get("proposed") or {}).get("execution"):
            return doc
        with self._lock:
            cached = self._orders_cache.get(report_id)
        if cached:
            return with_execution(doc, cached)
        try:
            execution = compute_execution(doc, self.market_data())
        except Exception:  # noqa: BLE001  # DB 연결 실패여도 리포트는 열려야 한다
            return doc
        if execution:
            with self._lock:
                if len(self._orders_cache) >= 32:
                    self._orders_cache.pop(next(iter(self._orders_cache)))
                self._orders_cache[report_id] = execution
        return with_execution(doc, execution)

    def results(self, report_id: str) -> dict[str, Any] | None:
        """저장된 13_results 묶음 (근거 색인·체크포인트·시계열 조회용). 리포트는 불변이라 최근 8개를 메모리에 둔다."""
        with self._lock:
            if report_id in self._results_cache:
                return self._results_cache[report_id]
        art = self.repo.get_run_artifact(report_id)
        if not art:
            return None
        res = art["results"]
        with self._lock:
            if len(self._results_cache) >= 8:
                self._results_cache.pop(next(iter(self._results_cache)))
            self._results_cache[report_id] = res
        return res

    def report_titles(self, report_ids: Iterable[str]) -> dict[str, str | None]:
        """리포트 ID → 문서 머리말의 짧은 제목(header.title_ko, LLM 이 요청을 줄여 만든 이름 · 옛 리포트는 코드가 만든 제목).
        리포트는 불변이라 한 번 읽은 제목은 기억한다 (목록·모의투자 이름을 만들 때마다 DB 가 문서를 다시 읽지 않게). 아직 없는 리포트는 기억하지 않는다."""
        ids = list(dict.fromkeys(i for i in report_ids if i))
        with self._lock:
            need = [i for i in ids if i not in self._titles]
        if need:
            got = self.repo.report_titles(need)
            with self._lock:
                self._titles.update(got)
        with self._lock:
            return {i: self._titles.get(i) for i in ids}
