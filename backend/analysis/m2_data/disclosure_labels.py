"""공시 사건 종류(event_type, backend/collectors/disclosures/categories.py 규칙) → 한국어 라벨과 표시 문구.

SEC 공시의 title 은 대개 "8-K" 뿐이라 사건 종류·항목 번호가 정보다. DART 는 보고서 이름이 설명적이라 그대로 쓴다.
"""

from __future__ import annotations

from typing import Any

EVENT_LABEL_KO: dict[str, str] = {
    # 사건 (SEC 8-K item · DART 키워드)
    "earnings": "실적 발표", "bankruptcy": "부도·회생", "restatement": "재무제표 재작성", "control_change": "최대주주·경영권 변경",
    "acquisition_disposition": "자산·지분 취득/처분", "material_agreement": "주요 계약", "agreement_termination": "계약 해지",
    "debt_acceleration": "채무 조기상환 요구", "restructuring": "구조조정", "impairment": "손상차손", "delisting_notice": "상장폐지·관리종목 통지", "delisting": "상장폐지 신고", "deregistration": "등록 철회", "late_filing": "보고서 제출 지연",
    "auditor_change": "감사인 변경", "executive_change": "임원 변경", "cybersecurity": "사이버 보안 사건", "debt_obligation": "채무·보증 부담",
    "unregistered_equity_sale": "비등록 주식 매각", "rights_modification": "주주 권리 변경", "charter_amendment": "정관 변경", "shareholder_vote": "주주 의결",
    "reg_fd": "공정공시(Reg FD)", "other_event": "기타 중요 사건", "fiscal_year_change": "회계연도 변경", "ethics_waiver": "윤리규정 예외",
    "benefit_plan_blackout": "임직원 거래 제한 기간", "merger_split": "합병·분할", "merger_registration": "합병 등록(S-4)", "capital_change": "증자·감자",
    "securities_offering": "증권 발행", "buyback": "자사주 취득·처분 결정", "dividend": "배당 결정", "litigation": "소송·제재", "capex": "신규 시설투자",
    "production_change": "생산 중단·재개", "rumor_response": "풍문·조회공시 답변", "fair_disclosure": "공정공시", "voluntary_disclosure": "자율공시",
    "tender_offer": "공개매수", "foreign_current_report": "해외 발행사 수시보고(6-K)",
    # 정기 보고·절차 (뷰 근거는 아니고 요약에만)
    "annual_report": "사업보고서·연간 보고(10-K)", "semiannual_report": "반기보고서", "quarterly_report": "분기보고서(10-Q)", "audit_report": "감사보고서",
    "proxy": "의결권 위임장", "shareholder_meeting": "주주총회", "investor_relations": "기업설명회(IR)", "major_holder": "대량 보유 보고",
    "related_party": "특수관계인 거래", "derivative_offering": "파생결합증권 발행", "offering_document": "증권 발행 후속 서류", "exhibits_only": "첨부 서류만",
    "current_report": "수시 보고", "other": "기타",
}
SEC_ITEM_LABEL_KO: dict[str, str] = {"1.01": "계약", "1.02": "계약 해지", "1.03": "파산", "1.05": "사이버", "2.01": "취득·처분", "2.02": "실적", "2.03": "채무", "2.04": "조기상환",
                                     "2.05": "구조조정", "2.06": "손상", "3.01": "상장폐지 통지", "3.02": "주식 매각", "3.03": "권리 변경", "4.01": "감사인", "4.02": "재작성",
                                     "5.01": "경영권", "5.02": "임원", "5.03": "정관", "5.07": "주주 의결", "7.01": "Reg FD", "8.01": "기타", "9.01": "첨부"}  # fmt: skip


def label_ko(event_type: str | None) -> str:
    return EVENT_LABEL_KO.get(event_type or "", event_type or "분류 없음")


def display_title(rec: dict[str, Any]) -> str:
    """사람이 읽을 제목. SEC: '8-K 2.02,9.01 · 실적 발표' / DART: 보고서 이름 그대로."""
    form = (rec.get("form") or "").strip()
    title = (rec.get("title") or "").strip()
    lab = label_ko(rec.get("event_type"))
    if (rec.get("source") or "").upper().startswith("SEC"):
        items = (rec.get("items") or "").strip()
        head = f"{form} {items}".strip() or title or "SEC 공시"
        return f"{head} · {lab}"
    return title or form or lab
