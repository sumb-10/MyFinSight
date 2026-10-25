"""API 가 공유하는 서비스 객체 (Repository, 로컬 저장소, 설정, MarketData, LLM, 대화 서비스, 큐)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.analysis.common.llm import LlmClient, make_llm
from backend.analysis.common.store import JsonStore, ProfileStore, RequestStore
from backend.analysis.executor.queue import Queue
from backend.analysis.m1_request.dialog import DialogService
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.m6_tracking.paper import PaperService
from backend.analysis.settings import AnalysisSettings


@dataclass
class Services:
    repo_factory: Callable[[], Any]
    store: JsonStore
    settings: AnalysisSettings
    llm_factory: Callable[[], LlmClient] | None = None
    _md: MarketData | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _results_cache: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)  # report_id → 13_results (불변; 최근 8개)

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
        return self.llm_factory() if self.llm_factory else make_llm(self.settings.llm)

    def market_data(self) -> MarketData:
        """프로세스 안에서 재사용. 새 거래일 자료가 들어오면 다시 만든다."""
        with self._lock:
            repo = self.repo
            if self._md is None:
                self._md = MarketData(repo, self.settings)
            else:
                try:
                    latest = self._md.latest_trading_day()
                    if latest != self._md.ceiling:
                        self._md = MarketData(repo, self.settings)
                except Exception:  # noqa: BLE001
                    self._md = MarketData(repo, self.settings)
            return self._md

    def dialog(self) -> DialogService:
        return DialogService(self.store, self.repo, self.market_data(), self.llm(), self.settings)

    def paper(self) -> PaperService:
        return PaperService(self.store, self.repo, self.market_data(), self.llm(), self.settings)

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
