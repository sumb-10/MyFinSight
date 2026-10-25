"""리포트 문서 검증 게이트 (M5-05, 요구 5·8). 하나라도 실패하면 공개 리포트를 만들지 않는다.

오류(실패): 일곱 섹션 존재·순서, 본문 인용 ID 실존(evidence_index), 뉴스 인용은 보유 종목·구성일 이전, 시장 분석 문단의 뉴스 인용(근거가 있을 때), 금지 표현.
경고: 문단 속 숫자가 결과값에 없음 (settings.report.strict_numbers 이면 오류), 개발 용어.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.analysis.settings import AnalysisSettings

from backend.analysis.common.citations import CITE_RE  # 인용 ID 정규식은 한 곳에서
NUM_RE = re.compile(r"(?:\$\s?)?(-?[\d,]+(?:\.\d+)?)\s*(%p|%|USD|원|달러|일|개|회|종목|배)?")
DEV_WORDS = ["샘플", "stub", "mock", "JSON", "파이프라인 내부"]


@dataclass
class CheckResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors_by_src: dict[str, list[str]] = field(default_factory=dict)  # 오류를 낸 LLM 호출(14a/14b/14c) 또는 "code"/"doc" 별 (재시도 라우팅용)

    @property
    def ok(self) -> bool:
        return not self.errors

    def err(self, src: str, msg: str) -> None:
        self.errors.append(msg)
        self.errors_by_src.setdefault(src, []).append(msg)

    def sources_to_retry(self) -> set[str]:
        """다시 불러야 할 LLM 호출. 문서 구조 오류("doc")는 서술 호출 둘(14b·14c)로, 코드 생성 블록 오류("code")는 재시도로 못 고친다."""
        srcs = {k for k in self.errors_by_src if k in ("14a", "14b", "14c")}
        if "doc" in self.errors_by_src:
            srcs |= {"14b", "14c"}
        return srcs


NEGATION_MARKERS = ("않", "아니", "아닙", "없", "못", "안 ", "아닌", "말고")  # "아닙니다" 는 음절이 달라 "아니" 로 잡히지 않는다 (라운드 5: 부정형이 금지어로 걸려 실행이 실패한 사례)
ALLOWED_TERMS = ("무위험수익률", "무위험 수익률", "무위험 이자율", "무위험 금리")  # 샤프 비율의 전문 용어: 단정 표현이 아니다


# "보장" 은 명사로도 쓰인다 ("보험 보장 우려", "보장 범위"). 단정 표현으로 보는 것은 동사꼴 ("보장합니다", "보장된다") 뿐이다.
VERB_FORMS = {"보장": ("합니다", "한다", "됩니다", "된다", "하는", "할", "해", "하며", "해서", "돼", "되어", "받", "하고", "하지", "되지", "하겠", "합니")}


def _find_all(text: str, w: str) -> list[int]:
    out, i = [], text.find(w)
    forms = VERB_FORMS.get(w)
    while i >= 0:
        tail = text[i + len(w): i + len(w) + 3]
        if forms is None or any(tail.startswith(f) for f in forms):
            out.append(i)
        i = text.find(w, i + 1)
    return out


def _negated(text: str, i: int, w: str) -> bool:
    """금지 표현이 부정형으로 쓰였는지 ("보장하지 않습니다", "보장되는 것은 아닙니다"). 뒤 18글자 안에 부정 표지가 있으면 허용."""
    tail = text[i + len(w): i + len(w) + 18]
    return any(m in tail for m in NEGATION_MARKERS)


def known_numbers(obj: Any, acc: set[float]) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            known_numbers(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            known_numbers(v, acc)
    elif isinstance(obj, bool):
        return
    elif isinstance(obj, int | float):
        v = abs(float(obj))
        if v <= 20:
            acc.add(round(v * 100, 1))
            acc.add(round(v * 100))
            acc.add(round(v * 100, 2))
        acc.add(round(v, 2))
        acc.add(round(v, 1))
        acc.add(round(v))


def paragraphs_src(doc: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(섹션 id, 문장, 출처) — paragraphs 블록과 cards 의 text_ko. 출처는 블록의 `src`(14a/14b/14c/code), 없으면 "code"."""
    out = []
    for sec in doc["sections"]:
        for b in sec["blocks"]:
            src = b.get("src") or "code"
            if b["type"] == "paragraphs":
                out += [(sec["id"], t, src) for t in b["items"]]
            elif b["type"] == "cards":
                out += [(sec["id"], it.get("text_ko", ""), src) for it in b["items"]]
            elif b["type"] == "companies":  # 06 단계 LLM 문단 (재시도 대상 아님: src "06")
                out += [(sec["id"], t, "06") for it in b["items"] for t in it.get("rationale_ko", [])]
    return out


def paragraphs_of(doc: dict[str, Any]) -> list[tuple[str, str]]:
    """(섹션 id, 문장) — paragraphs 블록과 cards 의 text_ko."""
    return [(sid, t) for sid, t, _ in paragraphs_src(doc)]


def check(doc: dict[str, Any], R: dict[str, Any], settings: AnalysisSettings) -> CheckResult:
    res = CheckResult()
    want = list(settings.report.sections)
    got = [s["id"] for s in doc["sections"]]
    if got != want:
        res.err("doc", f"sections must be exactly {want} in order, got {got}")
    for s in doc["sections"]:
        if not s["blocks"]:
            res.err("doc", f"section {s['id']} has no blocks")
    idx = R["evidence_index"]
    held = set()
    for p in R["backtest"]["portfolios"]:
        held |= set(p["target_weights"])
    held |= {s["ticker"] for s in R["selection"]["table"]}
    paras3 = paragraphs_src(doc)
    paras = [(sid, t) for sid, t, _ in paras3]
    for sid, text, src in paras3:
        for cid in CITE_RE.findall(text):
            e = idx.get(cid)
            if e is None:
                res.err(src, f"{sid}: unknown citation [{cid}]")
                continue
            if cid.startswith(("ev", "dc")):
                what = "news" if cid.startswith("ev") else "disclosure"
                tk = set(e.get("tickers", []))
                if tk and not tk & held:
                    res.err(src, f"{sid}: {what} [{cid}] is about {sorted(tk)} which are not held tickers")
                pub = (e.get("available_on") or e.get("published_at") or "") if what == "disclosure" else (e.get("published_at") or "")
                if pub and pub > str(R["request"]["derived"]["as_of"]):
                    res.err(src, f"{sid}: {what} [{cid}] {'available' if what == 'disclosure' else 'published'} {pub} after as_of")
    for sec in doc["sections"]:  # 근거 참조 블록의 id 는 색인에 있어야 한다
        for b in sec["blocks"]:
            if b["type"] == "evidence_ref" and b.get("ids"):
                bad = [i for i in b["ids"] if i not in idx]
                if bad:
                    res.err("code", f"{sec['id']}: evidence_ref has unknown ids {bad[:5]}")
    # 시장 분석 문단(14c): 뉴스·공시 근거가 하나라도 있으면 인용해야 한다
    news_ids = [k for k in idx if k.startswith(("ev", "dc"))]
    market_paras = [t for sid, t, src in paras3 if sid == "market" and src == "14c"]
    if news_ids and market_paras and not any(CITE_RE.search(t) for t in market_paras):
        res.err("14c", "market: paragraphs must cite at least one evidence id (news available)")
    banned = list(settings.report.banned_phrases)
    for sid, text, src in paras3:
        clean = text
        for term in ALLOWED_TERMS:
            clean = clean.replace(term, "")
        for w in banned:
            if any(not _negated(clean, i, w) for i in _find_all(clean, w)):
                res.err(src, f"{sid}: banned phrase '{w}'")
        for w in DEV_WORDS:
            if w in text:
                res.warnings.append(f"{sid}: development term '{w}'")
    # 숫자 대조
    known: set[float] = set()
    known_numbers({k: v for k, v in R.items() if k not in ("backtest", "evidence_index")}, known)
    known_numbers({k: v for k, v in R["backtest"].items() if k != "series_dates"}, known)
    for sid, text in paras:
        plain = CITE_RE.sub("", text)
        for m in NUM_RE.finditer(plain):
            raw, unit = m.group(1), m.group(2)
            if not unit and not m.group(0).lstrip().startswith("$"):
                continue
            try:
                v = abs(float(raw.replace(",", "")))
            except ValueError:
                continue
            if v < 2 and unit in ("일", "개", "회", "종목", "배"):
                continue
            if unit in ("일", "개", "회", "종목") and v <= 60:
                continue
            if round(v, 2) not in known and round(v, 1) not in known and round(v) not in known:
                msg = f"{sid}: number {m.group(0).strip()} not found in results"
                if settings.report.strict_numbers:
                    res.err(next((src for s2, t2, src in paras3 if s2 == sid and t2 == text), "code"), msg)
                else:
                    res.warnings.append(msg)
    return res
