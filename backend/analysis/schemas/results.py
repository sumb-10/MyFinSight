"""검증(M5-03)과 결과 통합(M5-04)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator


class Check(BaseModel):
    rule: str
    name_ko: str
    level: Literal["hard", "soft", "info", "flag"]  # flag = 표시 규칙(최대낙폭): 추천 여부를 가르지 않고 순위에 반영
    status: Literal["pass", "warn", "fail", "info", "flag"]
    ok: bool | None = None  # 정보(info) 항목도 기준을 넘었는지 남긴다 (대시보드의 '참고' 목록용)
    value: float | None = None
    threshold: float | None = None
    message_ko: str


class ValidationResult(BaseModel):
    id: str
    kind: str
    status: Literal["pass", "warn", "fail"]
    checks: list[Check]  # 사용자 기준 (R1 최대낙폭, R2 목표수익, R3 비교지수, R7 변동성) + 정보 (드리프트·투자 비율·낙폭 비교)
    n_fail: int
    n_warn: int
    n_flag: int = 0  # 허용 낙폭 초과 표시 수
    integrity: list[Check] = []  # 코드 자체 점검 (상한 준수·자료 무결성). 사용자 표에는 안 보이고 실행 기록에 한 줄로 남는다


class Validation(BaseModel):
    request_id: str
    stage: str = "12_validation"
    criteria: dict
    results: list[ValidationResult]
    comparison_table: list[dict]
    recommended: dict | None = None
    alternatives: list[dict] = []  # 호환용 (라운드 5 부터 비어 있음: 낙폭 맞춤안은 backtest.portfolios 의 정식 후보)
    chosen_id: str | None = None  # 리포트가 "선택안"으로 쓰는 id (= 추천 id, 항상 있음)
    summary: dict
    warnings: list[str] = []


class ResultsBundle(BaseModel):
    """13_results: 이후 단계·DB 저장·재분석의 유일한 입력."""

    request_id: str
    run_id: str
    stage: str = "13_results"
    generated_at: str
    pipeline_version: str
    request: dict
    intent: dict
    selection: dict
    portfolio: dict
    backtest: dict
    validation: dict
    money_krw: dict
    evidence_index: dict  # 인용 ID -> 근거 (뉴스 ev*, 재무 fin:*, 계산값 calc:*)
    data_quality: dict | None = None
    llm_usage: dict
    sources: list[dict]
    parameters: dict
    warnings: list[dict] = []
    warnings_summary: list[str] = []  # user+info 를 묶어 렌더한 한국어 (호환용)
    notices: list[dict] = []  # 사용자에게 보이는 경고 (level=user) 구조화
    notices_ko: list[str] = []  # 위를 렌더한 문장

    @model_validator(mode="after")
    def _consistency(self) -> ResultsBundle:
        n = len(self.backtest["series_dates"])
        for p in [self.backtest["benchmark"], *self.backtest["portfolios"]]:
            for k, v in p["series"].items():
                if len(v) != n:
                    raise ValueError(f"backtest.{p['id']}.series.{k} length {len(v)} != {n}")
        ids = {p["id"] for p in self.backtest["portfolios"]}
        targets = self.portfolio["targets"]
        static_ids = {t["id"] for t in targets["portfolios"] + targets["templates"]}
        wf_ids = {p["id"] for p in (self.portfolio.get("walkforward") or {}).get("portfolios", [])}
        matched = [p for p in self.backtest["portfolios"] if p.get("kind") == "matched"]
        matched_ids = {p["id"] for p in matched}
        if ids - matched_ids != static_ids | wf_ids:
            raise ValueError(f"backtest portfolios {sorted(ids - matched_ids)} != targets {sorted(static_ids | wf_ids)}")
        for p in matched:  # 낙폭 맞춤안은 기준 포트폴리오가 같은 결과 안에 있어야 한다
            if p.get("base_id") not in ids or p["id"] != f"dd_match_{p.get('base_id')}":
                raise ValueError(f"matched portfolio {p['id']} must reference a base in the same results (base_id={p.get('base_id')})")
        need = (
            ids
            | {self.backtest["benchmark"]["id"]}
            | {b["id"] for b in self.backtest.get("benchmarks", [])}
            | {a["id"] for a in self.validation.get("alternatives", [])}
        )
        if set(self.money_krw["by_portfolio"]) != need:
            raise ValueError(f"money_krw.by_portfolio must cover {sorted(need)}")
        return self
