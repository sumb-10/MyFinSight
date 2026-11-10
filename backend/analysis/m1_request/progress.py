"""M1-02 새 요청 첫 해석의 진행 단계. 해석 중 화면이 2초마다 요청을 다시 읽어 지금 단계와 실제 결과를 보여 준다.

단계: 조건 정리 → 아이디어 해석 → 후보 종목 찾기 → 후보 분류 → 고를 수 있는 종목 확인 → 질문 고르기.
첫 턴(run_first_turn) 만 기록한다. 답·말로 보태기 턴은 화면이 그 자리에서 기다리므로 기록하지 않는다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from backend.analysis.common.jsonio import now_iso
from backend.analysis.schemas.dialog import AnalysisRequestDoc, ProgressStatus, ProgressStep

log = logging.getLogger(__name__)

STEPS: tuple[tuple[str, str], ...] = (
    ("conditions", "조건 정리"),
    ("intent", "아이디어 해석"),
    ("retrieve", "후보 종목 찾기"),
    ("classify", "후보 분류"),
    ("screen", "고를 수 있는 종목 확인"),
    ("question", "질문 고르기"),
)

# precheck 가 받는 콜백 꼴: (단계 key, 상태, 결과 문구)
StepFn = Callable[[str, ProgressStatus, str | None], None]


class Progress:
    """단계 목록과 기록기. save 가 있으면 단계가 바뀔 때마다 부른다 (없으면 기록만 하고 아무 데도 쓰지 않음)."""

    def __init__(self, save: Callable[[list[ProgressStep]], None] | None = None) -> None:
        self.steps = [ProgressStep(key=k, label_ko=v) for k, v in STEPS]
        self._save = save

    def step(self, key: str, status: ProgressStatus, detail_ko: str | None = None) -> None:
        """key 단계를 status 로. 이 단계를 시작(running)하면 앞에서 아직 진행 중인 단계는 끝난(done) 것으로 본다."""
        for s in self.steps:
            if s.key == key:
                s.status = status
                if detail_ko is not None:
                    s.detail_ko = detail_ko
                break
            if status == "running" and s.status == "running":
                s.status = "done"
        if self._save is not None:
            self._save([s.model_copy() for s in self.steps])

    def close(self, keys: tuple[str, ...] | None = None, detail_ko: str | None = None) -> None:
        """keys(없으면 전부) 중 아직 대기·진행 중인 단계를 건너뜀으로 (조건 오류로 일찍 끝남·점검 실패)."""
        open_ = [s for s in self.steps if s.status in ("waiting", "running") and (keys is None or s.key in keys)]
        for s in open_:
            s.status = "skipped"
            if detail_ko is not None:
                s.detail_ko = detail_ko
        if open_ and self._save is not None:
            self._save([s.model_copy() for s in self.steps])


def for_request(requests: Any, doc: AnalysisRequestDoc) -> Progress:
    """첫 턴용 기록기: 단계가 바뀔 때마다 doc(고치는 중인 문서)과 저장된 요청 문서의 progress 만 고친다.

    저장된 문서는 다시 읽어 progress 만 바꿔 쓴다 — 고치다 만 doc 을 쓰면 실패 처리(저장된 해석 중 문서에 실패만 적음)가 깨진다.
    부르는 쪽(run_first_turn)이 요청 잠금을 쥐고 있다. 저장이 실패해도(Windows 에서 읽는 중 교체 실패 등) 해석은 계속한다.
    """

    def save(steps: list[ProgressStep]) -> None:
        at = now_iso()
        doc.progress, doc.progress_updated_at = steps, at
        try:
            stored = requests.load(doc.request_id)
            stored.progress, stored.progress_updated_at = steps, at
            requests.save(stored)
        except Exception:  # noqa: BLE001 — 진행 표시는 보조 정보
            log.warning("progress save failed for %s", doc.request_id, exc_info=True)

    return Progress(save)


def themes_ko(intent: dict[str, Any]) -> str:
    labels = [t.get("label_ko") or t.get("id") for t in intent.get("interpretation", {}).get("themes", [])]
    return "테마 " + ", ".join(str(x) for x in labels) if labels else "테마 없음"


def screen_ko(pre: dict[str, Any] | None) -> str | None:
    """점검 결과 → '기준일 2026-11-06 18개 · 시작일 2023-11-07 15개'."""
    parts = [f"{x}일 {d.get('date') or ''} {d.get('n_selected')}개".replace("  ", " ")
             for k, x in (("as_of", "기준"), ("start", "시작")) if isinstance(d := (pre or {}).get(k), dict) and d.get("n_selected") is not None]  # fmt: skip
    return " · ".join(parts) or None
