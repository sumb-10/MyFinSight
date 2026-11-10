"""M1-02 보충 질문 대화. 한 턴 = 조립 → HARD 검증 → 파생값 → 의도 해석(LLM, 질문 제안) → 코드가 질문 1개 선택.

규칙: 1회 1항목, 최대 N회(설정). HARD 오류는 질문이 아니라 즉시 수정 안내. 선택지 답은 코드가 필드에 반영하고,
자유 입력은 아이디어에 덧붙여 다음 턴의 LLM 이 해석한다. 확인(confirm) 전에는 분석을 시작하지 않는다.
같은 프로필·아이디어·답 → 같은 대화 → 같은 LLM 캐시 키 → 같은 요청 (요구 14).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
import re
from typing import Any

from backend.analysis.common.jsonio import canonical_json, now_iso, sha256_hex
from backend.analysis.common.labels import sector_counts_ko, usd_ko
from backend.analysis.common.llm import LlmClient
from backend.analysis.common.store import JsonStore, ProfileStore, RequestStore, new_request_id, new_run_id
from backend.analysis.errors import Conflict, DialogBlocked, DialogNotReady, NotFound, RequestInvalid, public_message
from backend.analysis.executor.queue import Queue
from backend.analysis.m1_request import assemble
from backend.analysis.m1_request.conditions import condition_rows
from backend.analysis.m1_request.derive import derive
from backend.analysis.m1_request.history import context_package
from backend.analysis.m1_request.precheck import precheck as run_precheck
from backend.analysis.m1_request.progress import Progress, for_request, screen_ko, themes_ko
from backend.analysis.m4_portfolio.spec import dropped_ko
from backend.analysis.m1_request.validate import hard_errors, label
from backend.analysis.m2_data import descriptor as D
from backend.analysis.m2_data.metrics import METRIC_SHORT_KO
from backend.analysis.m2_data.market_data import MarketData
from backend.analysis.m3_selection.intent import build_messages, interpret
from backend.analysis.m1_request import message_result as msg_result
from backend.analysis.m1_request import revision
from backend.analysis.schemas.dialog import AnalysisRequestDoc, ConditionRow, DialogMessage, DialogState, DialogSummary, Question, QuestionProposal, RevisionDraft
from backend.analysis.common.capacity import cap_cause_ko, cap_limits
from backend.analysis.schemas.request import UNIVERSE_MARKET
from backend.analysis.settings import AnalysisSettings
from backend.schemas.errors import MyFinSightError

log = logging.getLogger(__name__)

FIRST_TURN_FAILED_KO = "서버 오류로 해석을 마치지 못했습니다."  # 화면 제목이 「아이디어를 해석하지 못했습니다」라 이유만
# 해석 중(interpreting) 으로 마지막 진행(단계·분류 묶음, 없으면 요청을 만든 때) 뒤 이만큼 지나면 서버가 다시 시작돼 끊긴 것으로 본다.
# 단계 사이 가장 긴 일은 LLM 한 번(호출당 한도 180초, 재시도 포함)
STALE_INTERPRETING = dt.timedelta(minutes=15)
STALE_INTERPRETING_KO = "서버가 다시 시작돼 해석이 끊겼습니다."

KIND_ORDER = {"feasibility": 0, "missing": 1, "conflict": 2, "ambiguous": 3, "preference": 4}
# 답에 따라 고르는 종목 자체가 바뀌는 항목 (선정 기준·유니버스·테마·제외·필수 포함). 이 항목의 충돌(conflict)·빈 값(missing) 질문은
# 점검 결과로 만든 질문(feasibility: 섹터 상한·종목 수·시작일)보다 먼저 묻는다 — 점검은 지금 조건의 예상 선정 종목으로 계산하기 때문 (024)
SELECTION_FIELDS = frozenset({"strategy_preference.template", "constraints.universe", "natural_language.idea", "constraints.exclude_sectors",
                              "constraints.exclude_themes", "constraints.exclude_tickers", "constraints.must_include_tickers"})  # fmt: skip
# 다른 질문과 한 번에 물어도 되는 항목 (6번): 답이 종목 선정·후보 수·기간·배분 가능 비율(점검 질문의 숫자)에 영향이 없다.
# 선정 기준·종목 범위·넣을/뺄 것·아이디어·기간·종목 수·비중 상한·최소 현금은 앞 답에 따라 뒤 질문의 숫자가 바뀌어 한 턴에 하나씩 묻는다 (024)
BATCHABLE_FIELDS = frozenset({"constraints.rebalance", "strategy_preference.baseline_weighting", "strategy_preference.use_news_tilt", "risk.benchmark",
                              "risk.target_annual_return", "risk.max_drawdown_tolerance", "capital.monthly_contribution", "horizon.purpose"})  # fmt: skip


def _few_why_ko(counts: dict[str, int], stock_cap: float, sector_cap: float, cash: float) -> str:
    """후보가 모자랄 때 '그대로 진행' 하면 왜·얼마나 현금이 남는지 — 실제로 묶는 상한으로 (039: 8종목이 모두 금융이라 섹터 상한 40% 가 막는데
    '종목당 상한(10%) 때문 (예: 8종목 × 10% = 80% 투자)' 라고 해, 최소 현금 20% 를 빼면 남는 현금이 없는 것처럼 읽혔다)."""
    lim = cap_limits(counts, stock_cap, sector_cap, 1.0 - cash)
    cause = cap_cause_ko(lim, stock_cap, sector_cap, clause=True)
    if not cause:
        return f"후보 수가 최소 종목 수에 못 미치지만, 지금 상한 안에서도 투자 비율 {1 - cash:.0%}는 모두 배분할 수 있습니다."
    return f"그대로 진행하면 {cause} 현금이 {1 - lim['cap_room']:.0%}" + (f"(요청한 최소 현금 {cash:.0%} 포함)" if cash > 1e-9 else "") + " 남습니다."


def _stale(since: str) -> bool:
    """since(마지막 진행 시각 또는 요청을 만든 시각) 뒤 STALE_INTERPRETING 이 지났는지 (now_iso 는 오프셋이 붙은 지역 시각)."""
    try:
        made = dt.datetime.fromisoformat(since)
    except ValueError:
        return False
    now = dt.datetime.now(made.tzinfo) if made.tzinfo else dt.datetime.now()
    return now - made > STALE_INTERPRETING


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



def _start_why_ko(st: dict[str, Any], cons: dict[str, Any]) -> str:
    """시작일 종목이 적은 이유를 실제 사유별 수로 (049: '상장 전이거나 재무 지표가 없던 종목' 이라고 했는데 실제는 최소 시가총액이 8개를 뺐다)."""
    by = st.get("dropped_by") or {}
    if not by:
        return "과거에는 상장 전이거나 재무 지표가 없던 종목이 있어 시작일에 뽑을 수 있는 종목이 적을 수 있습니다."
    return f"분석 기준일 선정 종목 중 {sum(by.values())}개를 시작일에는 고를 수 없습니다: {dropped_ko(by, cons)}."

def _rules_collapse_to_caps(req: dict[str, Any]) -> bool:
    """목표 종목 수 × 종목당 상한이 투자 가능 비율 이하면 어느 비중 규칙이든 모든 종목이 상한(같은 비중)이 된다."""
    cons = req.get("constraints") or {}
    n = int(((cons.get("num_holdings") or {}).get("target")) or 0)
    cap = float(cons.get("max_weight_per_stock") or 1.0)
    invest = 1.0 - float(cons.get("min_cash_ratio") or 0.0)
    return n > 0 and n * cap <= invest + 1e-9


class DialogService:
    def __init__(self, store: JsonStore, repo: Any, md: MarketData, llm: LlmClient, settings: AnalysisSettings) -> None:
        self.store, self.repo, self.md, self.llm, self.s = store, repo, md, llm, settings
        self.requests = RequestStore(store)
        self.profiles = ProfileStore(store)
        self.queue = Queue(store)

    # ───────────────────────── 공개 API ─────────────────────────
    def start(self, idea: str, *, overrides: dict[str, Any] | None = None, mode: str = "new", base_report_id: str | None = None,
              language: str = "ko", profile_version: int | None = None, clarifications: list[str] | None = None, revision: RevisionDraft | None = None) -> DialogState:  # fmt: skip
        """새 요청을 만들고 첫 턴까지 이 자리에서 끝낸다 (재분석·수정 요청·테스트). 오류는 그대로 던진다.
        홈의 새 요청은 API 가 create() 로 번호를 먼저 돌려주고 run_first_turn() 을 응답 뒤에 돌린다."""
        st = self.create(idea, overrides=overrides, mode=mode, base_report_id=base_report_id, language=language,
                         profile_version=profile_version, clarifications=clarifications, revision=revision)  # fmt: skip
        return self.run_first_turn(st.request_id, reraise=True)

    def create(self, idea: str, *, overrides: dict[str, Any] | None = None, mode: str = "new", base_report_id: str | None = None,
               language: str = "ko", profile_version: int | None = None, clarifications: list[str] | None = None, revision: RevisionDraft | None = None) -> DialogState:  # fmt: skip
        """프로필·아이디어를 검사하고 요청을 '해석 중'(interpreting) 으로 바로 저장한다. LLM 은 부르지 않는다.
        해석에 수 초~1분이 걸려도 화면이 번호를 먼저 받아 그 주소로 가므로, 새로고침해도 요청을 잃지 않는다."""
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
                                 max_questions=self.s.dialog.max_questions, dialog_state="interpreting", progress=Progress().steps)  # fmt: skip  (단계는 모두 대기로 시작)
        with self.requests.locked(doc.request_id):
            self.requests.save(doc)
        return self.state(doc)

    def run_first_turn(self, request_id: str, *, reraise: bool = False) -> DialogState:
        """create() 로 저장한 요청의 첫 턴(해석·점검·첫 질문). 실패하면 failed + error_ko 로 저장한다 (reraise 면 다시 던짐).
        이미 해석 중이 아니면 아무것도 하지 않는다 (두 번 불려도 같음)."""
        with self.requests.locked(request_id):
            doc = self.requests.load(request_id)
            if doc.dialog_state != "interpreting":
                return self.state(doc)
            try:
                doc = self._turn(doc, progress=for_request(self.requests, doc))
            except Exception as e:
                if not isinstance(e, MyFinSightError):
                    log.exception("first turn failed for %s", request_id)
                failed = self.requests.load(request_id)  # _turn 이 고치다 만 문서 대신 저장된 해석 중 문서에 실패만 적는다
                failed.dialog_state = "failed"
                failed.error_ko = (public_message(e) if isinstance(e, MyFinSightError) else "") or FIRST_TURN_FAILED_KO
                self.requests.save(failed)
                if reraise:
                    raise
                return self.state(failed)
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
            self._apply_answer(doc, q, option_value, free_text)
            doc.messages.append(DialogMessage(role="user", content=self._answer_message(doc, q)))
            doc = self._turn_when_answered(doc)
            self.requests.save(doc)
        return self.state(doc)

    def answer_batch(self, request_id: str, answers: list[dict[str, Any]]) -> DialogState:
        """함께 물은 질문들에 한 번에 답한다 (6번). 답마다 보기·자유 입력·skip, 목록에 없는 질문은 답하지 않음(기본값)으로 본다 — 지금처럼 모든 질문은 선택.
        답을 모두 반영해 HARD 규칙을 함께 검사하고(부딪히면 아무것도 바꾸지 않고 422), 한 메시지로 LLM 에 알려 턴을 한 번만 돈다."""
        with self.requests.locked(request_id):
            doc = self.requests.load(request_id)
            if doc.status != "draft":
                raise Conflict(f"요청이 이미 {doc.status} 상태입니다")
            open_qs = [q for q in doc.questions if not q.answered_at]
            if not open_qs:
                raise Conflict("지금 답할 질문이 없습니다")
            by_seq = {int(a.get("seq", 0)): a for a in answers}
            unknown = sorted(set(by_seq) - {q.seq for q in open_qs})
            if unknown:
                raise RequestInvalid(f"지금 답할 수 없는 질문입니다: {', '.join(map(str, unknown))}", details={"seqs": unknown})
            trial = doc.model_copy(deep=True)
            batch = [q for q in trial.questions if not q.answered_at]
            for q in batch:
                a = by_seq.get(q.seq) or {}
                text = (a.get("free_text") or "").strip()
                if a.get("skip") or (a.get("option_value") is None and not text):
                    self._apply_skip(trial, q)
                else:
                    self._apply_answer(trial, q, a.get("option_value"), text or None)
            self._check_combined(trial, batch)
            trial.messages.append(DialogMessage(role="user", content=self._reply_message(trial, batch)))
            doc = self._turn(trial)
            self.requests.save(doc)
        return self.state(doc)

    @staticmethod
    def _apply_answer(doc: AnalysisRequestDoc, q: Question, option_value: Any, free_text: str | None) -> None:
        """답 하나를 요청에 반영 (보기 = 덮어쓰기·patch·아이디어 보충, 자유 입력 = 아이디어 보충). 턴은 돌지 않는다."""
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
            q.free_text = (free_text or "").strip()
            q.answer = q.free_text
            doc.idea_clarifications.append(f"[{label(q.field)}] {q.free_text}")
        q.answered_at = now_iso()

    @staticmethod
    def _apply_skip(doc: AnalysisRequestDoc, q: Question) -> None:
        q.skipped, q.answer, q.answered_at = True, "(답하지 않음 — 기본값 사용)", now_iso()
        if q.kind == "feasibility" and q.field == "horizon.backtest_years":  # 질문 문구대로 '답하지 않으면 시작일을 옮긴다' = 이동 동의 (정책 결정 4)
            doc.overrides["_start_shift_ok"] = True

    def _turn_when_answered(self, doc: AnalysisRequestDoc) -> AnalysisRequestDoc:
        """함께 물은 질문이 남아 있으면 턴을 미룬다 (질문 하나씩 답하는 기존 API 로 묶음에 답할 때). 모두 답했으면 다음 턴."""
        return doc if any(not q.answered_at for q in doc.questions) else self._turn(doc)

    def _check_combined(self, doc: AnalysisRequestDoc, batch: list[Question]) -> None:
        """함께 고른 답이 서로 부딪히면(예: 종목당 상한 × 최소 종목 수 < 투자 비율) 반영하지 않고 422. 보기 하나하나는 질문을 고를 때 이미 검사했다."""
        if doc.hard_errors:  # 원래 오류가 있던 요청은 질문 화면이 오류 고치기를 먼저 보여 준다 — 여기서 새로 막지 않는다
            return
        trial = doc.model_copy(deep=True)
        self._fix_num_holdings(trial, self.profiles.version(trial.profile_version))
        req = assemble.build(self.profiles.version(trial.profile_version), trial.idea, overrides=trial.overrides, clarifications=trial.idea_clarifications,
                             request_id=trial.request_id, created_at=trial.created_at, language=trial.language)  # fmt: skip
        errs = hard_errors(req)
        if not errs:
            return
        touched = lambda q: [q.field, *((q.applied or {}).get("patch") or {})]  # noqa: E731
        seqs = sorted({q.seq for q in batch if q.applied for e in errs for f in touched(q) if f.startswith(e.field) or e.field.startswith(f)})
        raise RequestInvalid("함께 고른 답이 서로 맞지 않습니다: " + "; ".join(e.message_ko for e in errs[:3]),
                             details={"seqs": seqs, "errors": [e.model_dump() for e in errs]})  # fmt: skip

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
        """질문과 상관없이 말로 조건·아이디어를 보탬. 아이디어 보충으로 붙여 다음 턴에 해석한다 (필드 값은 코드가 질문/답으로만 바꾼다).
        그 턴 전후를 비교한 결과(반영됨·반영 안 됨·확인 필요)를 message_results 에 남긴다 (GET /requests/{id}/messages, 리포트 request_log)."""
        text = (text or "").strip()
        if not text:
            raise RequestInvalid("내용을 적어 주세요", details={"fields": {"text": "비어 있음"}})
        with self.requests.locked(request_id):
            doc = self.requests.load(request_id)
            if doc.status != "draft":
                raise Conflict(f"요청이 이미 {doc.status} 상태입니다")
            before, n_asked = msg_result.snapshot(self._rows(doc), doc.intent), len(doc.questions)
            closed = [q.model_copy() for q in doc.questions if not q.answered_at]
            self._settle_pending(doc, "(말로 조건을 보태 건너뜀)")
            doc.idea_clarifications.append(f"[추가 요청] {text}")
            doc.messages.append(DialogMessage(role="user", content=f"사용자의 추가 요청: {text}\n아이디어 보충으로 반영해 의도 명세를 다시 출력하세요. 필드 값을 바꿔야 하면 그 필드를 conflict/preference 질문으로 제안하세요."))
            doc = self._turn(doc)
            asked = doc.questions[n_asked:] if doc.dialog_state == "asking" else []  # 이 턴에 생긴 질문 (함께 묻는 묶음이면 여러 개)
            capped = not asked and bool(doc.blocked_reason_ko) and len(doc.questions) >= doc.max_questions  # _turn 이 턴마다 사유를 다시 정한다
            doc.message_results.append(msg_result.judge(text, now_iso(), before, msg_result.snapshot(self._rows(doc), doc.intent),
                                                        asked=asked, closed=closed, capped=capped))  # fmt: skip
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
            self._apply_skip(doc, q)
            doc.messages.append(DialogMessage(role="user", content=self._skip_message(q)))
            doc = self._turn_when_answered(doc)
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
    def _turn(self, doc: AnalysisRequestDoc, *, progress: Progress | None = None) -> AnalysisRequestDoc:
        """한 턴. progress 는 새 요청 첫 턴만 넘긴다 (단계마다 요청 문서에 기록 → 해석 중 화면)."""
        pg = progress or Progress()
        pg.step("conditions", "running")
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
            pg.step("conditions", "done", f"고칠 조건 {len(errs)}건")
            pg.close(detail_ko="조건을 먼저 고칩니다")
            return doc
        normalized = derive(req, self.md, self.s).model_dump(mode="json")
        doc.draft_request = normalized
        doc.derived = normalized["derived"]
        pg.step("conditions", "done", f"기준일 {doc.derived['as_of']} · 백테스트 {float(normalized['horizon']['backtest_years']):g}년")
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
        pg.step("intent", "running")
        spec, warns, _msgs = interpret(normalized, desc, self.llm, self.s, messages=_dicts(doc.messages), asked_fields=asked)
        intent = spec.model_dump(mode="json")
        proposals = [QuestionProposal.model_validate(q) for q in intent.pop("questions", [])]
        # 테마와 무관한 답(종목 수·상한·기간 등)이면 테마 정의(GICS·키워드·예시 종목)와 제외 테마 규칙을 이전 턴 그대로 둔다.
        # LLM 이 턴마다 의도 전체를 다시 쓰며 GICS 코드를 바꿔(004: '2510' 이 빠짐) 점검 후보가 4 → 3 이 됐고, '4개로 줄임' 답이 틀린 숫자 위에 남았다.
        # 아이디어·보탠 말(테마 넓히기·자유 입력 포함)·제외 테마·유니버스가 바뀌었을 때만 새 테마를 받는다.
        basis = sha256_hex(canonical_json({"idea": doc.idea, "cl": list(doc.idea_clarifications), "ex": req["constraints"].get("exclude_themes") or [],
                                           "u": req["constraints"].get("universe") or []}), 12)  # fmt: skip
        if doc.intent and doc.overrides.get("_theme_basis") == basis:
            intent["interpretation"]["themes"] = doc.intent["interpretation"]["themes"]
            intent["exclude_theme_rules"] = doc.intent.get("exclude_theme_rules", [])
        doc.overrides["_theme_basis"] = basis
        doc.intent = intent
        pg.step("intent", "done", themes_ko(intent))
        doc.messages.append(DialogMessage(role="assistant", content=json.dumps({**intent, "questions": [p.model_dump() for p in proposals]}, ensure_ascii=False)))
        doc.warnings = list(warns)
        try:  # 실행 전 점검 (LLM 없음): 후보 수·지표 보유 수를 기준일·백테스트 시작일에서 센다 (서명이 같으면 재사용)
            btr = (doc.overrides.get("_backtest_request") or {}).get("backtest") or {}
            doc.precheck = run_precheck(normalized, intent, desc, self.md, self.s, previous=doc.precheck, llm=self.llm,
                                        reselect=btr.get("reselect_at_start", True) is not False and not doc.overrides.get("_no_reselect"),
                                        progress=pg.step)  # fmt: skip  (재선정을 껐으면 시작일 부족을 묻지 않는다, F24·054)
        except Exception as e:  # noqa: BLE001 — 점검은 보조 정보
            doc.precheck = None
            doc.warnings.append(f"precheck skipped: {e}")
            pg.close(("retrieve", "classify", "screen"), "점검하지 못해 건너뜀")
        else:
            pg.step("screen", "done", screen_ko(doc.precheck))
        pg.step("question", "running")
        proposals = self._code_proposals(req, intent, desc, overrides=doc.overrides, precheck=doc.precheck) + proposals  # 코드 규칙 질문이 LLM 제안보다 앞
        to_ask = self._pick_questions(doc, proposals, req)  # 첫 질문 + 함께 물어도 되는 질문 (6번)
        picked = to_ask[: max(0, doc.max_questions - len(doc.questions))]
        chosen = to_ask[0] if to_ask else None
        pg.step("question", "done", "더 물을 것 없음" if not picked else " · ".join(f"「{label(p.field)}」" for p in picked) + " 묻기")
        if chosen is None:
            doc.dialog_state = "ready"
            doc.blocked_reason_ko = None
        elif not picked:
            # 질문 상한 (라운드 5): 막지 않고 남은 항목을 기본값(지금 조건)으로 두어 바로 확정할 수 있게 한다. 사유는 blocked_reason_ko 로 보여 준다
            doc.dialog_state = "ready"
            doc.blocked_reason_ko = (f"보충 질문 {doc.max_questions}회를 모두 써서 남은 항목은 지금 조건(기본값) 그대로 둡니다: "
                                     + ", ".join(label(p.field) for p in proposals[:3]) + ". 바꾸려면 '조건 바꾸기'나 '말로 조건 보태기'를 쓰세요.")  # fmt: skip
        else:
            doc.blocked_reason_ko = None
            now, batch = now_iso(), len(doc.questions) + 1
            for p in picked:
                doc.questions.append(Question(**p.model_dump(), seq=len(doc.questions) + 1, asked_at=now, field_label_ko=label(p.field), batch=batch))
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

        now = precheck.get("as_of") or {}

        def shrink_patch(n: int, counts: dict[str, int] | None = None) -> dict[str, Any]:
            cap = max(stock_cap, min(1.0, math.ceil((1.0 - cash) / n * 100) / 100))
            # '전액 투자' 가 참이 되게 섹터 상한도: 예상 선정 종목의 섹터 구성(점검)으로 투자 비율을 다 담는 가장 작은 섹터 상한 (F26: 한 섹터 테마면
            # 종목당 상한만 올려서는 섹터 상한에 걸려 현금이 남고, 같은 문제를 섹터 상한 질문으로 다시 물었다)
            sec_cap = max(sector_cap, cap)
            ks = list((counts or {}).values())
            if ks and sum(ks) == n:
                need = next((c / 100 for c in range(int(sec_cap * 100), 101) if sum(min(k * cap, c / 100) for k in ks) >= (1.0 - cash) - 1e-9), 1.0)
                sec_cap = max(sec_cap, need)
            return {"constraints.num_holdings": {"target": n, "min": n, "max": n}, "constraints.max_weight_per_stock": cap,
                    "constraints.max_weight_per_sector": round(sec_cap, 2)}  # fmt: skip

        def ups_ko(sp: dict[str, Any]) -> list[str]:
            """보기가 실제로 올리는 상한 (012: 이미 15% 인 종목당 상한을 '15%로 올려' 라고 썼다, 048: 시작일 보기가 섹터 상한 40% → 50% 를 말없이 올렸다)."""
            cap, scap = sp["constraints.max_weight_per_stock"], sp["constraints.max_weight_per_sector"]
            return [f"종목당 상한 {cap:.0%}" for _ in [0] if cap > stock_cap + 1e-9] + [f"섹터당 상한 {scap:.0%}" for _ in [0] if scap > sector_cap + 1e-9]

        def mcap_note(summ: dict[str, Any]) -> str:
            """사용자가 정한 최소 시가총액·최소 거래대금이 테마 관련 종목을 얼마나 뺐는지 (048: 61개 중 45개가 500억 달러 미만이었는데 질문은 테마 넓히기만 권했다,
            052: 12개 중 6개가 거래대금으로 빠졌는데 시가총액 2개만 적었다)."""
            bf = summ.get("by_filter") or {}
            parts = []
            for key, lab in (("min_avg_daily_volume_usd", "최근 거래대금이 최소 거래대금"), ("min_market_cap_usd", "시가총액이 최소 시가총액")):
                k = int(bf.get(key) or 0)
                if k > 0 and float(cons.get(key) or 0) > 0:
                    parts.append((k, f"{k}개는 {lab}({usd_ko(cons.get(key))})에 못 미쳐"))
            k_mc = int(bf.get("market_cap_missing") or 0)  # 시가총액 자료가 없어 최소 시가총액을 확인할 수 없는 종목 (057: KB금융이 빠진 이유가 질문에 없었다)
            if k_mc > 0 and float(cons.get("min_market_cap_usd") or 0) > 0:
                parts.append((k_mc, f"{k_mc}개는 시가총액 자료가 없어"))
            k_kw = int(bf.get("keyword_weak") or 0)  # 테마 키워드가 약하게만 맞아 후보에서 뺀 종목도 센다 (079: 10개 중 3+1 개만 적어 5개가 남는 계산이 맞지 않았다 — 메리츠금융지주)
            if k_kw > 0 and parts:
                parts.append((k_kw, f"{k_kw}개는 테마 키워드가 약하게만 맞아"))
            if not parts:
                return ""
            parts.sort(key=lambda x: -x[0])
            return f" 테마 관련 종목 {summ.get('n_matched')}개 중 " + ", ".join(p for _, p in parts) + " 빠졌습니다."

        n_now = int(min(now.get("n_with_metric", 0), now.get("n_candidates", 0)))
        if precheck.get("short_now") and "_ack_few_candidates" not in overrides:
            opts = []
            if n_now >= 2:
                sp = shrink_patch(n_now, now.get("sector_counts"))
                ups = ups_ko(sp)
                lab = f"종목 수를 {n_now}개로 줄이고" + (f" {'·'.join(ups)}로 올려" if ups else "") + f" 투자 비율 {1 - cash:.0%}를 모두 배분"
                # 백테스트 시작일 구성도 그 상한으로 다 담기는지 — 아니면 보기에 적는다 (074: '…85%를 모두 배분' 을 골랐는데 시작일 7종목 × 10% = 70%; Q-278 과 같은 문제)
                st_counts = {k: int(v) for k, v in (((precheck.get("start") or {}).get("sector_counts")) or {}).items()}
                if st_counts:
                    st_at = min(1.0 - cash, sum(min(k * sp["constraints.max_weight_per_stock"], sp["constraints.max_weight_per_sector"]) for k in st_counts.values()))
                    if st_at < (1.0 - cash) - 0.005:
                        lab += f" (백테스트 시작일 구성은 {st_at:.0%}까지만)"
                opts.append({"value": f"shrink_{n_now}", "label_ko": lab, "patch": sp})
            opts.append({"value": "widen_theme", "label_ko": "테마를 넓혀 다시 해석 (인접 산업 포함)",
                         "clarification": f"[테마 넓히기] 테마에 맞는 후보가 {n_now}개뿐이라 인접 산업·관련 업종까지 넓혀 해석해 주세요"})
            # 지금 상한으로 다 담기면 현금이 남지 않는다 — 보기 문구가 같은 질문의 설명과 어긋났다 (059: '100% 모두 배분할 수 있습니다' 인데 '현금이 남을 수 있음')
            full = cap_limits(now.get("sector_counts") or {"": max(n_now, 1)}, stock_cap, sector_cap, 1.0 - cash).get("kind") is None
            opts.append({"value": "proceed", "label_ko": "그대로 진행 (종목 수만 최소보다 적음)" if full else "그대로 진행 (현금이 남을 수 있음)", "patch": {"_ack_few_candidates": True}})
            out.append(QuestionProposal(
                field="constraints.num_holdings", kind="feasibility", priority=1,
                question_ko=(f"분석 기준일에 선정할 수 있는 종목(테마·선정 기준 통과, 필수 포함 포함)이 {n_now}개로, 최소 종목 수 {nh_min}개(목표 {nh['target']}개)에 못 미칩니다. 어떻게 할까요?"),
                options=opts, allow_free_text=False,
                why_ko=_few_why_ko(now.get("sector_counts") or {"": max(n_now, 1)}, stock_cap, sector_cap, cash) + mcap_note(now),
            ))  # fmt: skip
            return out  # 후보 부족이 먼저 — 창 축소 질문은 이게 풀린 뒤에
        st = precheck.get("start") or {}
        n_start = int(min(st.get("n_with_metric", 0), st.get("n_candidates", 0)))
        if precheck.get("start_impossible") and "_no_reselect" not in overrides:
            # 시작일 종목이 1개 이하이고 창 안에서 2종목 이상이 되는 날도 없으면 07 이 멈춘다 → 실행 전에 대안을 묻는다
            # (054: 2022~2023 국내 은행 PER 자료가 없어 질문 없이 실행했다가 07 에서 실패. 사용자 결정: 실행할 수 없으면 대안을 제시)
            metric = METRIC_SHORT_KO.get(str(st.get("metric") or ""), "선정 지표")
            out.append(QuestionProposal(
                field="horizon.backtest_years", kind="feasibility", priority=1,
                question_ko=(f"백테스트 시작일({st.get('date')})에 선정할 수 있는 종목이 {n_start}개이고, 시작일을 옮겨도 2종목 이상을 고를 수 있는 날이 없습니다. "
                             "답하지 않으면 실행이 멈춥니다. 어떻게 할까요?"),
                options=[{"value": "no_reselect", "label_ko": f"지금 선정 목록({int(now.get('n_selected') or 0)}종목)으로 과거를 평가 — 시작일에 다시 고르지 않음 "
                                                              "(지금 정보로 고른 목록이라 과거 성과가 실제보다 좋게 보일 수 있음)", "patch": {"_no_reselect": True}},
                         {"value": "change_metric", "label_ko": "선정 기준을 바꿔 다시 해석",
                          "clarification": f"[선정 기준 바꾸기] 백테스트 시작일({st.get('date')})에 {metric} 자료가 있는 종목이 없어 과거를 평가할 수 없습니다. 과거 자료가 있는 다른 선정 기준으로 해석해 주세요"}],
                allow_free_text=False, why_ko=_start_why_ko(st, cons),
            ))  # fmt: skip
            return out
        if precheck.get("short_at_start") and not precheck.get("short_now") and "_allow_fewer_at_start" not in overrides and "_no_reselect" not in overrides:  # 기준일부터 부족하면 위 질문이 다룬다 (07 도 옮기지 않음)
            opts = []
            if n_start >= 2:
                # 종목이 적으면 종목·섹터 상한 때문에 백테스트 내내 현금이 남는다 → 고르기 전에 보이게 (002: '기간 유지' 를 골라 현금 50% 로 평가됐는데 질문에는 없었다)
                cap_st = st.get("capacity")
                cash_note = (f" — 상한 때문에 백테스트에서는 투자금의 {float(cap_st):.0%}만 투자" if cap_st is not None and float(cap_st) < (1.0 - cash) - 0.005 else "")
                # 옮겨도 최소 종목 수를 못 채우면 그 사실도 실행에 넘긴다 — 리포트가 '다른 기간을 검토' 를 권하지 않게 (051)
                fs0 = precheck.get("feasible_start")
                opts.append({"value": "keep_window", "label_ko": f"백테스트 기간을 유지하고 시작 때 선정 가능한 {n_start}종목으로 평가{cash_note}",
                             "patch": {"_allow_fewer_at_start": True, **({} if fs0 else {"_shift_cannot_help": True})}})
            fs = precheck.get("feasible_start")
            if fs and float(fs.get("years") or 0) >= 1.0:
                opts.append({"value": f"shorten_{fs['years']}", "label_ko": f"백테스트 기간을 {fs['years']:g}년으로 줄임 ({fs['date']}부터는 {fs['n_with_metric']}종목)",
                             "patch": {"horizon.backtest_years": float(fs["years"])}})
            if n_start >= 2:
                sp = shrink_patch(n_start, (st.get("sector_counts") or None))
                ups = ups_ko(sp)
                opts.append({"value": f"shrink_{n_start}", "label_ko": f"종목 수를 {n_start}개로 줄여 처음부터 끝까지 같은 종목 수로" + (f" ({'·'.join(ups)}로 올림)" if ups else ""), "patch": sp})
            if fs:
                tail = f"답하지 않으면 시작일을 {fs['date']}로 옮겨 평가 기간이 {fs['years']:g}년으로 짧아집니다."
            elif n_start <= 1:
                tail = "답하지 않아도 시작 종목이 1개 이하라 2종목 이상이 되는 날로 시작일을 자동으로 옮깁니다."
            else:
                tail = f"시작일을 옮겨도 최소 종목 수를 채울 수 없어, 답하지 않으면 {n_start}종목으로 시작합니다."
            if len(opts) >= 2:
                out.append(QuestionProposal(
                    field="horizon.backtest_years", kind="feasibility", priority=1,
                    question_ko=(f"백테스트 시작일({st.get('date')})에 선정할 수 있는 종목이 {n_start}개로 최소 {nh_min}개에 못 미칩니다. {tail} 어떻게 할까요?"),
                    options=opts, allow_free_text=False,
                    why_ko=_start_why_ko(st, cons),
                ))  # fmt: skip
        return out

    def _code_proposals(self, req: dict[str, Any], intent: dict[str, Any], desc: Any, *, overrides: dict[str, Any] | None = None,
                        precheck: dict[str, Any] | None = None) -> list[QuestionProposal]:  # fmt: skip
        """LLM 이 아니라 코드가 만드는 질문 세 가지.
        1) 아이디어에 적힌 과거 기간("2005년부터 약 12년간", "2006년 ~ 2016년까지") 이 지금 백테스트 창과 다르면 기간을 묻는다.
        2) LLM 이 `conflicts` 에 적은 "아이디어 ↔ 프로필 기본값" 충돌(idea_value 있음)은 사용자가 고르게 질문으로 바꾼다 (자연어가 프로필 기본값을 이길 수 있게).
        3) 테마가 한 GICS 섹터에 몰려 있는데 섹터 상한 < 투자 비율이면 현금이 남는다는 사실을 알리고 "풀까요 / 유지할까요" 를 묻는다."""
        # 배분 가능 비율(섹터 상한) 질문을 시작일 질문보다 먼저 둔다: 상한을 바꾸면 시작일 구성의 투자 비율도 바뀌어, 먼저 물은
        # '기간 유지 — 백테스트에서는 투자금의 60%만 투자' 안내가 다음 답(섹터 상한 90%)으로 틀어졌다 (010). 종목 수 부족 질문이 있으면 그 보기가 상한까지 다룬다.
        cap_q = self._sector_cap_proposals(req, intent, desc, precheck) if self.s.dialog.ask_sector_cap_conflict else []
        return cap_q + self._feasibility_proposals(req, precheck, overrides or {}) + self._period_proposal(req) + self._conflict_proposals(req, intent, overrides or {})

    def _sector_cap_proposals(self, req: dict[str, Any], intent: dict[str, Any], desc: Any, precheck: dict[str, Any] | None) -> list[QuestionProposal]:
        """섹터 상한 때문에 투자 비율을 다 배분하지 못하면 '올릴까요 / 유지할까요' (F25: 점검의 예상 선정 종목으로 계산)."""
        out: list[QuestionProposal] = []
        cons = req["constraints"]
        cap = float(cons.get("max_weight_per_sector", 1.0))
        invest = 1.0 - float(cons.get("min_cash_ratio", 0.0) or 0.0)
        now = (precheck or {}).get("as_of") or {}
        if now.get("capacity") is not None and (precheck or {}).get("basis") == "after_classification":
            # 점검의 예상 선정 종목으로 배분 가능 비율을 계산 (예전: 테마 GICS 섹터가 정확히 1개일 때만 물어 002 처럼 두 테마가 모두
            # 산업재로 몰려 현금이 65% 남아도 묻지 않았다, F25). 종목 수 부족 질문이 먼저면(그 보기가 섹터 상한까지 다룸) 미룬다.
            if (precheck or {}).get("short_now") or float(now["capacity"]) >= invest - 0.005 or cap >= invest - 1e-9:
                return out
            counts = {k: int(v) for k, v in (now.get("sector_counts") or {}).items()}
            need = now.get("cap_needed") or round(invest, 2)
            mix = sector_counts_ko(counts)  # 한국어 질문에 GICS 영어 이름(Industrials)을 쓰지 않는다
            cash_left = 1 - float(now["capacity"])
            # 백테스트 시작일 구성은 섹터 구성이 달라 같은 상한으로도 다 못 담을 수 있다 — 보기에 그 사실을 적고, 시작일까지 다 담는 상한도 보기로
            # (070: '섹터 상한 45% 로 올려 투자 비율 90% 를 모두 배분' 을 골랐는데 2023 년 시작일 목록은 정보기술 18개라 75% 만 투자됐다 — 60% 가 필요했다)
            st = (precheck or {}).get("start") or {}
            st_counts = {k: int(v) for k, v in (st.get("sector_counts") or {}).items()}
            stock_cap = float(cons.get("max_weight_per_stock", 1.0))
            st_at = min(invest, sum(min(k * stock_cap, float(need)) for k in st_counts.values())) if st_counts else None
            short_start = st_at is not None and st_at < invest - 0.005
            st_need = st.get("cap_needed")
            options = [{"value": float(need), "label_ko": f"이번 분석에서는 섹터 상한을 {float(need):.0%}로 올려 투자 비율 {invest:.0%}를 모두 배분"
                        + (f" (백테스트 시작일 구성은 {st_at:.0%}까지만)" if short_start else "")}]  # fmt: skip
            if short_start and st_need and float(need) + 1e-9 < float(st_need) <= 1.0 + 1e-9:
                options.append({"value": float(st_need), "label_ko": f"섹터 상한을 {float(st_need):.0%}로 올려 백테스트 시작일 구성까지 투자 비율 {invest:.0%}를 모두 배분"})
            options.append({"value": cap, "label_ko": f"섹터 상한 {cap:.0%} 유지 (현금 {cash_left:.0%})"})
            out.append(QuestionProposal(  # 배분 가능 비율 부족 = 실행 가능성 문제 → 'feasibility' (시작일 질문보다 먼저 정렬되게, 010)
                field="constraints.max_weight_per_sector", kind="feasibility", priority=1,
                question_ko=(f"예상 선정 종목 {now.get('n_selected')}개가 {mix}로 몰려 있어 섹터당 상한 {cap:.0%}로는 {float(now['capacity']):.0%}만 투자되고 "
                             f"현금이 {cash_left:.0%} 남습니다" + (f"(최소 현금 {1 - invest:.0%} 포함)" if invest < 1 - 1e-9 else "") + ". 어떻게 할까요?"),
                options=options,
                allow_free_text=False,
                why_ko="섹터 상한은 여러 업종에 나눌 때 쓰는 보호 장치라, 한 업종에 몰린 테마에서는 뜻한 것보다 현금이 많이 남습니다.",
            ))  # fmt: skip
            return out
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
            if field == "strategy_preference.baseline_weighting" and _rules_collapse_to_caps(req):
                continue  # 모든 비중 규칙이 종목당 상한으로 같은 비중이 되면 기준 비중 방식은 결과를 바꾸지 못한다 (079: 5종목 × 18% = 90% 인데 동일비중·역변동성을 물었다)
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
        # 자료가 시작되기 전 기간은 실행 단계(derive)가 옮기거나 거부한다 → 보기도 같은 규칙으로 (검토: 시가총액 하드 조건 뒤 실행할 수 없는 기간을 보기로 냈다)
        mk = sorted({UNIVERSE_MARKET[u] for u in req["constraints"]["universe"]})
        floors = [self.s.market.mcap_data_start[m] for m in mk if m in self.s.market.mcap_data_start] if (req["constraints"].get("min_market_cap_usd") or 0) > 0 else []
        if req["strategy_preference"].get("template") in self.s.market.valuation_templates:
            floors += [self.s.market.valuation_data_start[m] for m in mk if m in self.s.market.valuation_data_start]
        floor = dt.date.fromisoformat(max(floors)) if floors else None
        end = dt.date.fromisoformat(want_end) if want_end else self.md.ceiling
        if floor and end < floor:
            return []  # 아이디어대로 하면 기준일이 자료 시작 전이라 실행할 수 없다 → 묻지 않는다
        start = end - dt.timedelta(days=int(round(per["years"] * 365.25)))
        if floor and start < floor:  # 실제로 평가되는 기간을 보기에 적는다
            label_req += f" — 자료가 {floor} 부터라 실제 평가는 약 {(end - floor).days / 365.25:.1f}년"
        value_req = {"backtest_years": per["years"], "start_date": want_end}
        value_cur = {"backtest_years": cur_years, "start_date": hz.get("start_date")}
        vs, ms = self.s.market.valuation_data_start, self.s.market.mcap_data_start
        return [QuestionProposal(
            field="horizon", kind="conflict", priority=1,
            question_ko=f"아이디어에 적으신 기간대로 백테스트를 {label_req}로 할까요? 지금 설정은 최근 {cur_years:g}년입니다.",
            options=[{"value": value_req, "label_ko": f"아이디어대로 {label_req}"}, {"value": value_cur, "label_ko": f"지금 설정대로 최근 {cur_years:g}년"}],
            allow_free_text=False,
            why_ko=(f"기준일(백테스트 끝)이 과거이면 그 날짜 이전 자료만으로 종목을 고릅니다. 재무 지표 자료는 미국 {vs.get('US')}, 한국 {vs.get('KR')} 부터 충분해 저PER·퀄리티·고배당은 그 이후만, "
                    f"최소 시가총액 조건은 시가총액 자료가 충분한 미국 {ms.get('US')}, 한국 {ms.get('KR')} 이후만 평가할 수 있습니다."),
        )]  # fmt: skip

    def _pick_question(self, doc: AnalysisRequestDoc, proposals: list[QuestionProposal], req: dict[str, Any]) -> QuestionProposal | None:
        """이번 턴에 가장 먼저 물을 질문 하나."""
        return next(iter(self._pick_questions(doc, proposals, req)), None)

    def _pick_questions(self, doc: AnalysisRequestDoc, proposals: list[QuestionProposal], req: dict[str, Any]) -> list[QuestionProposal]:
        """이번 턴에 물을 질문들: 가장 급한 질문 하나(예전 규칙 그대로) + 그와 함께 물어도 되는 질문 (6번, 최대 settings.dialog.max_batch_questions 개).
        함께 묻는 질문은 답이 종목 선정·후보 수·배분 가능 비율에 영향이 없는 항목(BATCHABLE_FIELDS)만 — 앞 답이 뒤 질문의 숫자를 바꾸면 안 된다 (024).
        첫 질문이 점검 질문이거나 보기가 여러 조건을 함께 바꾸면(patch) 혼자 묻는다 (화면이 그 질문에 바뀌는 조건·점검 숫자를 따로 보여 준다)."""
        askable = set(self.s.dialog.askable_fields)
        asked = {q.field for q in doc.questions}
        asked_text = {(q.field, q.question_ko) for q in doc.questions}
        valid: list[QuestionProposal] = []
        for p in proposals[: self.s.dialog.max_proposals_per_turn * 2]:
            if p.field not in askable:
                continue
            # 실행 전 점검 질문은 다른 답 때문에 숫자가 바뀌었으면 다시 묻는다 — 같은 문장은 다시 묻지 않는다
            # (064: 종목 수를 18개로 줄인 뒤 선정 기준을 고배당으로 바꿔 15개만 남았는데, 같은 필드라 묻지 않아 18개 요청에 15종목으로 실행)
            if p.field in asked and not (p.kind == "feasibility" and (p.field, p.question_ko) not in asked_text):
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
            # 라운드 5: 보기가 하나뿐인 질문은 묻지 않는다 (고를 것이 없다). 자유 입력이 열려 있어도, 원래 보기가 2개 이상이었는데
            # 규칙 검사로 하나만 남았다면 버린다 — 예: '배당 성장 우선' 처럼 지원하지 않는 값이 빠지고 '프로필 기준 유지' 하나만 남은 질문(000)
            if len(ok_opts) < 2 and (not p.allow_free_text or len(p.options) >= 2):
                doc.warnings.append(f"question on {p.field} dropped: fewer than 2 valid options")
                continue
            if len(ok_opts) == 1 and p.field != "natural_language.idea":  # LLM 이 처음부터 보기 1개를 낸 경우도 고를 것이 없다
                doc.warnings.append(f"question on {p.field} dropped: a single option")
                continue
            valid.append(p.model_copy(update={"options": ok_opts}))
        if not valid:
            return []
        valid.sort(key=lambda p: (p.priority, KIND_ORDER.get(p.kind, 9)))
        # 점검 질문이 첫 순서여도 고르는 종목을 바꾸는 충돌이 남아 있으면 그것을 먼저 묻는다 (우선순위와 관계없이). 점검 질문은 다음 턴에 확정된 기준으로 다시 계산된다
        # (024: 저변동성 기준 예상 종목 '유틸리티 7개, 부동산 3개' 로 섹터 상한을 물은 뒤 '아이디어대로: 고배당' 을 골라 부동산 8개·유틸리티 2개가 됐다. 029·032 도 같은 순서)
        first = valid[0]
        if first.kind == "feasibility":
            first = next((p for p in valid if p.kind in ("conflict", "missing") and p.field in SELECTION_FIELDS), valid[0])
        out = [first]
        if first.kind == "feasibility" or any(o.patch for o in first.options):
            return out
        for p in valid:
            if len(out) >= self.s.dialog.max_batch_questions:
                break
            if p is first or p.field not in BATCHABLE_FIELDS or p.kind == "feasibility" or any(o.patch for o in p.options):
                continue
            if any(p.field == q.field or p.field.startswith(q.field + ".") or q.field.startswith(p.field + ".") for q in out):
                continue
            out.append(p)
        return out

    # ───────────────────────── 보조 ─────────────────────────
    @staticmethod
    def _history_text(doc: AnalysisRequestDoc) -> str:
        if not doc.questions:
            return "(없음)"
        return "\n".join(f"Q{q.seq} [{q.kind}] {q.field}: {q.question_ko} → 답: {q.answer or '(대기 중)'}" for q in doc.questions)

    def _answer_message(self, doc: AnalysisRequestDoc, q: Question) -> str:
        return (f"Q{q.seq} ({q.field}) 답: {q.answer}\n코드가 반영한 갱신된 요청:\n```json\n{self._request_json(doc)}\n```\n"
                "이 답을 반영해 의도 명세를 다시 출력하세요. 같은 항목은 다시 묻지 않습니다.")  # fmt: skip

    @staticmethod
    def _skip_message(q: Question) -> str:
        return f"Q{q.seq} ({q.field}) 답: 답하지 않음. 기본값/현재 값을 그대로 쓰고 이 항목은 다시 묻지 마세요."

    def _reply_message(self, doc: AnalysisRequestDoc, batch: list[Question]) -> str:
        """한 번에 보낸 답들을 LLM 에 알리는 메시지 하나 (질문이 하나면 하나씩 답할 때와 같은 문장)."""
        if len(batch) == 1:
            return self._skip_message(batch[0]) if batch[0].skipped else self._answer_message(doc, batch[0])
        lines = [f"- Q{q.seq} ({q.field}) 답: " + ("답하지 않음 (기본값/현재 값을 그대로 쓰고 다시 묻지 않음)" if q.skipped else str(q.answer)) for q in batch]
        return (f"사용자가 질문 {len(batch)}개에 한 번에 답했습니다:\n" + "\n".join(lines) + f"\n코드가 반영한 갱신된 요청:\n```json\n{self._request_json(doc)}\n```\n"
                "이 답들을 반영해 의도 명세를 다시 출력하세요. 같은 항목은 다시 묻지 않습니다.")  # fmt: skip

    def _request_json(self, doc: AnalysisRequestDoc) -> str:
        prof = self.profiles.version(doc.profile_version)
        req = assemble.build(prof, doc.idea, overrides=doc.overrides, clarifications=doc.idea_clarifications, request_id=doc.request_id, created_at=doc.created_at)
        body = {k: req[k] for k in ("capital", "horizon", "risk", "constraints", "strategy_preference", "natural_language")}
        return json.dumps(body, ensure_ascii=False, indent=1, default=str)

    def _rows(self, doc: AnalysisRequestDoc) -> list[ConditionRow]:
        """「말로 보태기」 전후 비교용 조건 표 (기본 투자조건과 비교, state() 의 질문 중 표와 같은 방법). 만들지 못하면 빈 표 (보조 정보).
        state() 의 표 코드와 합치지 않았다 — 종목 이름 묶음(PR 16)이 그 줄을 고쳐 PR 끼리 충돌하지 않게. 둘 다 들어간 뒤 합친다."""
        if not doc.draft_request:
            return []
        try:
            prof = self.profiles.version(doc.profile_version)
            base_req = assemble.build(prof, doc.idea, request_id=doc.request_id, created_at=doc.created_at)
            answered = {q.field: q.seq for q in doc.questions if q.applied}
            return condition_rows(doc.draft_request, base_req, answered_fields=answered, derived=doc.derived)
        except Exception:  # noqa: BLE001 — 표는 보조 정보
            return []

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
        state, error_ko = doc.dialog_state, doc.error_ko
        if state == "interpreting" and _stale(doc.progress_updated_at or doc.created_at):  # 해석하던 서버가 다시 시작돼 끊김 (저장은 하지 않는다: 잠금 없이, 서버 여러 개여도 같은 판정)
            state, error_ko = "failed", STALE_INTERPRETING_KO
        return DialogState(request_id=doc.request_id, mode=doc.mode, base_report_id=doc.base_report_id, status=doc.status, state=state, turn=doc.turn,
                           max_questions=doc.max_questions, idea=doc.idea, question=current, questions=doc.questions, hard_errors=doc.hard_errors,
                           confirmation=confirmation, unresolved=self._unresolved(doc) if (doc.dialog_state == "blocked" or doc.blocked_reason_ko) else [], summary=summary,
                           revision=doc.revision, run_id=doc.run_id, warnings=doc.warnings, conditions=conditions,
                           overrides={k: v for k, v in doc.overrides.items() if not k.startswith("_")},
                           blocked_reason_ko=doc.blocked_reason_ko, precheck=doc.precheck, error_ko=error_ko, progress=doc.progress)  # fmt: skip
