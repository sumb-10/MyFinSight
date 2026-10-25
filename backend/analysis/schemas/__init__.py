"""단계 경계 스키마 (module_mockup/scripts/schemas.py 를 모듈별로 나눔).

각 단계는 출력을 해당 모델로 검증한 뒤 다음 단계에 넘긴다 (C-02·C-03).
"""

from backend.analysis.schemas.backtest import (
    BacktestRequest,
    BacktestResults,
    BacktestSpec,
    BacktestWindow,
    CapitalSpec,
    Checkpoint,
    CheckpointWeights,
    Confirmation,
    ForwardConfig,
    Period,
    PortfolioResult,
    SelectionRow,
    SelectionSpec,
    ViewsConfig,
    WalkforwardConfig,
)
from backend.analysis.schemas.dialog import (
    AnalysisRequestDoc,
    ConditionRow,
    DialogState,
    DialogStatus,
    FieldError,
    Question,
    QuestionKind,
    QuestionOption,
)
from backend.analysis.schemas.intent import (
    Conflict,
    ExcludeThemeRule,
    IntentSpec,
    Interpretation,
    NewsTilt,
    ReportSettings,
    RiskParams,
    Screen,
    Theme,
    ThemeFilter,
    ValidationCriteria,
)
from backend.analysis.schemas.portfolio import (
    BaselinePortfolios,
    ExAnte,
    MarketModel,
    Portfolio,
    TargetPortfolios,
    View,
    Views,
    ViewSet,
)
from backend.analysis.schemas.report import BLOCK_TYPES, EvidenceRecord, ReportDoc, Section
from backend.analysis.schemas.request import (
    TEMPLATE_METRICS,
    Capital,
    Constraints,
    Derived,
    Horizon,
    NaturalLanguage,
    NormalizedRequest,
    NumHoldings,
    Profile,
    Rebalance,
    RebalanceRule,
    RebalanceUnit,
    Risk,
    RiskTolerance,
    StrategyPreference,
    Template,
    Universe,
    UserRequest,
    Weighting,
)
from backend.analysis.schemas.results import Check, ResultsBundle, Validation, ValidationResult
from backend.analysis.schemas.run import BUCKETS, RunBucket, RunIndexEntry, RunStatus, RunStep
from backend.analysis.schemas.selection import (
    Candidate,
    Candidates,
    FilteredOut,
    Gics,
    GicsLevel,
    Rejected,
    Selected,
    Selection,
    Tagging,
    TagResult,
)

__all__ = [name for name in dir() if not name.startswith("_")]
