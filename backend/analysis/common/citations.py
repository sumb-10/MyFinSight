"""인용 ID 한 곳 정의. 문단·카드·표의 `[…]` 인용을 찾는 정규식과 종류 판별.

- ev<news_id>        뉴스 (news)           기준: available_on(없으면 published_at)
- dc<disclosure_id>  공시 (disclosure)     기준: available_on (수정 공시 제외)
- fin:<asset>:<metric>:<date>  재무·가격 지표 사실 (financial)
- calc:<metric>:<portfolio>    백테스트 계산값 (calc)
"""

from __future__ import annotations

import re

CITE_RE = re.compile(r"\[(ev\d+|dc\d+|fin:[^\]\s]+|calc:[^\]\s]+)\]")
PREFIX_KIND = {"ev": "news", "dc": "disclosure", "fin": "financial", "calc": "calc"}


def kind_of(cid: str) -> str:
    for p, k in PREFIX_KIND.items():
        if cid.startswith(p):
            return k
    return "unknown"
