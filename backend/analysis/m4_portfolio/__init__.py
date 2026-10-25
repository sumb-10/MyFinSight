"""Module4 포트폴리오 구성: 시장모형 → 기준 비중 4종 → 뉴스 근거 뷰(LLM) → Black-Litterman. 공통 함수 construct() 가 네 호출 위치를 묶는다."""

from backend.analysis.m4_portfolio.construct import ConstructResult, construct

__all__ = ["ConstructResult", "construct"]
