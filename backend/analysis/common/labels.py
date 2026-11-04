"""사용자 문장에 쓰는 표시 이름 (2026-11 시나리오 QA: 한국어 질문·공지에 'Industrials 8개' 처럼 GICS 영어 이름이 그대로 나왔다)."""

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=256)
def sector_ko(name: str | None) -> str:
    """GICS 섹터 이름(영어·코드) → 이 프로젝트의 한국어 이름. 모르면 그대로 돌려준다."""
    if not name:
        return name or ""
    from backend.pipeline.gics import load_taxonomy  # 무거운 분류표는 처음 쓸 때만 읽는다

    tax = load_taxonomy()
    node = tax.get(str(name)) if str(name).isdigit() else tax.resolve(str(name), level=1)
    return node.name_ko if node and node.level == 1 else str(name)


def sector_counts_ko(counts: dict[str, int]) -> str:
    """{'Industrials': 8, 'Utilities': 1} → '산업재 8개, 유틸리티 1개' (많은 순)."""
    return ", ".join(f"{sector_ko(k)} {v}개" for k, v in sorted(counts.items(), key=lambda x: -x[1]))


THEME_KO = {"tobacco": "담배", "gambling": "도박", "fossil_fuels": "화석연료", "weapons": "무기", "defense": "방산", "alcohol": "주류", "adult_entertainment": "성인 산업",
            "nuclear": "원자력", "cannabis": "대마", "coal": "석탄", "oil_gas": "석유·가스", "animal_testing": "동물 실험", "fur": "모피", "crypto": "가상자산"}  # fmt: skip
VOL_PREF_KO = {"low": "낮음", "medium": "중간", "high": "높음"}


def theme_ko(theme: str | None) -> str:
    """제외 테마 id(LLM·사용자가 정한 영어 이름) → 한국어. 모르면 밑줄만 띄어 쓴다."""
    t = str(theme or "")
    return THEME_KO.get(t.lower(), t.replace("_", " "))


def field_ko(path: str | None) -> str:
    """요청 필드 경로('horizon.backtest_years') → 화면 이름('백테스트 기간(년)')."""
    from backend.analysis.m1_request.validate import LABELS  # 순환 import 방지: 쓸 때만

    p = str(path or "")
    return LABELS.get(p) or {"capital.trading_currency": "거래 통화"}.get(p) or p


def enum_ko(value: str | None) -> str:
    """요청 값의 영어 코드('moderate', 'hold', 'beginner') → 한국어 (조건 확인 화면과 같은 표)."""
    from backend.analysis.m1_request.conditions import KO

    v = str(value or "")
    return KO.get(v) or {"beginner": "초보", "intermediate": "중급", "advanced": "상급", "expert": "전문가"}.get(v) or v


def usd_ko(x: float | None) -> str:
    """달러 금액을 한국어 단위로: 10e9 → '100억 달러', 2e7 → '2,000만 달러' ('10.0B USD' 를 LLM 이 '10.0십억 달러' 로 옮겨 적었다, 005)."""
    v = float(x or 0)
    if v >= 1e8:
        n = v / 1e8
        return f"{n:,.0f}억 달러" if abs(n - round(n)) < 0.05 else f"{n:,.1f}억 달러"
    if v >= 1e4:
        return f"{v / 1e4:,.0f}만 달러"
    return f"{v:,.0f}달러"
