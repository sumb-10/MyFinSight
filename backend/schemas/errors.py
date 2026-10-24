"""M00-02 공통 오류 (명세서 그대로 옮긴 임시본)."""

from __future__ import annotations

from typing import Any


class MyFinSightError(Exception):
    """모든 MyFinSight 오류의 부모. code로 원인을 구분한다 (부록 C)."""

    code: str = "UNKNOWN"
    recoverable: bool = False

    def __init__(
        self, message: str, *, code: str | None = None, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details: dict[str, Any] = details or {}


class DataSourceError(MyFinSightError):
    """외부 조회 실패 (어댑터 자체 설정 오류 등)."""

    code = "DATA_SOURCE_UNAVAILABLE"


class DataQualityError(MyFinSightError):
    """필수 데이터 실패."""


class ConfigError(MyFinSightError):
    """설정 파일 오류 (M00-01)."""


class InputError(MyFinSightError):
    """Profile·Spec 파일 오류."""


class SpecValidationError(MyFinSightError):
    """Spec 검증 실패 (M04-01)."""


class WeightValidationError(MyFinSightError):
    """비중 검증 실패 (M04-02)."""


class StrategyError(MyFinSightError):
    """규칙 실행 불가 (예: 상한 불가능)."""


class BacktestError(MyFinSightError):
    """백테스트 실패 (M05)."""


class ConsistencyError(MyFinSightError):
    """일치성 검사 실패 (M04-03)."""


class RepositoryError(MyFinSightError):
    """저장소 읽기·쓰기 실패 (M02-04). code = REPO_WRITE_FAILED / REPO_READ_FAILED."""
