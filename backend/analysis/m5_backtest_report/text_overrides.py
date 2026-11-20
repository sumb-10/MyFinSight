"""저장된 리포트의 「종합 판단 → 선택 근거 자세히 보기」 본문을 새 작성 규칙으로 다시 쓴 글 (2026-11-16 사용자 요청).

리포트 문서(DB report.doc_json)는 한 번 쓰면 바꾸지 않는다(persist.py). 그래서 다시 쓴 두 문단 묶음만
<store>/report_text_overrides/<report_id>.json 에 두고, 리포트를 읽을 때 종합 판단(verdict) 섹션의 두 문단 블록만 바꿔 보낸다.
- 14b 서술의 종합 판단(overview_ko) → verdict 의 paragraphs(src 14b)
- 14a 해석의 조건·위험 문단(risk_fit_ko) → verdict 의 paragraphs(src 14a)
- 14b 서술의 비중 설명(construction_ko, 있으면) → construction 의 묶음 밖 paragraphs(src 14b) = 「비중 결정 설명」 (2026-11-16)
- 14a 해석의 성과 해석(performance_ko, 있으면) → performance 의 묶음 밖 paragraphs(src 14a) = 「성과 해석」 (2026-11-16)
- 14c 시장 분석(market_ko, 있으면) → market 의 묶음 밖 paragraphs(src 14c) = 「주요 뉴스와 공시」 (2026-11-16)
- 14b 서술의 분석 기준일 뉴스 설명(forward_ko, 있으면) → construction 의 「분석 기준일의 현재 구성」 묶음 paragraphs(src 14b) = 「종목·비중을 정한 근거」 (2026-11-16)
- 「확인한 한계」 카드(limitations: [{title_ko, text_ko}], 있으면) → assumptions 의 cards「확인한 한계」 (2026-11-16, 코드로 만든 글 · 모델 호출 없음)
- 7. 「분석의 전제」(assumptions_ko + reconsideration_ko) → assumptions 의 paragraphs(src 14b), 「다음 분석에서 바꿔 볼 조건」(next_actions_ko) → cards + summary.next_actions_ko,
  「중요한 주의 사항」·「참고」 쉬운 문장(summary_patch = caution_text.summary_patch, 코드로 만든 글) → summary.verdict·validation 에 덧씌움 (2026-11-16)
- 4. 「조건별 근거 보기」(서버 묶음 이름 '검증 상세'): validation_ko → 그 묶음의 paragraphs(src 14a),
  validation_tables([선택 전략의 조건별 결과, 전략별 점검 결과], 코드로 만든 표) → 그 묶음의 예전 두 표 자리 (2026-11-16)
원래대로 되돌리려면 그 파일을 지운다. 그 밖의 섹션·맨 위 한 줄 결론은 저장된 글 그대로다.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from backend.analysis.common.store import JsonStore

DIR = "report_text_overrides"
VERSION = "2026-11-16"


def rel(report_id: str) -> str:
    return f"{DIR}/{report_id}.json"


def load(store: JsonStore, report_id: str) -> dict[str, Any] | None:
    ov = store.read(rel(report_id), None)
    if not isinstance(ov, dict):
        return None
    if not (_texts(ov.get("overview_ko")) and _texts(ov.get("risk_fit_ko"))) and not _cards(ov.get("limitations")) \
            and not _texts(ov.get("assumptions_ko")) and not _texts(ov.get("next_actions_ko")) and not isinstance(ov.get("summary_patch"), dict) \
            and not _texts(ov.get("validation_ko")) and not isinstance(ov.get("validation_tables"), list):
        return None
    return ov


def save(store: JsonStore, report_id: str, obj: dict[str, Any]) -> None:
    store.write(rel(report_id), {**obj, "report_id": report_id, "version": VERSION})


def _texts(x: Any) -> list[str] | None:
    return [str(t) for t in x if str(t).strip()] if isinstance(x, list) and any(str(t).strip() for t in x) else None


def _cards(x: Any) -> list[dict[str, Any]] | None:
    """[{title_ko, text_ko}] 중 본문이 있는 카드만 (meta 는 빈 목록)."""
    if not isinstance(x, list):
        return None
    out = [{"title_ko": str(c.get("title_ko") or ""), "text_ko": str(c["text_ko"]), "meta": []} for c in x if isinstance(c, dict) and str(c.get("text_ko") or "").strip()]
    return out or None


def _cards_block(doc: dict[str, Any], sid: str, title: str) -> dict[str, Any] | None:
    sec = next((s for s in doc.get("sections") or [] if s.get("id") == sid), None)
    return next((b for b in (sec or {}).get("blocks") or [] if b.get("type") == "cards" and b.get("title_ko") == title), None)


def _targets(doc: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    sec = next((s for s in doc.get("sections") or [] if s.get("id") == "verdict"), None)
    if not sec:
        return None
    paras = [b for b in sec.get("blocks") or [] if b.get("type") == "paragraphs"]
    b14 = next((b for b in paras if b.get("src") == "14b"), None)
    a14 = next((b for b in paras if b.get("src") == "14a"), None)
    return (b14, a14) if b14 is not None and a14 is not None else None


def _section_para(doc: dict[str, Any], sid: str, src: str) -> dict[str, Any] | None:
    sec = next((s for s in doc.get("sections") or [] if s.get("id") == sid), None)
    return next((b for b in (sec or {}).get("blocks") or [] if b.get("type") == "paragraphs" and b.get("src") == src and not b.get("group_ko")), None)


def _group_para(doc: dict[str, Any], sid: str, group: str, src: str) -> dict[str, Any] | None:
    sec = next((s for s in doc.get("sections") or [] if s.get("id") == sid), None)
    return next((b for b in (sec or {}).get("blocks") or [] if b.get("type") == "paragraphs" and b.get("src") == src and b.get("group_ko") == group), None)


def _construction_target(doc: dict[str, Any]) -> dict[str, Any] | None:
    sec = next((s for s in doc.get("sections") or [] if s.get("id") == "construction"), None)
    return next((b for b in (sec or {}).get("blocks") or [] if b.get("type") == "paragraphs" and b.get("src") == "14b" and not b.get("group_ko")), None)


def apply(doc: dict[str, Any], ov: dict[str, Any] | None) -> dict[str, Any]:
    """덧씌울 글이 있는 블록만 바꾼 사본. 덧씌울 글이 없거나 문서 모양이 다르면 그 블록은 원래 글 그대로 (아무것도 안 바뀌면 원래 문서)."""
    if not ov:
        return doc
    out = copy.deepcopy(doc)
    secs: list[str] = []
    ov_b, ov_a = _texts(ov.get("overview_ko")), _texts(ov.get("risk_fit_ko"))
    if ov_b and ov_a and _targets(out) is not None:  # 종합 판단 두 문단은 함께만
        b14, a14 = _targets(out)  # type: ignore[misc]
        b14["items"], a14["items"] = ov_b, ov_a
        secs.append("verdict")
    if (ov_l := _cards(ov.get("limitations"))) and (lim := _cards_block(out, "assumptions", "확인한 한계")) is not None:
        lim["items"] = ov_l
        secs.append("limitations")
    if (ov_c := _texts(ov.get("construction_ko"))) and (c14 := _construction_target(out)) is not None:
        c14["items"] = ov_c
        secs.append("construction")
    if (ov_p := _texts(ov.get("performance_ko"))) and (p14 := _section_para(out, "performance", "14a")) is not None:
        p14["items"] = ov_p
        secs.append("performance")
    if (ov_m := _texts(ov.get("market_ko"))) and (m14 := _section_para(out, "market", "14c")) is not None:
        m14["items"] = ov_m
        secs.append("market")
    if (ov_f := _texts(ov.get("forward_ko"))) and (f14 := _group_para(out, "construction", "분석 기준일의 현재 구성", "14b")) is not None:
        f14["items"] = ov_f
        secs.append("forward")
    # 7. 주의 사항과 전제 (2026-11-16): 「분석의 전제」 문단(14b assumptions_ko + reconsideration_ko), 「다음 분석에서 바꿔 볼 조건」 카드(14a next_actions_ko),
    # 「중요한 주의 사항」·「참고」의 쉬운 문장(summary_patch: 코드로 만든 글)
    if (ov_as := _texts(ov.get("assumptions_ko"))) and (as14 := _section_para(out, "assumptions", "14b")) is not None:
        as14["items"] = ov_as + (_texts(ov.get("reconsideration_ko")) or [])
        secs.append("assumptions")
    if (ov_n := _texts(ov.get("next_actions_ko"))) and (nx := _cards_block(out, "assumptions", "다음에 검토할 수 있는 선택지")) is not None:
        tl = [str(t).strip() for t in ov.get("next_action_titles_ko") or []]
        ok = len(tl) == len(ov_n) and all(tl)
        nx["items"] = [{"title_ko": tl[i] if ok else f"선택지 {i + 1}", "text_ko": t, "meta": []} for i, t in enumerate(ov_n)]  # 조건의 뜻을 담은 제목 (2026-11-19)
        if isinstance(out.get("summary"), dict):
            out["summary"]["next_actions_ko"] = ov_n
        secs.append("next_actions")
    if (ov_v := _texts(ov.get("validation_ko"))) and (v14 := _group_para(out, "performance", "검증 상세", "14a")) is not None:
        v14["items"] = ov_v
        secs.append("validation")
    if isinstance(vt := ov.get("validation_tables"), list) and len(vt) == 2 and all(isinstance(t, dict) and t.get("type") == "table" for t in vt):
        sec = next((s for s in out.get("sections") or [] if s.get("id") == "performance"), None)
        blocks = (sec or {}).get("blocks") or []
        old = [i for i, b in enumerate(blocks) if b.get("type") == "table" and b.get("group_ko") == "검증 상세"
               and re.match(r"검증 규칙 \(|전체 포트폴리오 검증 요약|선택 전략의 조건별 결과 \(|전략별 점검 결과", str(b.get("title_ko") or ""))]  # fmt: skip
        if len(old) == 2:
            for i, t in zip(old, vt, strict=True):
                blocks[i] = {**t, "group_ko": "검증 상세", **({"group_open": blocks[i]["group_open"]} if "group_open" in blocks[i] else {})}
            secs.append("validation_tables")
    if isinstance(sp := ov.get("summary_patch"), dict) and isinstance(out.get("summary"), dict):
        for k in ("verdict", "validation"):
            if isinstance(sp.get(k), dict) and isinstance(out["summary"].get(k), dict):
                out["summary"][k].update(sp[k])
        secs.append("cautions")
    if not secs:
        return doc
    out["text_override"] = {"version": ov.get("version"), "created_at": ov.get("created_at"), "sections": secs}
    return out
