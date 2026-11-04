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
