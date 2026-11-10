import { useEffect, useState } from "react"
import { AlertCircle, ArrowLeft, Check, Loader2 } from "lucide-react"
import { useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { errorMessage } from "../../api/client"
import type { ConditionRow, DialogState, ProgressStep, Question } from "../../api/types"
import { saveUi } from "../../state/uiStorage"
import { Alert, Badge, Button } from "../../ui"
import { ko } from "../../lib/format"
import { Part, PartDisclosure } from "../profile/parts"
import { MockTag } from "../report/proposedView"

/** 종목 목록 조건: 목업에서는 「회사명 (티커)」로 보인다 (제안 표기, 일반 모드는 서버 문장 그대로 · MockTag 도 목업에서만 보인다). */
const isTickerField = (f: string) => /_tickers$/.test(f)

// 새 분석 · 조건 확인 화면(질문 화면 ClarifyScreen · 최종 확인 화면 ConfirmScreen) 공용 부품.
// 카드·접기 모양은 '내 투자조건' 화면의 Part/PartDisclosure 를 그대로 가져다 쓴다 (그 파일은 고치지 않는다).
// 값과 변경 여부는 서버가 만든 ConditionRow(value_ko·profile_value_ko·changed) 를 그대로 쓰고, 화면에서 새로 계산하지 않는다.

/** 제목 + 짧은 설명 + 오른쪽 버튼. 좁은 화면에서는 버튼을 제목 아래로 내린다 (내 투자조건 저장 화면과 같은 머리). */
/** titleAction = 제목 바로 옆에 붙는 작은 버튼 (예: 이름 바꾸기 연필, 리포트 상세 제목과 같은 모양). */
export function FlowHeader({ eyebrow, title, titleAction, desc, action }: { eyebrow: string; title: string; titleAction?: React.ReactNode; desc?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between sm:gap-8">
      <div className="min-w-0 max-w-3xl">
        <p className="mb-2 text-xs font-bold tracking-widest text-blue-700">{eyebrow}</p>
        {titleAction ? (
          <div className="flex items-start gap-1"><h1 className="break-words text-3xl font-bold tracking-tight text-slate-950">{title}</h1>{titleAction}</div>
        ) : (
          <h1 className="text-3xl font-bold tracking-tight text-slate-950">{title}</h1>
        )}
        {desc && <p className="mt-2 text-sm leading-6 text-slate-600">{desc}</p>}
      </div>
      {action && <div className="flex shrink-0 gap-2">{action}</div>}
    </header>
  )
}

/** App 의 main(overflow-x-auto)은 세로로도 스크롤 컨테이너가 되어, 그 안의 sticky 가 창 스크롤에 붙지 않는다.
 *  sticky 를 쓰는 화면(확인 화면 「분석 시작」 줄, 진행 화면 오른쪽 열)에 있는 동안만 clip 으로 바꾸고 나갈 때 되돌린다. */
export function useStickyInMain() {
  useEffect(() => {
    const main = document.querySelector("main")
    if (!main) return
    main.style.overflowX = "clip"
    return () => { main.style.overflowX = "" }
  }, [])
}

const FLOW = ["추가 질문 답하기", "조건 최종 확인", "분석 시작"]

/** 지금 어느 단계인지 (내 투자조건의 단계 카드와 같은 모양, 누르는 기능은 없다). */
export function FlowSteps({ current }: { current: 0 | 1 }) {
  return (
    <nav aria-label="분석 준비 단계">
      <ol className="grid grid-cols-3 gap-2 sm:gap-3">
        {FLOW.map((label, i) => {
          const now = i === current, done = i < current
          return (
            <li key={label} aria-current={now ? "step" : undefined} className={`rounded-xl border p-3 ${now ? "border-blue-400 bg-blue-50 ring-1 ring-blue-200" : done ? "border-slate-200 bg-white" : "border-dashed border-slate-200 bg-white"}`}>
              <span className="flex items-center justify-between">
                <span className={`text-xs font-bold ${now ? "text-blue-700" : "text-slate-400"}`}>0{i + 1}</span>
                {done && <Check className="size-4 text-emerald-600" aria-hidden="true" />}
              </span>
              <span className={`mt-1 block text-sm font-semibold ${now || done ? "text-slate-800" : "text-slate-500"}`}>{label}</span>
              <span className={`mt-0.5 block text-[11px] ${now ? "text-blue-700" : "text-slate-400"}`}>{now ? "현재 단계" : done ? "완료" : "다음 단계"}</span>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

/** 요청 처리 중 표시. 실제 요청이 끝날 때까지만 보인다 (진행률은 알 수 없어 경과 시간만). */
export function Pending({ title, detail, children }: { title: string; detail?: string; children?: React.ReactNode }) {
  const [sec, setSec] = useState(0)
  useEffect(() => { const t = setInterval(() => setSec((s) => s + 1), 1000); return () => clearInterval(t) }, [])
  return (
    <div role="status" className="flex gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
      <Loader2 className="mt-0.5 size-5 shrink-0 animate-spin text-blue-700" aria-hidden="true" />
      <div className="min-w-0 text-sm">
        <p className="font-semibold text-slate-900">{title}</p>
        {detail && <p className="mt-0.5 text-xs leading-5 text-slate-500">{detail}</p>}
        {children}
        <p className="mt-1 text-xs text-slate-400" aria-hidden="true">{sec}초 경과{sec >= 30 ? " · 분석 모델이 응답을 만드는 중이라 1~2분 걸릴 수 있습니다" : ""}</p>
      </div>
    </div>
  )
}
/** 새 요청을 보낸 뒤 서버가 해석하는 동안 (LLM 두 번 + 분류 묶음 · 수 초~1분). 서버가 단계(progress)를 주면 지금 단계와
 *  실제 결과(후보 수·분류 묶음 등)를, 주지 않으면(예전 서버) 하는 일만 보여 준다. 가짜 진행률은 쓰지 않는다. */
export function IdeaPending({ steps }: { steps?: ProgressStep[] }) {
  if (steps?.length) return (
    <Pending title="아이디어를 해석하고 있습니다" detail="서버가 지금 하는 단계와 그 결과입니다. 끝나면 질문 화면으로 넘어갑니다.">
      <ProgressList steps={steps} />
    </Pending>
  )
  return (
    <Pending title="아이디어를 해석하고 있습니다" detail="분석 모델이 아이디어를 이해하고, 기본 투자조건과 맞춰 본 뒤 꼭 필요한 질문만 고릅니다. 끝나면 질문 화면으로 넘어갑니다.">
      <ol className="mt-2 space-y-0.5 text-xs text-slate-600">
        {["아이디어 이해 (투자 테마·종목 찾기)", "기본 투자조건과 맞춰 보기", "꼭 필요한 질문 고르기"].map((t, i) => <li key={t} className="flex gap-2"><span className="grid size-4 shrink-0 place-items-center rounded-full bg-blue-100 text-[10px] font-bold text-blue-800">{i + 1}</span>{t}</li>)}
      </ol>
    </Pending>
  )
}
const STEP_STATE = { done: "완료", running: "진행 중", waiting: "대기", skipped: "건너뜀" } as const
/** 서버 해석 단계 목록. stopped = 해석이 실패해 진행 중이던 단계가 거기서 멈춤 (실패 화면). */
export function ProgressList({ steps, stopped = false }: { steps: ProgressStep[]; stopped?: boolean }) {
  return (
    <ol aria-label="해석 단계" className="mt-2 space-y-1 text-xs">
      {steps.map((s, i) => {
        const halted = stopped && s.status === "running"
        const icon = s.status === "done" ? <Check className="size-3 text-emerald-700" strokeWidth={3} />
          : halted ? <AlertCircle className="size-3 text-red-700" />
          : s.status === "running" ? <Loader2 className="size-3 animate-spin text-blue-700" />
          : <span className="text-[10px] font-bold text-slate-400">{s.status === "skipped" ? "–" : i + 1}</span>
        const ring = s.status === "done" ? "bg-emerald-100" : halted ? "bg-red-100" : s.status === "running" ? "bg-blue-100" : "bg-slate-100"
        return (
          <li key={s.key} className="flex items-start gap-2">
            <span className={`mt-px grid size-4 shrink-0 place-items-center rounded-full ${ring}`} aria-hidden="true">{icon}</span>
            <span className={s.status === "running" ? "font-semibold text-slate-900" : s.status === "done" ? "text-slate-700" : "text-slate-400"}>
              {s.label_ko}
              <span className="sr-only"> ({halted ? "여기서 멈춤" : STEP_STATE[s.status]})</span>
              {halted && <span className="ml-1.5 font-normal text-red-700" aria-hidden="true">여기서 멈춤</span>}
              {s.status === "skipped" && <span className="ml-1.5 font-normal" aria-hidden="true">건너뜀</span>}
              {s.detail_ko && <span className={`ml-1.5 font-normal ${s.status === "running" && !halted ? "text-blue-700" : "text-slate-500"}`}>{s.detail_ko}</span>}
            </span>
          </li>
        )
      })}
    </ol>
  )
}
export const LLM_DETAIL = "분석 모델(AI)이 내용을 해석해 조건에 반영합니다. 처리하는 동안 화면을 닫지 마세요."

/** 「말로 조건 보태기」: 질문 화면과 확인 화면이 같은 이름·안내를 쓴다. */
export const NOTE_BUTTON = "말로 보태기"
export const NOTE_DESC = `질문과 상관없이 바꾸고 싶은 것을 적고 「${NOTE_BUTTON}」를 누르면 분석 모델이 해석해 반영합니다. 투자 시장·숫자 조건은 「조건 바꾸기」가 더 정확합니다.`
export const NOTE_UNSENT = `아직 반영하지 않았습니다. 「${NOTE_BUTTON}」를 눌러야 이번 분석 조건에 들어갑니다.`
/** 적고 아직 보내지 않은 문장 (요청별, 이 탭에서만). 질문 화면 → 확인 화면으로 넘어가도 남아, 확인 화면의 「반영하지 않은 추가 요청」 확인을 거친다. */
const pendingNotes = new Map<string, string>()
export const pendingNote = (requestId: string) => pendingNotes.get(requestId) ?? ""
export const keepPendingNote = (requestId: string, text: string) => { if (text.trim()) pendingNotes.set(requestId, text); else pendingNotes.delete(requestId) }

// ───────────────────────── 요청 그만두기 · 화면 사이 안내 ─────────────────────────
/** 같은 아이디어·조건으로 새 요청을 시작할 수 있게 홈에 미리 채워 둔다 (프로필을 바꿔도 진행 중 요청에는 적용되지 않으므로).
 *  note 를 주면 홈이 왜 채워져 있는지 한 번 알린다 (요청을 그만둔 경우). */
export function startNewWith(idea: string, overrides: Record<string, unknown> | undefined, note?: string) {
  saveUi({ prefillIdea: idea, prefillOverrides: overrides ?? {}, prefillNote: note ?? null, activeRequestId: null })
  navigate({ page: "home" })
}
export const LEFT_NOTE = "그만둔 요청의 아이디어와 바꾼 조건을 그대로 채워 두었습니다. 고쳐서 다시 보내 주세요."

/** 요청 그만두기: 서버에서 요청을 닫고, 아이디어·바꾼 조건을 홈에 채워 둔다 (전에는 홈으로만 가서 아이디어를 다시 써야 했다).
 *  질문 화면·확인 화면이 같이 쓴다. ask → 한 번 더 확인(CancelRequestConfirm) → leave. */
export function useLeaveRequest(requestId: string, st: DialogState | null | undefined) {
  const svc = useService()
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const leave = async () => {
    if (!st) return
    setBusy(true); setError("")
    try { await svc.cancelRequest(requestId); startNewWith(st.idea, st.overrides, LEFT_NOTE) }
    catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false) }
  }
  return { asking, busy, error, ask: () => setAsking(true), close: () => setAsking(false), leave }
}
type Leave = ReturnType<typeof useLeaveRequest>

/** 머리 오른쪽 「취소하고 홈으로」. */
export function CancelRequestButton({ c, disabled }: { c: Leave; disabled?: boolean }) {
  return <Button variant="ghost" onClick={c.ask} disabled={disabled || c.asking || c.busy}><ArrowLeft className="size-4" />취소하고 홈으로</Button>
}

/** 「취소하고 홈으로」를 누른 뒤의 확인. keepLabel = 그만두지 않고 남는 버튼 이름 (질문 화면 「계속 답하기」, 확인 화면 「계속 확인하기」). */
export function CancelRequestConfirm({ c, keepLabel, disabled }: { c: Leave; keepLabel: string; disabled?: boolean }) {
  if (!c.asking) return c.error ? <ActionError title="요청을 취소하지 못했습니다" message={c.error} retry={() => void c.leave()} /> : null
  return (
    <div role="alertdialog" aria-label="요청 취소 확인" className="rounded-2xl border border-red-200 bg-red-50 p-5 text-sm text-red-900">
      <p className="font-semibold">이 요청을 취소할까요?</p>
      <p className="mt-1">지금까지 답한 내용은 이 요청과 함께 닫히고, 분석은 시작되지 않습니다. 아이디어와 바꾼 조건은 홈에 그대로 채워 둡니다.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button variant="danger" onClick={() => void c.leave()} disabled={disabled || c.busy}>{c.busy ? "취소하는 중…" : "요청 취소"}</Button>
        <Button variant="ghost" onClick={c.close} disabled={c.busy}>{keepLabel}</Button>
      </div>
      {c.error && <p className="mt-2 text-xs font-medium">취소하지 못했습니다: {c.error} 다시 눌러 주세요.</p>}
    </div>
  )
}

/** 화면을 넘어가며 남기는 1회성 안내 (요청별, 이 탭에서만 · pendingNotes 와 같은 방식).
 *  확인 화면에서 조건을 바꿨더니 다시 물을 것이 생겨 질문 화면으로 돌아갈 때, 왜 돌아왔는지 알리는 데 쓴다. */
export interface FlowNotice { what: string; changes: RowChange[] }
const notices = new Map<string, FlowNotice>()
export const leaveFlowNotice = (requestId: string, n: FlowNotice) => { notices.set(requestId, n) }
/** 읽고 지운다. 개발 모드 이중 실행에도 한 번은 보이도록 state 초기값에서 읽고(peek), 지우기는 effect 에서 한다. */
export function useFlowNotice(requestId: string) {
  const [n] = useState(() => notices.get(requestId) ?? null)
  useEffect(() => { notices.delete(requestId) }, [requestId])
  return n
}

/** 질문 화면 맨 위: 확인 화면에서 바꾼 것 때문에 다시 확인할 것이 생겨 돌아왔다는 안내. */
export function BackToQuestions({ n, hardErrors }: { n: FlowNotice; hardErrors: boolean }) {
  return (
    <Alert tone="warning" title={`방금 ${n.what} 때문에 분석 전에 다시 확인할 것이 생겨 이 화면으로 돌아왔습니다`}>
      {n.changes.length > 0 && <ul className="mt-1 list-disc pl-5">{n.changes.map((c) => <li key={c.label}>{c.label}: {c.before} → <b>{c.after}</b></li>)}</ul>}
      <p className="mt-1">{hardErrors ? "아래 오류를 고치면" : "아래 질문에 답하면"} 다시 조건 확인 화면으로 넘어갑니다.</p>
    </Alert>
  )
}

export function ActionError({ title, message, retry }: { title: string; message: string; retry?: () => void }) {
  return (
    <div role="alert" className="flex gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-red-950">
      <AlertCircle className="mt-0.5 size-5 shrink-0" />
      <div className="min-w-0 text-sm">
        <p className="font-semibold">{title}</p>
        <p className="mt-0.5 leading-6 opacity-80">{message} 입력한 내용은 그대로 남아 있습니다.</p>
        {retry && <Button variant="secondary" className="mt-2" onClick={retry}>다시 시도</Button>}
      </div>
    </div>
  )
}

export function IdeaPart({ st }: { st: DialogState }) {
  return (
    <Part title="투자 아이디어">
      <blockquote className="border-l-4 border-slate-200 pl-3 text-[15px] leading-7 text-slate-800">{st.idea}</blockquote>
      {st.summary.interpretation_summary_ko && (
        <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-700">
          <p className="text-xs font-bold text-slate-500">분석 모델의 이해</p>
          <p className="mt-1">{st.summary.interpretation_summary_ko}</p>
          {st.summary.themes.length > 0 && <div className="mt-2 flex flex-wrap gap-2">{st.summary.themes.map((t) => <Badge key={t.id} tone="slate">{t.label_ko}</Badge>)}</div>}
        </div>
      )}
    </Part>
  )
}

/** 조건 바꾸기·말로 보태기가 끝난 뒤: 실제로 바뀐 조건 값 (없으면 그렇다고 알린다). */
export function ResultNote({ changes, what }: { changes: RowChange[]; what: string }) {
  return (
    <div role="status" className={`rounded-xl border p-4 text-sm ${changes.length ? "border-emerald-200 bg-emerald-50 text-emerald-950" : "border-slate-200 bg-slate-50 text-slate-700"}`}>
      <p className="font-semibold">{changes.length ? `${what}을 반영했습니다. 바뀐 조건 ${changes.length}개` : `${what}을 처리했지만 바뀐 조건 값은 없습니다.`}</p>
      {changes.length > 0 && <ul className="mt-1.5 space-y-0.5">{changes.map((c) => <li key={c.label}>{c.label}: {c.before} → <b>{c.after}</b></li>)}</ul>}
      {!changes.length && what === "추가 요청" && <p className="mt-1 text-xs">테마 해석에만 쓰였거나, 확인 질문으로 이어질 수 있습니다. 투자 시장·숫자 조건은 「조건 바꾸기」로 직접 바꿔 주세요.</p>}
    </div>
  )
}

// ───────────────────────── 조건 ─────────────────────────
const SOURCE_KO: Record<ConditionRow["source"], string> = { profile: "기본 투자조건", idea: "아이디어", answer: "답변·직접 변경", default: "기본값", derived: "계산" }
const visible = (rows: ConditionRow[]) => rows.filter((r) => r.group_ko !== "아이디어")

/** 요청 전후 조건 행 비교 (같은 field 의 표시값이 달라진 것). 조건 바꾸기·말로 보태기 결과 안내용. */
export interface RowChange { label: string; before: string; after: string }
export function diffRows(before: ConditionRow[], after: ConditionRow[]): RowChange[] {
  const old = new Map(before.map((r) => [r.field, r.value_ko]))
  return visible(after).filter((r) => old.has(r.field) && old.get(r.field) !== r.value_ko).map((r) => ({ label: r.label_ko, before: old.get(r.field)!, after: r.value_ko }))
}

/** 기본 투자조건(수정안이면 원안)과 달라진 조건만. 비교는 서버의 changed·profile_value_ko 를 그대로 쓴다. */
export function ChangedConditions({ rows, base, action, children }: { rows: ConditionRow[]; base: string; action?: React.ReactNode; children?: React.ReactNode }) {
  const changed = visible(rows).filter((r) => r.changed)
  return (
    <Part title="이번 분석에서 달라진 조건" desc={`${base}과 다른 항목만 보여 줍니다.`} aside={action}>
      {changed.length ? (
        <ul className="divide-y divide-slate-100">
          {changed.map((r) => (
            <li key={r.field} className="flex flex-col gap-1 py-2.5 first:pt-0 last:pb-0 sm:flex-row sm:items-baseline sm:gap-4">
              <span className="shrink-0 text-sm font-semibold text-slate-900 sm:w-40">{r.label_ko}{isTickerField(r.field) && <MockTag />}</span>
              <span className="min-w-0 break-words text-sm text-slate-700">
                {r.profile_value_ko != null && <><span className="text-slate-400">{base} {r.profile_value_ko}</span><span className="mx-1.5 text-slate-400">→</span></>}
                <b className="text-slate-950">{r.value_ko}</b>
                <span className="ml-2 text-xs text-slate-400">{SOURCE_KO[r.source]}</span>
              </span>
            </li>
          ))}
        </ul>
      ) : <p className="text-sm text-slate-600">{base}과 달라진 항목이 없습니다. {base}을 그대로 사용합니다.</p>}
      {children}
    </Part>
  )
}

/** 전체 투자 조건 (기본 접힘, 그룹별 · 서버가 주는 「계산 조건」 묶음 포함). 접고 펼쳐도 값은 그대로 (행 데이터를 다시 받지 않는다). */
export function AllConditions({ rows, base }: { rows: ConditionRow[]; base: string }) {
  const list = visible(rows)
  const groups = [...new Set(list.map((r) => r.group_ko))]
  return (
    <PartDisclosure title="전체 투자 조건 보기" summary={`${list.length}개 항목 · 달라진 항목 ${list.filter((r) => r.changed).length}개`}>
      {groups.map((g) => (
        <section key={g} className="rounded-xl border border-slate-200">
          <h4 className="rounded-t-xl border-b border-slate-200 bg-slate-100 px-4 py-2.5 text-sm font-bold text-slate-900">{g}</h4>
          <dl className="grid grid-cols-1 gap-x-8 gap-y-3 p-4 text-sm sm:grid-cols-2">
            {list.filter((r) => r.group_ko === g).map((r) => (
              <div key={r.field} className="min-w-0">
                <dt className="flex items-center gap-1.5 text-xs font-semibold text-slate-500">{r.label_ko}{isTickerField(r.field) && <MockTag />}{r.changed && <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-600">달라짐</span>}</dt>
                <dd className="mt-0.5 break-words font-semibold text-slate-900">{r.value_ko}</dd>
                {r.changed && r.profile_value_ko != null && <dd className="text-xs text-slate-400">{base} {r.profile_value_ko}</dd>}
                {r.note_ko && <dd className="mt-0.5 text-xs leading-5 text-amber-700">{r.note_ko}</dd>}
              </div>
            ))}
          </dl>
        </section>
      ))}
    </PartDisclosure>
  )
}

// ───────────────────────── 질문 ─────────────────────────
/** 질문 종류별 짧은 설명 (질문 문구 자체는 서버가 준 그대로 둔다). */
export const KIND_HELP: Record<Question["kind"], string> = {
  missing: "분석에 꼭 필요한데 아직 정해지지 않은 조건입니다.",
  conflict: "투자 아이디어와 기본 투자조건이 서로 달라, 이번 분석에서 어느 쪽을 쓸지 고릅니다.",
  ambiguous: "아이디어를 두 가지 이상으로 해석할 수 있어 확인합니다.",
  preference: "결과가 달라질 수 있는 선택이라 원하는 쪽을 확인합니다.",
  feasibility: "지금 조건으로는 분석에 필요한 종목이나 과거 자료가 부족해, 분석을 시작하기 전에 조정 방법을 고릅니다.",
}

/** 이미 답한 질문과 답 (같은 조건을 다시 묻더라도 무엇을 답했는지 확인할 수 있게). */
export function AnsweredList({ questions }: { questions: Question[] }) {
  const done = questions.filter((x) => x.answered_at)
  if (!done.length) return null
  return (
    <PartDisclosure title="지금까지 답한 내용" summary={`${done.length}개`}>
      <ol className="space-y-3">
        {done.map((x, i) => (
          <li key={x.seq} className="rounded-xl border border-slate-200 bg-white p-3 text-sm">
            <p className="flex flex-wrap items-center gap-2 text-xs text-slate-500"><span className="font-bold text-slate-700">질문 {i + 1}</span>{x.field_label_ko ?? ko(x.field)}{isTickerField(x.field) && <MockTag />}</p>
            <p className="mt-1 text-slate-800">{x.question_ko}</p>
            <p className="mt-1.5 flex items-start gap-1.5 font-semibold text-slate-950"><Check className="mt-0.5 size-4 shrink-0 text-emerald-600" aria-hidden="true" />{x.skipped ? "답하지 않음 (기본값 사용)" : x.answer}</p>
          </li>
        ))}
      </ol>
    </PartDisclosure>
  )
}
