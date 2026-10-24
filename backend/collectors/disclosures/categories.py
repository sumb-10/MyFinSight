"""공시 유형 규칙: (출처, 양식, 8-K item, 제목) → event_type.

규칙을 바꾸면 그 출처의 버전(SEC_RULE_VERSION·DART_RULE_VERSION)을 올리고, 저장된 행의
rule_version 으로 다시 분류할 행을 찾는다 (backend/scripts/reclassify_disclosures.py).
행마다 어느 규칙표를 썼는지도 rule_version 에 남긴다:
- sec-<버전>: 2004-08-23 이후 8-K (지금 Item 번호 1.01~9.01) 와 그 밖의 SEC 양식
- sec-old-<버전>: 2004-08-23 전 8-K (옛 Item 1~12 체계: Item 5 = 기타, 9 = Reg FD, 12 = 실적)
- dart-<버전>: DART 보고서 이름 키워드
"""

from __future__ import annotations

import re
from datetime import date

SEC_RULE_VERSION = "v1"
DART_RULE_VERSION = "v2"  # v2: 증권 발행을 파생결합증권·후속 서류·신고(결정)로 나눔
SEC_NEW_ITEMS_FROM = date(2004, 8, 23)
"""8-K Item 번호가 지금 체계(1.01~9.01)로 바뀐 날 (SEC Release 33-8400)."""

# 여러 item 이 같이 있으면 먼저 나오는 것 (중요한 사건 먼저, 9.01 첨부는 마지막)
SEC_ITEMS: list[tuple[str, str]] = [
    ("1.03", "bankruptcy"),
    ("4.02", "restatement"),
    ("2.02", "earnings"),
    ("5.01", "control_change"),
    ("2.01", "acquisition_disposition"),
    ("1.01", "material_agreement"),
    ("1.02", "agreement_termination"),
    ("2.04", "debt_acceleration"),
    ("2.05", "restructuring"),
    ("2.06", "impairment"),
    ("3.01", "delisting_notice"),
    ("4.01", "auditor_change"),
    ("5.02", "executive_change"),
    ("1.05", "cybersecurity"),
    ("2.03", "debt_obligation"),
    ("3.02", "unregistered_equity_sale"),
    ("3.03", "rights_modification"),
    ("5.03", "charter_amendment"),
    ("5.07", "shareholder_vote"),
    ("7.01", "reg_fd"),
    ("8.01", "other_event"),
]
SEC_OLD_ITEMS: list[tuple[str, str]] = [
    ("3", "bankruptcy"),
    ("12", "earnings"),  # 2003-03 부터 실적 발표
    ("1", "control_change"),
    ("2", "acquisition_disposition"),
    ("4", "auditor_change"),
    ("6", "executive_change"),  # 이사 사임
    ("8", "fiscal_year_change"),
    ("10", "ethics_waiver"),
    ("11", "benefit_plan_blackout"),
    ("9", "reg_fd"),  # 2003-03 전에는 실적 발표도 Item 9 로 많이 냄
    ("5", "other_event"),
]
SEC_FORMS: dict[str, str] = {
    "10-K": "annual_report",
    "10-K405": "annual_report",
    "10-KT": "annual_report",
    "20-F": "annual_report",
    "40-F": "annual_report",
    "10-Q": "quarterly_report",
    "10-QT": "quarterly_report",
    "6-K": "foreign_current_report",
    "DEF 14A": "proxy",
    "DEFA14A": "proxy",
    "SC 13D": "major_holder",
    "SC 13G": "major_holder",
    "SC TO-T": "tender_offer",
    "SC TO-I": "tender_offer",
    "S-1": "securities_offering",
    "S-3": "securities_offering",
    "S-4": "merger_registration",
    "NT 10-K": "late_filing",
    "NT 10-Q": "late_filing",
    "25-NSE": "delisting",
    "15-12B": "deregistration",
}
"""저장하는 SEC 양식 (8-K 계열 + 이것들, 끝의 /A 는 정정). Form 3·4·5(내부자 거래)와
424B·FWP(증권 발행 보충 서류, 은행은 수만 건)는 받지 않는다."""
SEC_8K = ("8-K", "8-K12B", "8-K12G3")

DART_RULES: list[tuple[str, str]] = [
    # (보고서 이름 정규식, event_type). 위에서부터 처음 맞는 것
    (r"^사업보고서", "annual_report"),
    (r"^반기보고서", "semiannual_report"),
    (r"^분기보고서", "quarterly_report"),
    (r"감사보고서", "audit_report"),
    (r"부도|회생절차|파산|영업정지|해산사유", "bankruptcy"),
    (r"상장폐지|관리종목|불성실공시|매매거래정지", "delisting_notice"),
    (r"잠정\)?실적|영업\(잠정\)|매출액또는손익구조|손익구조", "earnings"),
    (r"최대주주(또는주요주주)?변경|최대주주인수|경영권", "control_change"),
    (r"대량보유|최대주주등소유주식변동", "major_holder"),
    # 계열사·대주주와의 거래 (공정거래법·자본시장법 공시): 건수가 많아 따로 묶음
    (
        r"특수관계인|최대주주등(에대한|으로부터|과의)|동일인등출자계열회사|계열금융회사"
        r"|대규모기업집단|약관에의한금융거래",
        "related_party",
    ),
    (r"합병|분할|주식교환|주식이전|영업양수|영업양도|자산양수|자산양도", "merger_split"),
    (r"타법인주식|유형자산(취득|처분)", "acquisition_disposition"),
    (r"유상증자|무상증자|감자", "capital_change"),
    # 증권사·카드사가 수시로 내는 ELS·DLS·ELW 서류 (일괄신고 투자설명서 포함). 미국 424B·FWP 같은 잡음
    (r"파생결합|주식워런트|주가연계|^투자설명서\(일괄신고\)$", "derivative_offering"),
    # 신고·결정 뒤의 후속 서류 (투자설명서·발행실적보고서): 사건은 신고(결정) 쪽
    (r"투자설명서|발행실적보고서", "offering_document"),
    (
        r"전환사채|신주인수권부사채|교환사채|사채권발행|증권신고서|증권발행",
        "securities_offering",
    ),
    (r"자기주식|자사주", "buyback"),
    (r"배당", "dividend"),
    (r"단일판매|공급계약", "material_agreement"),
    (r"소송|횡령|배임|제재", "litigation"),
    (r"대표이사|임원|사외이사|독립이사", "executive_change"),
    (r"채무보증", "debt_obligation"),
    (r"신규시설투자", "capex"),
    (r"생산중단|생산재개", "production_change"),
    (r"의결권대리행사", "proxy"),
    (r"기업설명회|\(IR\)", "investor_relations"),
    (r"풍문또는보도|조회공시", "rumor_response"),
    (r"주주총회|정기주총|임시주총", "shareholder_meeting"),
    (r"공정공시", "fair_disclosure"),
    (r"자율공시|기타경영사항|기타주요경영사항", "voluntary_disclosure"),
]
DART_SKIP = re.compile(
    r"임원ㆍ주요주주특정증권등소유상황보고서|임원·주요주주특정증권등소유상황보고서"
)
"""저장하지 않는 DART 보고서 (임원·주요주주 개인의 주식 변동, SEC Form 4 와 같은 종류)."""
DART_AMEND = re.compile(
    r"^\s*\[(기재정정|첨부정정|첨부추가|변경등록|정정명령부과|연장결정|발행조건확정)\]\s*"
)


def sec_base_form(form: str) -> tuple[str, bool]:
    """'8-K/A' → ('8-K', True)."""
    f = (form or "").strip().upper()
    return (f[:-2], True) if f.endswith("/A") else (f, False)


def sec_keep(form: str) -> bool:
    base, _ = sec_base_form(form)
    return base in SEC_8K or base in SEC_FORMS


def sec_event(form: str, items: str | None, filed: date) -> tuple[str, str]:
    """SEC 공시 → (event_type, rule_version)."""
    base, _ = sec_base_form(form)
    old = filed < SEC_NEW_ITEMS_FROM
    rule = f"sec-old-{SEC_RULE_VERSION}" if old and base in SEC_8K else f"sec-{SEC_RULE_VERSION}"
    if base not in SEC_8K:
        return SEC_FORMS.get(base, "other"), rule
    have = {x.strip() for x in (items or "").split(",") if x.strip()}
    if old:  # 옛 번호는 정수 ("5", "7"), 새 번호를 섞어 쓴 행은 거의 없음
        have = {x.split(".")[0].lstrip("0") or "0" for x in have}
    for item, event in SEC_OLD_ITEMS if old else SEC_ITEMS:
        if item in have:
            return event, rule
    return ("exhibits_only" if have else "current_report"), rule


def dart_form(report_nm: str) -> tuple[str, bool]:
    """DART 보고서 이름 → (정정 표시와 끝의 (YYYY.MM) 를 뺀 이름, 정정 여부)."""
    name = (report_nm or "").strip()
    amended = False
    while m := DART_AMEND.match(name):
        amended = amended or "정정" in m.group(1)
        name = name[m.end() :]
    name = re.sub(r"\s*\(\d{4}\.\d{2}\)\s*$", "", name).strip()
    return name, amended


def dart_keep(report_nm: str) -> bool:
    return not DART_SKIP.search(report_nm or "")


def dart_event(report_nm: str) -> tuple[str, str]:
    name, _ = dart_form(report_nm)
    compact = name.replace(" ", "")
    for pattern, event in DART_RULES:
        if re.search(pattern, compact):
            return event, f"dart-{DART_RULE_VERSION}"
    return "other", f"dart-{DART_RULE_VERSION}"
