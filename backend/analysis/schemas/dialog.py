"""보충 질문 대화 (M1-02) 저장 객체와 API 응답.

흐름: 프로필 + 아이디어 → HARD 검증 → 파생값 → 의도 해석(LLM, questions 제안) → 코드가 질문 1개 선택
→ 사용자 답(선택지 또는 자유 입력) → 반복(최대 N회) → ready → 확인 → confirm → 큐.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

QuestionKind = Literal["missing", "conflict", "ambiguous", "preference", "feasibility"]  # feasibility = 실행 전 점검(후보 부족·창 축소) 질문 (라운드 5)
DialogStatus = Literal["asking", "ready", "blocked", "confirmed", "cancelled"]
RequestMode = Literal["new", "rerun", "revision"]


class QuestionOption(BaseModel):
    value: Any
    label_ko: str
    patch: dict[str, Any] | None = None  # 여러 필드를 한 번에 바꾸는 보기 (필드 경로 → 값; `_` 로 시작하면 숨은 override). 없으면 value 를 question.field 에 반영
    clarification: str | None = None  # 고르면 아이디어 보충으로 덧붙이는 문장 (다음 턴 LLM 이 해석)


class QuestionProposal(BaseModel):
    """LLM 이 제안한 질문 (의도 해석 출력의 questions[])."""

    field: str
    kind: QuestionKind
    question_ko: str
    options: list[QuestionOption] = []
    allow_free_text: bool = True
    priority: int = Field(ge=1, le=5, default=3)
    why_ko: str = ""


class Question(QuestionProposal):
    """실제로 사용자에게 보여 준 질문과 답."""

    seq: int = Field(ge=1)
    asked_at: str
    field_label_ko: str | None = None  # 화면에 보여 줄 필드 이름 (원시 경로 대신)
    answer: str | None = None  # 사용자가 보는 답 텍스트 (선택지 라벨 또는 자유 입력)
    applied: dict[str, Any] | None = None  # {"field": ..., "value": ...} 코드가 요청에 반영한 값
    free_text: str | None = None
    skipped: bool = False
    answered_at: str | None = None


class FieldError(BaseModel):
    field: str
    message_ko: str


class ConditionRow(BaseModel):
    """조건 확인 화면 한 줄 (서버가 라벨·표시값을 만들어 Front 가 사전을 갖지 않게 한다)."""

    field: str
    group_ko: str
    label_ko: str
    value_ko: str
    profile_value_ko: str | None = None
    changed: bool = False
    source: Literal["profile", "idea", "answer", "default", "derived"] = "profile"
    supported: bool = True
    note_ko: str | None = None


class DialogMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class RevisionChange(BaseModel):
    """수정 요청에서 LLM 이 제안하고 코드가 검증한 변경 하나."""

    field: str
    value: Any = None
    base_value: Any = None
    label_ko: str | None = None
    reason_ko: str | None = None
    supported: bool = True
    note_ko: str | None = None


class RevisionDraft(BaseModel):
    """자연어 수정 요청 → 변경 초안 (M1-05). 평가 조건(기간·자본·적립·비교지수·리밸런싱)은 원안과 같게 고정한다."""

    text: str
    summary_ko: str | None = None
    changes: list[RevisionChange] = []
    unsupported_ko: list[str] = []
    idea_update_ko: str | None = None
    frozen_fields: list[str] = []
    base_run_id: str | None = None


class AnalysisRequestDoc(BaseModel):
    """store/data/requests/<request_id>.json (analysis_request.schema v2)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 2
    request_id: str
    created_at: str
    mode: RequestMode = "new"
    base_report_id: str | None = None
    profile_version: int
    idea: str
    language: str = "ko"
    overrides: dict[str, Any] = {}  # 필드 경로 -> 값 (프로필과 다르게 적용한 조건)
    idea_clarifications: list[str] = []  # 자유 입력 답변 (아이디어에 덧붙여 LLM 에 전달)
    questions: list[Question] = []
    messages: list[DialogMessage] = []  # LLM 대화 이력 (system 제외, 캐시 키에 들어감)
    draft_request: dict[str, Any] | None = None
    derived: dict[str, Any] | None = None
    intent: dict[str, Any] | None = None
    hard_errors: list[FieldError] = []
    status: Literal["draft", "confirmed", "cancelled"] = "draft"
    dialog_state: DialogStatus = "asking"
    turn: int = 0
    max_questions: int = 5
    blocked_reason_ko: str | None = None
    effective_request: dict[str, Any] | None = None
    request_fingerprint: str | None = None
    confirmed_at: str | None = None
    run_id: str | None = None
    context_summary: str | None = None
    revision: RevisionDraft | None = None
    warnings: list[str] = []
    precheck: dict[str, Any] | None = None  # 실행 전 점검 결과 (후보 수·지표 보유 수, 기준일·백테스트 시작일; 서명으로 재사용)


class DialogSummary(BaseModel):
    interpretation_summary_ko: str | None = None
    themes: list[dict[str, Any]] = []
    derived: dict[str, Any] | None = None
    changed_fields: list[str] = []


class DialogState(BaseModel):
    """API 응답: 현재 대화 상태."""

    request_id: str
    mode: RequestMode
    base_report_id: str | None = None
    status: Literal["draft", "confirmed", "cancelled"]
    state: DialogStatus
    turn: int
    max_questions: int
    idea: str
    question: Question | None = None
    questions: list[Question] = []
    hard_errors: list[FieldError] = []
    confirmation: dict[str, Any] | None = None  # {"effective_request": ..., "rows": [ConditionRow]}
    unresolved: list[dict[str, Any]] = []
    summary: DialogSummary = DialogSummary()
    revision: RevisionDraft | None = None
    run_id: str | None = None
    warnings: list[str] = []
    conditions: list[dict[str, Any]] = []  # 지금 조건 표 (질문 중에도; ready 면 confirmation.rows 와 같다)
    overrides: dict[str, Any] = {}  # 이번 요청에서 직접 바꾼 조건 (필드 경로 → 값)
    blocked_reason_ko: str | None = None  # 질문 상한에 닿아 남은 항목을 기본값으로 둔 사유 (ready 로 진행 가능)
    precheck: dict[str, Any] | None = None
