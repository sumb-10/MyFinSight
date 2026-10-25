"""리포트 문서 (M5-05, 블록 모델). 일곱 섹션은 settings.report.sections 가 정한다."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

BLOCK_TYPES = {
    "paragraphs",
    "kpis",
    "table",
    "donut",
    "line",
    "area",
    "bar",
    "funnel",
    "callout",
    "cards",
    "checkpoints",
    "glossary",
    "evidence",
    # 문서 v2 (라운드 4)
    "evidence_ref",  # 근거 색인 참조 (ids 또는 count 만; 본문에 색인을 복사하지 않음)
    "weights_compare",  # 규칙별 비중 표
    "timeline",  # 리밸런싱 타임라인 (체크포인트 + walk-forward 뉴스·뷰)
    "companies",  # 선정 종목 + 기업별 근거
}


class EvidenceRecord(BaseModel):
    """출처 패널 한 건. id 는 본문 인용 `[ev123]` `[fin:US-AAPL:pe_ttm:2026-10-01]` `[calc:cagr:bl_01]` 과 같다."""
    event_type: str | None = None  # 공시
    event_label_ko: str | None = None
    form: str | None = None
    items: str | None = None
    filed_at: str | None = None
    available_on: str | None = None

    id: str
    kind: str  # news | financial | calc | data_quality
    title: str
    source: str  # DB 테이블 또는 출처 이름 (publisher)
    url: str | None = None
    published_at: str | None = None
    data_as_of: str | None = None
    tickers: list[str] = []
    value: Any | None = None
    unit: str | None = None
    excerpt: str | None = None
    language: str | None = None


class Section(BaseModel):
    id: str
    title_ko: str
    blocks: list[dict] = Field(min_length=1)

    @field_validator("blocks")
    @classmethod
    def _types(cls, v: list[dict]) -> list[dict]:
        for b in v:
            if b.get("type") not in BLOCK_TYPES:
                raise ValueError(f"unknown block type {b.get('type')!r}")
        return v


class ReportDoc(BaseModel):
    request_id: str
    run_id: str
    stage: str = "14_report"
    generated_at: str
    source: str
    header: dict
    kpis: list[dict]
    nav: list[dict]
    sections: list[Section] = Field(min_length=1)
    datasets: dict
    assessment: dict
    evidence: list[EvidenceRecord] = []
    execution: list[dict] = []  # run_step 요약 (실행 기록 패널)
    tracking: dict = Field(default_factory=lambda: {"eligible": False, "reason_ko": None})
    sources: list[dict]
    parameters: dict
    warnings: list[str] = []  # 문장 검증 메모 (숫자 대조) — 실행 기록 패널용
    notices: list[dict] = []  # 분석 중 확인한 점 (행동 필요 경고, 한국어)
    doc_version: int = 1  # 2: 요약 대시보드(summary)·접이식 묶음(group_ko)·근거 참조(evidence_ref)·인용된 근거만 evidence 에 (라운드 4)
    summary: dict | None = None  # '한눈에 보기' (report_blocks.build_summary)
    evidence_summary: dict = Field(default_factory=dict)  # {total, cited, by_kind}

    @model_validator(mode="after")
    def _refs(self) -> ReportDoc:
        n = len(self.datasets["dates"])
        for sid, s in self.datasets["series"].items():
            for k in ("index", "value_usd", "drawdown"):
                if k in s and len(s[k]) != n:
                    raise ValueError(f"datasets.series.{sid}.{k} length {len(s[k])} != {n}")
        kpi_ids = {k["id"] for k in self.kpis}
        for sec in self.sections:
            for b in sec.blocks:
                if b["type"] == "kpis" and not set(b["ids"]) <= kpi_ids:
                    raise ValueError(f"section {sec.id}: unknown kpi ids {set(b['ids']) - kpi_ids}")
                if b["type"] in ("line", "area") and not set(b["series_ids"]) <= set(self.datasets["series"]):
                    raise ValueError(f"section {sec.id}: unknown series ids")
        if {s.id for s in self.sections} != {n_["id"] for n_ in self.nav}:
            raise ValueError("nav ids must match section ids")
        return self
