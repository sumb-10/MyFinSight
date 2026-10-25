"""M1-02 보충 질문 대화. 한 턴 = 조립 → HARD 검증 → 파생값 → 의도 해석(LLM, 질문 제안) → 코드가 질문 1개 선택.

규칙: 1회 1항목, 최대 N회(설정). HARD 오류는 질문이 아니라 즉시 수정 안내. 선택지 답은 코드가 필드에 반영하고,
자유 입력은 아이디어에 덧붙여 다음 턴의 LLM 이 해석한다. 확인(confirm) 전에는 분석을 시작하지 않는다.
같은 프로필·아이디어·답 → 같은 대화 → 같은 LLM 캐시 키 → 같은 요청 (요구 14).
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
from typing import Any

from backend.analysis.common.jsonio import canonical_json, now_iso, sha256_hex
from backend.analysis.common.llm import LlmClient
from backend.analysis.common.store import JsonStore, ProfileStore, RequestStore, new_request_id, new_run_id
from backend.analysis.errors import Conflict, DialogBlocked, DialogNotReady, NotFound, RequestInvalid
from backend.analysis.executor.queue import Queue
from backend.analysis.m1_request import assemble
from backend.analysis.m1_request.conditions import condition_rows
from backend.analysis.m1_request.derive import derive
from backend.analysis.m1_request.history import context_package
from backend.analysis.m1_request.precheck import precheck as run_precheck
from backend.analysis.m1_request.validate import hard_errors, label
from backend.analysis.m2_data import descriptor as D
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.m3_selection.intent import build_messages, interpret
from backend.analysis.m1_request import revision
from backend.analysis.schemas.dialog import AnalysisRequestDoc, DialogMessage, DialogState, DialogSummary, Question, QuestionProposal, RevisionDraft
from backend.analysis.schemas.request import UNIVERSE_MARKET
from backend.analysis.settings import AnalysisSettings

KIND_ORDER = {"feasibility": 0, "missing": 1, "conflict": 2, "ambiguous": 3, "preference": 4}


def _dicts(messages: list[Any]) -> list[dict[str, str]]:
    """저장소에서 읽은 DialogMessage 모델과 새로 붙인 dict 를 모두 {"role","content"} dict 로."""
    return [m if isinstance(m, dict) else {"role": m.role, "content": m.content} for m in messages]


_YEAR = r"(19\d{2}|20\d{2})\s*년"


def parse_period(text: str, *, today: dt.date, max_years: float = 20.0) -> dict[str, Any] | None:
    """아이디어 문장에서 백테스트 기간을 읽는다. 돌려주는 값: start_year, end_year(없으면 None=지금까지), years, end_date(YYYY-12-31 또는 None).

    "2005년부터 약 12년간" → 2005~2016 (12년) / "2006년 경제위기 ~ 2016년까지" → 2006~2016 (11년, 양끝 포함)
    "2010년부터" → 2010~지금 / "2016년까지" → 기본 길이 없이는 못 정하므로 None.
    """
    t = text or ""
    years = [int(y) for y in re.findall(_YEAR, t)]
    m_len = re.search(r"(?:약\s*)?(\d{1,2})\s*년\s*(?:간|동안|정도|치)", t)
    length = int(m_len.group(1)) if m_len else None
    if not years:
        return None
    if length is not None and length >= 100:
        return None
    if len(years) >= 2:
        start, end = min(years), max(years)
        n = float(end - start + 1)
    elif length is not None and length > 0:
        start = years[0]
        end = start + length - 1
        n = float(length)
    elif re.search(_YEAR + r"\s*(?:부터|이후|이래|~|-)", t):
        start, end = years[0], None
        n = round((today - dt.date(start, 1, 1)).days / 365.25, 1)
    else:
        return None
    if end is not None and end >= today.year:
        end = None
        n = round((today - dt.date(start, 1, 1)).days / 365.25, 1)
    if n <= 0:
        return None
    n = min(n, max_years)
    return {"start_year": start, "end_year": end, "years": n, "end_date": f"{end}-12-31" if end else None}


class DialogService:
    def __init__(self, store: JsonStore, repo: Any, md: MarketData, llm: LlmClient, settings: AnalysisSettings) -> None:
        self.store, self.repo, self.md, self.llm, self.s = store, repo, md, llm, settings
        self.requests = RequestStore(store)
        self.profiles = ProfileStore(store)
        self.queue = Queue(store)

    # ───────────────────────── 공개 API ─────────────────────────
    def start(self, idea: str, *, overrides: dict[str, Any] | None = None, mode: str = "new", base_report_id: str | None = None,
              language: str = "ko", profile_version: int | None = None, clarifications: list[str] | None = None, revision: RevisionDraft | None = None) -> DialogState:  # fmt: skip
        prof = self.profiles.current()
        if prof is None:
            raise RequestInvalid("프로필을 먼저 등록해 주세요", details={"fields": {"profile": "프로필 없음"}})
        if profile_version is not None:
            prof = self.profiles.version(profile_version)
        if len((idea or "").strip()) < 5:
            raise RequestInvalid("투자 아이디어를 5자 이상 적어 주세요", details={"fields": {"natural_language.idea": "5자 이상"}})
        doc = AnalysisRequestDoc(request_id=new_request_id(), created_at=now_iso(), mode=mode, base_report_id=base_report_id,
                                 profile_version=prof["version"], idea=idea.strip(), language=language, overrides=dict(overrides or {}),
                                 idea_clarifications=[c for c in (clarifications or []) if c and c.strip()], revision=revision,
                                 max_questions=self.s.dialog.max_questions)  # fmt: skip
        with self.requests.locked(doc.request_id):
            doc = self._turn(doc)
            self.requests.save(doc)
        return self.state(doc)

    def start_revision(self, base_report_id: str, text: str) -> DialogState:
        """기준 리포트 + 자연어 수정 요청 → LLM 변경 초안(코드 검증) → revision 모드 대화. 평가 조건은 원안과 같게 고정 (M1-05)."""
        if len((text or "").strip()) < 3:
            raise RequestInvalid("수정 요청을 3자 이상 적어 주세요", details={"fields": {"text": "3자 이상"}})
        base_doc, base_results = self._base(base_report_id)
        base_req = base_results.get("request") or base_doc.effective_request  # 01_request 출력 (derived 포함)
        sel = base_results.get("selection", {})
        names = {r.get("ticker"): r.get("name") or "" for r in (sel.get("table") or [])}
        held = [x["ticker"] if isinstance(x, dict) else str(x) for x in ((sel.get("as_of_now") or {}).get("selected") or [])]
        holdings = [(t, names.get(t, "")) for t in held] or [(t, n) for t, n in names.items()]
        draft = revision.propose(base_req, base_doc.intent or base_results.get("intent") or {}, holdings, text, self.llm)
        draft.base_run_id = base_doc.run_id
        overrides = revision.overrides_from(draft, base_req)
        clar = [f"[수정 요청] {text.strip()}"] + ([f"[테마 범위 변경] {draft.idea_update_ko}"] if draft.idea_update_ko else [])
        return self.start(base_doc.idea, overrides=overrides, mode="revision", base_report_id=base_report_id, language=base_doc.language,
                          profile_version=base_doc.profile_version, clarifications=[*base_doc.idea_clarifications, *clar], revision=draft)  # fmt: skip

    def _base(self, base_report_id: str) -> tuple[AnalysisRequestDoc, dict[str, Any]]:
        """기준 리포트의 확정 요청과 결과 묶음."""
        entry = self.queue.get(base_report_id)
        base_doc = self.requests.load(entry.request_id)
        if not base_doc.effective_request:
            raise RequestInvalid("기준 리포트의 확정 요청이 없습니다")
        art = self.repo.get_run_artifact(base_report_id)
        if not art:
            raise NotFound(f"기준 리포트 {base_report_id} 의 결과가 없습니다")
        return base_doc, art["results"]

    def get(self, request_id: str) -> DialogState:
        return self.state(self.requests.load(request_id))

    def answer(self, request_id: str, seq: int, *, option_value: Any = None, free_text: str | None = None) -> DialogState:
        with self.requests.locked(request_id):
            doc = self.requests.load(request_id)
            if doc.status != "draft":
                raise Conflict(f"요청이 이미 {doc.status} 상태입니다")
            q = next((x for x in doc.questions if x.seq == seq), None)
            if q is None:
                raise NotFound(f"질문 {seq} 이 없습니다")
            if q.answered_at:
                raise Conflict(f"질문 {seq} 에는 이미 답했습니다")
            if option_value is None and not (free_text and free_text.strip()):
                raise RequestInvalid("선택지를 고르거나 답을 적어 주세요", details={"fields": {"answer": "비어 있음"}})
            now = now_iso()
            if option_value is not None:
                opt = next((o for o in q.options if o.value == option_value), None)
                shown = opt.label_ko if opt else str(option_value)
                if opt is not None and (opt.patch or opt.clarification):  # 라운드 5: 여러 필드를 한 번에 바꾸거나 아이디어를 보태는 보기
                    for k, v in (opt.patch or {}).items():
                        doc.overrides[k] = v
                    if opt.clarification:
                        doc.idea_clarifications.append(opt.clarification)
                    q.applied = {"field": q.field, "value": option_value, "patch": opt.patch, "clarification": opt.clarification}
                elif q.field == "natural_language.idea":
                    doc.idea_clarifications.append(shown)
                else:
                    doc.overrides[q.field] = option_value
                    q.applied = {"field": q.field, "value": option_value}
                q.answer = shown
            else:
                q.free_text = free_text.strip()
                q.answer = q.free_text
                doc.idea_clarifications.append(f"[{label(q.field)}] {q.free_text}")
            q.answered_at = now
            doc.messages.append(DialogMessage(role="user", content=self._answer_message(doc, q)))
            doc = self._turn(doc)
            self.requests.save(doc)
        return self.state(doc)

    def update_overrides(self, request_id: str, overrides: dict[str, Any]) -> DialogState:
        """조건 확인 화면에서 사용자가 버튼·폼으로 조건을 직접 바꿈 (값이 None 이면 그 덮어쓰기를 지움 → 프로필 값으로). 새 턴을 돈다."""
        with self.requests.locked(request_id):
            doc = self.requests.load(request_id)
            if doc.status != "draft":
                raise Conflict(f"요청이 이미 {doc.status} 상태입니다")
            changed = []
            for k, v in (overrides or {}).items():
                if k.startswith("_") or k == "natural_language.idea":
                    continue
                if v is None:
                    if k in doc.overrides:
                        doc.overrides.pop(k)
                        changed.append(f"{label(k)}: 프로필 값으로")
                else:
                    doc.overrides[k] = v
                    changed.append(f"{label(k)} = {json.dumps(v, ensure_ascii=False)}")
            if not changed:
                return self.state(doc)
            self._settle_pending(doc, "(조건을 직접 바꿔 건너뜀)")
            doc.messages.append(DialogMessage(role="user", content="사용자가 조건을 직접 바꿨습니다: " + "; ".join(changed)
                                              + "\n이 값은 이번 요청의 확정 입력(HARD)이니 그대로 두고, 바뀐 조건에 맞춰 의도 명세를 다시 출력하세요. 같은 항목은 묻지 않습니다."))
            doc = self._turn(doc)
            self.requests.save(doc)
        return self.state(doc)

    def message(self, request_id: str, text: str) -> DialogState:
        """질문과 상관없이 말로 조건·아이디어를 보탬. 아이디어 보충으로 붙여 다음 턴에 해석한다 (필드 값은 코드가 질문/답으로만 바꾼다)."""
        text = (text or "").strip()
        if not text:
            raise RequestInvalid("내용을 적어 주세요", details={"fields": {"text": "비어 있음"}})
        with self.requests.locked(request_id):
            doc = self.requests.load(request_id)
            if doc.status != "draft":
                raise Conflict(f"요청이 이미 {doc.status} 상태입니다")
            self._settle_pending(doc, "(말로 조건을 보태 건너뜀)")
            doc.idea_clarifications.append(f"[추가 요청] {text}")
            doc.messages.append(DialogMessage(role="user", content=f"사용자의 추가 요청: {text}\n아이디어 보충으로 반영해 의도 명세를 다시 출력하세요. 필드 값을 바꿔야 하면 그 필드를 conflict/preference 질문으로 제안하세요."))
            doc = self._turn(doc)
            self.requests.save(doc)
        return self.state(doc)

    @staticmethod
    def _settle_pending(doc: AnalysisRequestDoc, note: str) -> None:
        """대기 중인 질문이 있으면 '건너뜀' 으로 닫는다 (사용자가 다른 방법으로 조건을 바꾼 경우). 다음 턴이 필요하면 다시 묻는다."""
        for q in doc.questions:
            if not q.answered_at:
                q.skipped, q.answer, q.answered_at = True, note, now_iso()

    def skip(self, request_id: str, seq: int) -> DialogState:
        with self.requests.locked(request_id):
            doc = self.requests.load(request_id)
            q = next((x for x in doc.questions if x.seq == seq), None)
            if q is None:
                raise NotFound(f"질문 {seq} 이 없습니다")
            if q.answered_at:
                raise Conflict("이미 답한 질문입니다")
            q.skipped, q.answer, q.answered_at = True, "(답하지 않음 — 기본값 사용)", now_iso()
            doc.messages.append(DialogMessage(role="user", content=f"Q{q.seq} ({q.field}) 답: 답하지 않음. 기본값/현재 값을 그대로 쓰고 이 항목은 다시 묻지 마세요."))
            doc = self._turn(doc)
            self.requests.save(doc)
        return self.state(doc)

    def cancel(self, request_id: str) -> DialogState:
        with self.requests.locked(request_id):
            doc = self.requests.load(request_id)
            if doc.status == "draft":
                doc.status, doc.dialog_state = "cancelled", "cancelled"
                self.requests.save(doc)
        return self.state(doc)

    def confirm(self, request_id: str) -> tuple[str, int | None]:
        """(run_id, 대기 순번). 두 번 눌러도 같은 run_id (멱등)."""
        with self.requests.locked(request_id):
            doc = self.requests.load(request_id)
            if doc.status == "confirmed" and doc.run_id:
                try:
                    return doc.run_id, self.queue.position(doc.run_id)
                except NotFound:
                    return doc.run_id, None
            if doc.status != "draft":
                raise Conflict(f"요청이 {doc.status} 상태입니다")
            if doc.dialog_state == "blocked":
                raise DialogBlocked(doc.blocked_reason_ko or "미확정 항목이 남아 있습니다", details={"unresolved": self._unresolved(doc)})
            if doc.dialog_state != "ready" or not doc.draft_request or doc.hard_errors:
                raise DialogNotReady("조건 확인이 끝나지 않았습니다", details={"state": doc.dialog_state, "hard_errors": [e.model_dump() for e in doc.hard_errors]})
            eff = dict(doc.draft_request)
            fp_src = {k: v for k, v in eff.items() if k not in ("request_id", "created_at", "derived")}
            fp_src["intent_themes"] = [t["id"] for t in (doc.intent or {}).get("interpretation", {}).get("themes", [])]
            doc.effective_request = eff
            doc.request_fingerprint = sha256_hex(canonical_json(fp_src), 32)
            doc.status, doc.dialog_state, doc.confirmed_at = "confirmed", "confirmed", now_iso()
            run_id = new_run_id(dt.datetime.now())
            doc.run_id = run_id
            self.requests.save(doc)
            pos = self.queue.enqueue(run_id, doc.request_id, llm_mode=self.s.llm.mode)
            return run_id, pos

    # ───────────────────────── 한 턴 ─────────────────────────
    def _turn(self, doc: AnalysisRequestDoc) -> AnalysisRequestDoc:
        prof = self.profiles.version(doc.profile_version)
        self._fix_num_holdings(doc, prof)
        req = assemble.build(prof, doc.idea, overrides=doc.overrides, clarifications=doc.idea_clarifications, request_id=doc.request_id,
                             created_at=doc.created_at, language=doc.language)  # fmt: skip
        errs = hard_errors(req)
        doc.hard_errors = errs
        if errs:
            doc.dialog_state = "asking"
            doc.draft_request = req
            doc.warnings = [f"HARD 검증 오류 {len(errs)}건: 수정 후 계속"]
            return doc
        normalized = derive(req, self.md, self.s).model_dump(mode="json")
        doc.draft_request = normalized
        doc.derived = normalized["derived"]
        markets = sorted({UNIVERSE_MARKET[u] for u in req["constraints"]["universe"]})
        ms = self.s.market
        desc, _info, _w = D.load_for(dt.date.fromisoformat(str(doc.derived["as_of"])), req["constraints"]["universe"], markets,
                                    processed_dir=ms.descriptor_dir or D.PROCESSED, universe_file=ms.descriptor_universe)  # fmt: skip
        asked = [q.field for q in doc.questions]
        if not doc.messages:
            doc.messages = [DialogMessage(**m) for m in build_messages(normalized, desc, as_of=str(doc.derived["as_of"]), initial_amount_usd=float(doc.derived["initial_amount_usd"]),
                                                            context=context_package(self.store, self.repo), dialog_history=self._history_text(doc),
                                                            max_questions=doc.max_questions, asked_fields=asked,
                                                            explicit_fields=[k for k in doc.overrides if not k.startswith("_")])]  # fmt: skip
        spec, warns, _msgs = interpret(normalized, desc, self.llm, self.s, messages=_dicts(doc.messages), asked_fields=asked)
        intent = spec.model_dump(mode="json")
        proposals = [QuestionProposal.model_validate(q) for q in intent.pop("questions", [])]
        doc.intent = intent
        doc.messages.append(DialogMessage(role="assistant", content=json.dumps({**intent, "questions": [p.model_dump() for p in proposals]}, ensure_ascii=False)))
        doc.warnings = list(warns)
        try:  # 실행 전 점검 (LLM 없음): 후보 수·지표 보유 수를 기준일·백테스트 시작일에서 센다 (서명이 같으면 재사용)
            doc.precheck = run_precheck(normalized, intent, desc, self.md, self.s, previous=doc.precheck)
        except Exception as e:  # noqa: BLE001 — 점검은 보조 정보
            doc.precheck = None
            doc.warnings.append(f"precheck skipped: {e}")
        proposals = self._code_proposals(req, intent, desc, overrides=doc.overrides, precheck=doc.precheck) + proposals  # 코드 규칙 질문이 LLM 제안보다 앞
        chosen = self._pick_question(doc, proposals, req)
        if chosen is None:
            doc.dialog_state = "ready"
            doc.blocked_reason_ko = None
        elif len(doc.questions) >= doc.max_questions:
            # 질문 상한 (라운드 5): 막지 않고 남은 항목을 기본값(지금 조건)으로 두어 바로 확정할 수 있게 한다. 사유는 blocked_reason_ko 로 보여 준다
            doc.dialog_state = "ready"
            doc.blocked_reason_ko = (f"보충 질문 {doc.max_questions}회를 모두 써서 남은 항목은 지금 조건(기본값) 그대로 둡니다: "
                                     + ", ".join(label(p.field) for p in proposals[:3]) + ". 바꾸려면 '조건 바꾸기'나 '말로 조건 보태기'를 쓰세요.")  # fmt: skip
        else:
            doc.blocked_reason_ko = None
            q = Question(**chosen.model_dump(), seq=len(doc.questions) + 1, asked_at=now_iso(), field_label_ko=label(chosen.field))
            doc.questions.append(q)
            doc.turn = len(doc.questions)
            doc.dialog_state = "asking"
        return doc

    @staticmethod
    def _fix_num_holdings(doc: AnalysisRequestDoc, prof: dict[str, Any]) -> None:
        """목표 종목 수만 바꿨을 때 최소·최대가 어긋나면 HARD 오류 대신 자동으로 맞춘다 (라운드 5, P1-8)."""
        ov = doc.overrides
        if "constraints.num_holdings.target" not in ov or "constraints.num_holdings" in ov:
            return
        try:
            target = int(ov["constraints.num_holdings.target"])
        except (TypeError, ValueError):
            return
        pc = prof.get("constraints") or {}
        base = pc.get("num_holdings") or {}
        cur_min = int(ov.get("constraints.num_holdings.min", base.get("min", target)))
        cur_max = int(ov.get("constraints.num_holdings.max", base.get("max", target)))
        if target < cur_min:
            new_min = max(2, target)
            ov["constraints.num_holdings.min"] = new_min
            # 종목 수가 줄면 종목당 상한 × 최소 종목 수 ≥ 투자 비율이어야 한다 → 모자라면 상한도 함께 올린다 (HARD 오류 대신)
            cash = float(ov.get("constraints.min_cash_ratio", pc.get("min_cash_ratio", 0)) or 0)
            cap = float(ov.get("constraints.max_weight_per_stock", pc.get("max_weight_per_stock", 1.0)) or 1.0)
            need = math.ceil((1.0 - cash) / new_min * 100) / 100
            if cap * new_min < (1.0 - cash) - 1e-9 and need <= 1.0:
                ov["constraints.max_weight_per_stock"] = need
                sec = float(ov.get("constraints.max_weight_per_sector", pc.get("max_weight_per_sector", 1.0)) or 1.0)
                if sec < need:
                    ov["constraints.max_weight_per_sector"] = need
        if target > cur_max:
            ov["constraints.num_holdings.max"] = target

    def _feasibility_proposals(self, req: dict[str, Any], precheck: dict[str, Any] | None, overrides: dict[str, Any]) -> list[QuestionProposal]:
        """실행 전 점검 결과로 묻는 두 질문 (라운드 5): 후보 부족 · 창 축소 예상. 보기는 patch(여러 필드) 또는 clarification(테마 넓히기)."""
        if not precheck:
            return []
        out: list[QuestionProposal] = []
        cons = req["constraints"]
        nh, nh_min = cons["num_holdings"], int(cons["num_holdings"]["min"])
        cash = float(cons.get("min_cash_ratio", 0) or 0)
        stock_cap, sector_cap = float(cons["max_weight_per_stock"]), float(cons["max_weight_per_sector"])

        def shrink_patch(n: int) -> dict[str, Any]:
            cap = max(stock_cap, min(1.0, math.ceil((1.0 - cash) / n * 100) / 100))
            return {"constraints.num_holdings": {"target": n, "min": n, "max": n}, "constraints.max_weight_per_stock": cap,
                    "constraints.max_weight_per_sector": max(sector_cap, cap)}  # fmt: skip

        now = precheck.get("as_of") or {}
        n_now = int(min(now.get("n_with_metric", 0), now.get("n_candidates", 0)))
        if precheck.get("short_now") and "_ack_few_candidates" not in overrides:
            opts = []
            if n_now >= 2:
                cap = shrink_patch(n_now)["constraints.max_weight_per_stock"]
                opts.append({"value": f"shrink_{n_now}", "label_ko": f"종목 수를 {n_now}개로 줄이고 종목당 상한을 {cap:.0%}로 올려 전액 투자", "patch": shrink_patch(n_now)})
            opts.append({"value": "widen_theme", "label_ko": "테마를 넓혀 다시 해석 (인접 산업 포함)",
                         "clarification": f"[테마 넓히기] 테마에 맞는 후보가 {n_now}개뿐이라 인접 산업·관련 업종까지 넓혀 해석해 주세요"})
            opts.append({"value": "proceed", "label_ko": "그대로 진행 (현금이 남을 수 있음)", "patch": {"_ack_few_candidates": True}})
            out.append(QuestionProposal(
                field="constraints.num_holdings", kind="feasibility", priority=1,
                question_ko=(f"테마에 맞는 종목이 분석 기준일 기준 {n_now}개로, 최소 종목 수 {nh_min}개(목표 {nh['target']}개)에 못 미칩니다. 어떻게 할까요?"),
                options=opts, allow_free_text=False,
                why_ko=f"후보가 모자라면 종목당 상한({stock_cap:.0%}) 때문에 현금이 남습니다 (예: {max(n_now, 1)}종목 × {stock_cap:.0%} = {min(1.0, max(n_now, 1) * stock_cap):.0%} 투자).",
            ))  # fmt: skip
            return out  # 후보 부족이 먼저 — 창 축소 질문은 이게 풀린 뒤에
        st = precheck.get("start") or {}
        n_start = int(min(st.get("n_with_metric", 0), st.get("n_candidates", 0)))
        if precheck.get("short_at_start") and not precheck.get("short_now") and "_allow_fewer_at_start" not in overrides:  # 기준일부터 부족하면 위 질문이 다룬다 (07 도 옮기지 않음)
            opts = []
            if n_start >= 2:
                opts.append({"value": "keep_window", "label_ko": f"백테스트 기간을 유지하고 시작 때 선정 가능한 {n_start}종목으로 평가", "patch": {"_allow_fewer_at_start": True}})
            fs = precheck.get("feasible_start")
            if fs and float(fs.get("years") or 0) >= 1.0:
                opts.append({"value": f"shorten_{fs['years']}", "label_ko": f"백테스트 기간을 {fs['years']:g}년으로 줄임 ({fs['date']}부터는 {fs['n_with_metric']}종목)",
                             "patch": {"horizon.backtest_years": float(fs["years"])}})
            if n_start >= 2:
                cap = shrink_patch(n_start)["constraints.max_weight_per_stock"]
                opts.append({"value": f"shrink_{n_start}", "label_ko": f"종목 수를 {n_start}개로 줄여 처음부터 끝까지 같은 종목 수로 (상한 {cap:.0%})", "patch": shrink_patch(n_start)})
            if len(opts) >= 2:
                out.append(QuestionProposal(
                    field="horizon.backtest_years", kind="feasibility", priority=1,
                    question_ko=(f"백테스트 시작일({st.get('date')})에는 테마에 맞는 종목이 {n_start}개로 최소 {nh_min}개에 못 미칩니다. "
                                 "그대로 두면 시작일을 뒤로 옮겨 평가 기간이 짧아집니다. 어떻게 할까요?"),
                    options=opts, allow_free_text=False,
                    why_ko="과거에는 상장 전이거나 재무 지표가 없던 종목이 있어 시작일에 뽑을 수 있는 종목이 적을 수 있습니다.",
                ))  # fmt: skip
        return out

    def _code_proposals(self, req: dict[str, Any], intent: dict[str, Any], desc: Any, *, overrides: dict[str, Any] | None = None,
                        precheck: dict[str, Any] | None = None) -> list[QuestionProposal]:  # fmt: skip
        """LLM 이 아니라 코드가 만드는 질문 세 가지.
        1) 아이디어에 적힌 과거 기간("2005년부터 약 12년간", "2006년 ~ 2016년까지") 이 지금 백테스트 창과 다르면 기간을 묻는다.
        2) LLM 이 `conflicts` 에 적은 "아이디어 ↔ 프로필 기본값" 충돌(idea_value 있음)은 사용자가 고르게 질문으로 바꾼다 (자연어가 프로필 기본값을 이길 수 있게).
        3) 테마가 한 GICS 섹터에 몰려 있는데 섹터 상한 < 투자 비율이면 현금이 남는다는 사실을 알리고 "풀까요 / 유지할까요" 를 묻는다."""
        out: list[QuestionProposal] = []
        out += self._feasibility_proposals(req, precheck, overrides or {})
        out += self._period_proposal(req)
        out += self._conflict_proposals(req, intent, overrides or {})
        if not self.s.dialog.ask_sector_cap_conflict:
            return out
        cons = req["constraints"]
        cap = float(cons.get("max_weight_per_sector", 1.0))
        invest = 1.0 - float(cons.get("min_cash_ratio", 0.0) or 0.0)
        themes = (intent.get("interpretation") or {}).get("themes") or []
        sectors = {str(c)[:2] for th in themes for c in th.get("gics_codes", []) if str(c).strip()}
        if len(sectors) != 1 or cap >= invest - 1e-9:
            return out
        code = next(iter(sectors))
        names = {v[:2]: k for k, v in D.sector_name_to_code(desc).items() if k and v}
        sector_ko = names.get(code, f"섹터 {code}")
        out.append(QuestionProposal(
            field="constraints.max_weight_per_sector", kind="conflict", priority=1,  # 같은 우선순위면 코드 질문이 앞 (목록 앞에 둠)
            question_ko=f"이 아이디어의 테마는 '{sector_ko}' 한 섹터에 몰려 있습니다. 지금 섹터당 상한이 {cap:.0%}라 투자금의 {invest - cap:.0%}가 현금으로 남게 됩니다. 어떻게 할까요?",
            options=[{"value": round(invest, 4), "label_ko": f"이번 분석에서는 섹터 상한을 풀어 전액 투자 ({invest:.0%})"},
                     {"value": cap, "label_ko": f"프로필대로 {cap:.0%} 유지 (나머지 {invest - cap:.0%}는 현금)"}],
            allow_free_text=False,
            why_ko="섹터 상한은 여러 업종에 나눌 때 쓰는 보호 장치라, 한 업종만 담는 테마에서는 뜻한 것보다 현금이 많이 남습니다.",
        ))  # fmt: skip
        return out

    def _conflict_proposals(self, req: dict[str, Any], intent: dict[str, Any], overrides: dict[str, Any]) -> list[QuestionProposal]:
        """conflicts[].idea_value 가 있고, 그 필드가 질문 가능하며, 이번 요청에서 직접 정한 값(override)이 아니고, 지금 값과 다르면 → conflict 질문."""
        from backend.analysis.m1_request.conditions import fmt as fmt_value

        askable = set(self.s.dialog.askable_fields)
        out: list[QuestionProposal] = []
        seen: set[str] = set()
        for c in (intent.get("interpretation") or {}).get("conflicts") or []:
            val = c.get("idea_value")
            if val is None:
                continue
            # field 는 "natural_language.idea / constraints.universe" 처럼 둘을 함께 적기도 한다 → 질문 가능한 경로를 고른다
            cands = [tok.strip() for tok in str(c.get("field", "")).replace("/", " ").replace(",", " ").split()]
            field = next((f for f in cands if f in askable and f != "natural_language.idea"), None)
            if not field or field in seen:
                continue
            if any(k == field or k.startswith(field + ".") or field.startswith(k + ".") for k in overrides if not k.startswith("_")):
                continue  # 이번 요청에서 직접 정한 값은 그대로 (HARD)
            cur = assemble.get_path(req, field)
            if cur == val:
                continue
            seen.add(field)
            lab = label(field)
            out.append(QuestionProposal(
                field=field, kind="conflict", priority=1,
                question_ko=f"아이디어와 프로필의 '{lab}' 이(가) 다릅니다. {c.get('issue_ko', '')} 어느 쪽으로 할까요?".replace("  ", " "),
                options=[{"value": val, "label_ko": f"아이디어대로: {fmt_value(field, val, req)}"}, {"value": cur, "label_ko": f"프로필대로: {fmt_value(field, cur, req)}"}],
                allow_free_text=False,
                why_ko="프로필 값은 저장해 둔 기본값입니다. 이번 분석에서만 바꿀 수 있고 프로필은 그대로 남습니다.",
            ))  # fmt: skip
        return out

    def _period_proposal(self, req: dict[str, Any]) -> list[QuestionProposal]:
        per = parse_period(req["natural_language"]["idea"], today=self.md.ceiling)
        if not per:
            return []
        hz = req["horizon"]
        cur_years = float(hz.get("backtest_years") or self.s.backtest.default_backtest_years)
        cur_end = str(hz.get("start_date") or "")
        want_end = per["end_date"]
        if abs(cur_years - per["years"]) < 0.6 and (cur_end[:4] == (want_end or "")[:4] or (not want_end and not cur_end)):
            return []  # 이미 그 기간이다
        label_req = f"{per['start_year']}년부터 {per['end_year']}년까지 ({per['years']:g}년)" if want_end else f"{per['start_year']}년부터 지금까지 ({per['years']:g}년)"
        value_req = {"backtest_years": per["years"], "start_date": want_end}
        value_cur = {"backtest_years": cur_years, "start_date": hz.get("start_date")}
        return [QuestionProposal(
            field="horizon", kind="conflict", priority=1,
            question_ko=f"아이디어에 적으신 기간대로 백테스트를 {label_req}로 할까요? 지금 설정은 최근 {cur_years:g}년입니다.",
            options=[{"value": value_req, "label_ko": f"아이디어대로 {label_req}"}, {"value": value_cur, "label_ko": f"지금 설정대로 최근 {cur_years:g}년"}],
            allow_free_text=False,
            why_ko="기준일(백테스트 끝)이 과거이면 그 날짜 이전 자료만으로 종목을 고릅니다. 재무 지표 자료는 미국 2009년 8월, 한국 2004년 8월부터 있어 저PER·퀄리티·고배당은 그 이후만 가능합니다.",
        )]  # fmt: skip

    def _pick_question(self, doc: AnalysisRequestDoc, proposals: list[QuestionProposal], req: dict[str, Any]) -> QuestionProposal | None:
        askable = set(self.s.dialog.askable_fields)
        asked = {q.field for q in doc.questions}
        valid: list[QuestionProposal] = []
        for p in proposals[: self.s.dialog.max_proposals_per_turn * 2]:
            if p.field not in askable or p.field in asked:
                continue
            ok_opts = []
            for o in p.options:
                if p.field == "natural_language.idea" or (o.clarification and not o.patch):
                    ok_opts.append(o)
                    continue
                trial = json.loads(json.dumps(req))
                if o.patch:
                    for k, v in o.patch.items():
                        if not k.startswith("_"):
                            assemble.set_path(trial, k, v)
                else:
                    assemble.set_path(trial, p.field, o.value)
                if not hard_errors(trial):
                    ok_opts.append(o)
            if p.options and not ok_opts and not p.allow_free_text:
                doc.warnings.append(f"question on {p.field} dropped: no valid option")
                continue
            if len(ok_opts) < 2 and not p.allow_free_text:  # 라운드 5: 보기가 하나뿐인 질문은 묻지 않는다 (고를 것이 없다)
                doc.warnings.append(f"question on {p.field} dropped: fewer than 2 valid options")
                continue
            valid.append(p.model_copy(update={"options": ok_opts}))
        if not valid:
            return None
        valid.sort(key=lambda p: (p.priority, KIND_ORDER.get(p.kind, 9)))
        return valid[0]

    # ───────────────────────── 보조 ─────────────────────────
    @staticmethod
    def _history_text(doc: AnalysisRequestDoc) -> str:
        if not doc.questions:
            return "(없음)"
        return "\n".join(f"Q{q.seq} [{q.kind}] {q.field}: {q.question_ko} → 답: {q.answer or '(대기 중)'}" for q in doc.questions)

    def _answer_message(self, doc: AnalysisRequestDoc, q: Question) -> str:
        prof = self.profiles.version(doc.profile_version)
        req = assemble.build(prof, doc.idea, overrides=doc.overrides, clarifications=doc.idea_clarifications, request_id=doc.request_id, created_at=doc.created_at)
        body = {k: req[k] for k in ("capital", "horizon", "risk", "constraints", "strategy_preference", "natural_language")}
        return (f"Q{q.seq} ({q.field}) 답: {q.answer}\n코드가 반영한 갱신된 요청:\n```json\n{json.dumps(body, ensure_ascii=False, indent=1, default=str)}\n```\n"
                "이 답을 반영해 의도 명세를 다시 출력하세요. 같은 항목은 다시 묻지 않습니다.")  # fmt: skip

    def _unresolved(self, doc: AnalysisRequestDoc) -> list[dict[str, Any]]:
        out = []
        for q in doc.questions:
            if not q.answered_at or q.skipped:
                out.append({"field": q.field, "label_ko": label(q.field), "hint_ko": q.question_ko, "examples_ko": [o.label_ko for o in q.options[:3]]})
        return out

    def state(self, doc: AnalysisRequestDoc) -> DialogState:
        current = next((q for q in doc.questions if not q.answered_at), None) if doc.dialog_state == "asking" else None
        confirmation = None
        if doc.dialog_state in ("ready", "confirmed") and doc.draft_request:
            prof = self.profiles.version(doc.profile_version)
            base_req = assemble.build(prof, doc.idea, request_id=doc.request_id, created_at=doc.created_at)
            if doc.mode == "revision" and doc.base_report_id:
                try:
                    base_req = dict(self._base(doc.base_report_id)[0].effective_request)  # 수정안은 프로필이 아니라 원안과 비교해 변경을 표시
                except (NotFound, RequestInvalid):
                    pass
            answered = {q.field: q.seq for q in doc.questions if q.applied}
            rows = condition_rows(doc.draft_request, base_req, answered_fields=answered, derived=doc.derived)
            confirmation = {"effective_request": doc.effective_request or doc.draft_request, "rows": [r.model_dump() for r in rows],
                            "all_supported": all(r.supported for r in rows)}  # fmt: skip
        it = doc.intent or {}
        summary = DialogSummary(interpretation_summary_ko=it.get("interpretation", {}).get("summary_ko"),
                                themes=[{"id": t["id"], "label_ko": t["label_ko"], "description_ko": t["description_ko"]} for t in it.get("interpretation", {}).get("themes", [])],
                                derived=doc.derived, changed_fields=sorted(k for k in doc.overrides if not k.startswith("_")))  # fmt: skip
        conditions: list[dict[str, Any]] = []
        if doc.draft_request:  # 질문 중에도 지금 조건을 보여 준다 (조건 확인 화면에서 바로 바꿀 수 있게)
            if confirmation is not None:
                conditions = confirmation["rows"]
            else:
                try:
                    prof = self.profiles.version(doc.profile_version)
                    base_req = assemble.build(prof, doc.idea, request_id=doc.request_id, created_at=doc.created_at)
                    answered = {q.field: q.seq for q in doc.questions if q.applied}
                    conditions = [r.model_dump() for r in condition_rows(doc.draft_request, base_req, answered_fields=answered, derived=doc.derived)]
                except Exception:  # noqa: BLE001 — 표는 보조 정보
                    conditions = []
        return DialogState(request_id=doc.request_id, mode=doc.mode, base_report_id=doc.base_report_id, status=doc.status, state=doc.dialog_state, turn=doc.turn,
                           max_questions=doc.max_questions, idea=doc.idea, question=current, questions=doc.questions, hard_errors=doc.hard_errors,
                           confirmation=confirmation, unresolved=self._unresolved(doc) if (doc.dialog_state == "blocked" or doc.blocked_reason_ko) else [], summary=summary,
                           revision=doc.revision, run_id=doc.run_id, warnings=doc.warnings, conditions=conditions,
                           overrides={k: v for k, v in doc.overrides.items() if not k.startswith("_")},
                           blocked_reason_ko=doc.blocked_reason_ko, precheck=doc.precheck)  # fmt: skip
