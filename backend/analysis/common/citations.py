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


_ID = r"(?:ev\d+|dc\d+|fin:[^\]\s,]+|calc:[^\]\s,]+)"
_GROUP_RE = re.compile(r"\[(" + _ID + r"(?:\s*[,，、]\s*" + _ID + r")+)\]")


def split_grouped(text: str) -> str:
    """'[ev1, ev2]' 처럼 한 괄호에 묶은 인용을 '[ev1][ev2]' 로 — 인용은 괄호 하나에 id 하나 (2026-11 평가 074: 묶어 적어
    '시장 분석에 인용이 없다' 로 리포트 검사에 걸려 실행이 실패했다)."""
    return _GROUP_RE.sub(lambda m: "".join(f"[{x.strip()}]" for x in re.split(r"[,，、]", m.group(1))), text)


def split_grouped_in(obj):
    """LLM 응답(dict·list) 안의 모든 문자열에 split_grouped 를 제자리로 적용하고 obj 를 돌려준다 (검사기 안에서 써도 응답에 남는다)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            obj[k] = split_grouped(v) if isinstance(v, str) else split_grouped_in(v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            obj[i] = split_grouped(v) if isinstance(v, str) else split_grouped_in(v)
    return obj
