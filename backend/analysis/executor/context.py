"""실행 하나의 공유 상태. 단계 함수는 RunContext 만 받고, 산출물은 ctx.outputs 에 넣는다 (파일 덤프는 러너가)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.analysis.common.llm import LlmClient
from backend.analysis.common.warnings import CATALOG, Warning, from_text, make
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.schemas.backtest import BacktestRequest
from backend.analysis.settings import AnalysisSettings
from backend.pipeline.descriptor import Descriptor


@dataclass
class RunContext:
    run_id: str
    request: dict[str, Any]  # NormalizedRequest (derived 포함) 또는 UserRequest (01 단계가 derive)
    repo: Any
    md: MarketData
    llm: LlmClient
    settings: AnalysisSettings
    run_dir: Path
    desc: Descriptor | None = None
    desc_info: dict[str, Any] = field(default_factory=dict)
    intent: dict[str, Any] | None = None  # 대화 단계에서 이미 확정된 의도 (있으면 02 단계가 재사용)
    bt_req: BacktestRequest | None = None
    allow_fewer_at_start: bool = False  # 대화에서 '기간 유지(시작 때 종목 적어도 됨)' 를 고른 경우 (overrides._allow_fewer_at_start)
    cancel_check: Callable[[], bool] = lambda: False
    outputs: dict[str, Any] = field(default_factory=dict)
    facts: list[dict[str, Any]] = field(default_factory=list)
    news_by_stage: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # 단계별 근거 창 (병렬 실행에서도 순서가 같도록 단계 이름으로 모음)
    warnings: list[Warning] = field(default_factory=list)  # 구조화 경고 (common/warnings.py)
    step_summaries: dict[str, str] = field(default_factory=dict)
    progress: Callable[[str, int, int], None] = lambda stage, i, n: None  # 긴 단계의 진행 표시 (러너가 꽂음)

    @property
    def request_id(self) -> str:
        return self.request["request_id"]

    def out(self, name: str) -> Any:
        if name not in self.outputs:
            raise KeyError(f"stage output {name!r} not available yet")
        return self.outputs[name]

    def warn(self, stage: str, message_or_code: str, *, dates: list[str] | None = None, **fmt: Any) -> Warning:
        """카탈로그 코드면 한국어 경고를 만들고, 모듈이 낸 문자열이면 코드로 바꾼다(모르는 것은 debug 로 보존)."""
        w = make(stage, message_or_code, dates=dates or [], **fmt) if message_or_code in CATALOG else from_text(stage, message_or_code, dates=dates)
        self.warnings.append(w)
        return w

    def warn_all(self, stage: str, messages: list[str], *, dates: list[str] | None = None) -> None:
        for m in messages or []:
            self.warn(stage, str(m), dates=dates)

    def warnings_of(self, stage: str) -> list[Warning]:
        return [w for w in self.warnings if w.stage == stage]

    def add_news_window(self, stage: str, window: dict[str, Any]) -> None:
        self.news_by_stage.setdefault(stage, []).append(window)

    @property
    def news_windows(self) -> list[dict[str, Any]]:
        """모든 근거 창을 정해진 단계 순서로 (결과 묶음의 근거 색인 순서가 실행 방식과 무관하게 같도록)."""
        order = {n: i for i, n in enumerate(NEWS_STAGE_ORDER)}
        return [w for st in sorted(self.news_by_stage, key=lambda n: (order.get(n, 99), n)) for w in self.news_by_stage[st]]


NEWS_STAGE_ORDER = ("06_explain", "10_targets", "10w_paths", "10f_current")
