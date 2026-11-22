// 처음 켰을 때의 연결 흐름 (소개 다음 · 내 투자조건 앞). 사이드바 없이 한 화면에 입력 하나: 팀 DB → 분석 모델 → 내 투자조건.
// 「투자조건 도우미」(한 번에 질문 하나 + 진행 표시)와 같은 짜임: 흰 카드 하나, 머리에 진행 표시, 몸에 지금 할 일.
// 서비스에 getConnections 가 있을 때만 App 이 이 화면을 연다. 목업과 실제 서버(backend/analysis/connections.py, /connections) 모두 있다.
import { Fragment, useEffect, useState } from "react"
import { BookOpen, Check, CreditCard, Database, ExternalLink, FileText, Loader2, Monitor, Send, SlidersHorizontal, TrendingUp } from "lucide-react"
import { errorMessage } from "../../api/client"
import type { ProposedConnectionKind, ProposedConnections } from "../../api/proposed"
import { useProfile, useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { Alert, ErrorState, Loading } from "../../ui"
import { MockTag } from "../report/proposedView"
import { costLabel, dataStarts } from "./copy"
import { buildDbUrl, parseDbUrl } from "./dbUrl"
import { OpenAiMark } from "./openaiMark"
import { ErrorNote, Facts, More, Notes, SavedField, SecretField, ghostBig, linkClass, primaryBig, useConnect } from "./parts"
import { markConnectSkipped } from "./skip"

type StopState = "now" | "done" | "skip" | "next"   // 지금 · 연결됨 · 건너뜀 · 아직
const inputClass = "h-11 w-full rounded-control border border-line bg-surface px-3.5 text-14 text-main outline-none transition placeholder:text-hint focus:border-focus focus:ring-2 focus:ring-focus/25"

/** 저장하는 곳을 문장에 넣는다: 서버가 알려 준 운영체제 보관함 이름 (Windows 자격 증명 관리자 · macOS 키체인 …). 뒤에 '에'를 붙여 쓴다 */
const storeName = (label: string | null) => label ?? "이 컴퓨터의 보관함"
/** 분석 모델 안내 세 줄. 사용료 어림(cost)은 서버가 줄 때만 숫자로 적는다. */
export const llmNotes = (cost: number | null, store: string | null) => [
  { icon: Monitor, title: "이 컴퓨터에만 저장", text: `키는 ${storeName(store)}에 저장되고 연결 설정에서 지울 수 있습니다.` },
  { icon: Send, title: "OpenAI에만 사용", text: "키는 아이디어 해석과 리포트 작성에 OpenAI 모델을 부를 때만 씁니다." },
  { icon: CreditCard, title: cost != null ? `분석 1회 약 ${costLabel(cost)}달러` : "분석할 때 사용료", text: "사용료는 키를 발급한 OpenAI 계정에 청구됩니다." },
]
/** 팀 DB 안내 세 줄 (backend/analysis/common/dbconn.py: 읽기는 팀 DB, 실행 기록·리포트 쓰기는 이 컴퓨터의 파일). */
export const databaseNotes = (store: string | null) => [
  { icon: Monitor, title: "이 컴퓨터에만 저장", text: `주소는 ${storeName(store)}에 저장되고 연결 설정에서 지울 수 있습니다.` },
  { icon: BookOpen, title: "가격·재무·뉴스 조회", text: "앱은 팀 DB에서 자료를 읽기만 하고 고치지 않습니다." },
  { icon: FileText, title: "팀 DB와 따로 보관", text: "리포트와 실행 기록은 이 컴퓨터에 저장됩니다." },
]

/** 환경변수(.env · Docker Compose)로 들어온 연결: 화면에서는 보여 주기만 한다 */
function FromEnv() {
  return <p className="mx-5 mt-3 text-13 text-sub">환경변수(.env)로 설정된 연결입니다. 바꾸려면 그 파일을 고친 뒤 서버를 다시 켜 주세요.</p>
}
/** 운영체제 보관함이 없는 환경(Docker 컨테이너 등): 화면에서 저장할 수 없으니 넣는 방법만 알린다 */
function NoSave({ line }: { line: string }) {
  return (
    <div className="mt-7">
      <Alert tone="info" title="이 환경에서는 화면에서 저장할 수 없습니다.">
        서버를 켜는 폴더의 <code className="rounded bg-surface px-1 font-mono text-12 text-main">.env</code> 파일에 <code className="rounded bg-surface px-1 font-mono text-12 text-main">{line}</code> 줄을 적고 서버를 다시 켜 주세요.
      </Alert>
    </div>
  )
}

export function ConnectFlow({ step }: { step: ProposedConnectionKind }) {
  const svc = useService()
  const { profile } = useProfile()
  const [conns, setConns] = useState<ProposedConnections | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const load = () => { setLoadError(null); svc.getConnections!().then(setConns, (e) => setLoadError(errorMessage(e))) }
  useEffect(load, [svc])  // eslint-disable-line react-hooks/exhaustive-deps
  /** 흐름 끝: 이번 실행 동안 다시 띄우지 않게 적어 두고, 투자조건이 없으면 처음 설정으로 (대화형이 있으면 대화로) */
  const finish = () => { markConnectSkipped(); navigate(profile ? { page: "home" } : { page: "profile", mode: svc.startProfileChat ? "chat" : "setup" }) }

  const db: StopState = step === "database" ? (conns?.database.connected ? "done" : "now") : conns?.database.connected ? "done" : "skip"
  const llm: StopState = step === "llm" ? (conns?.llm.connected ? "done" : "now") : "next"
  return (
    <main className="connect min-h-screen bg-canvas px-10 pb-16 pt-7">
      <div className="flex items-center gap-3">
        <span className="flex size-9 items-center justify-center rounded-xl bg-accent text-on-accent"><TrendingUp className="size-5" aria-hidden="true" /></span>
        <span><span className="block text-base font-extrabold tracking-tight text-main">MyFinSight</span><span className="block text-[10px] font-medium text-sub">개인화 투자전략</span></span>
        <MockTag />
      </div>
      <div className="mx-auto mt-[5vh] w-full max-w-[680px] rounded-card bg-surface">
        <Track busy={busy} stops={[{ label: "팀 DB", icon: Database, state: db }, { label: "분석 모델", icon: OpenAiMark, state: llm }, { label: "내 투자조건", icon: SlidersHorizontal, state: "next" }]} />
        <div className="px-10 pb-8 pt-10">
          {loadError ? <ErrorState title="연결 상태를 불러오지 못했습니다" message={loadError} retry={load} />
            : !conns ? <Loading />
            : step === "database" ? <DatabaseStep key="database" conns={conns} onSaved={setConns} onBusy={setBusy} onNext={() => navigate({ page: "connect", step: "llm" })} />
            : <LlmStep key="llm" conns={conns} onSaved={setConns} onBusy={setBusy} onNext={finish} nextLabel={profile ? "홈으로" : "내 투자조건 설정으로"} />}
        </div>
      </div>
    </main>
  )
}

/** 진행 표시: 숫자 대신 연결할 대상의 아이콘. 지금 단계는 파란 테, 연결되면 확인 표시와 초록 선, 건너뛰면 회색으로 남는다. */
function Track({ stops, busy }: { stops: { label: string; icon: React.ElementType; state: StopState }[]; busy: boolean }) {
  const note = { now: "", done: " (연결됨)", skip: " (건너뜀)", next: "" } as const
  return (
    <ol aria-label="시작 준비 단계" className="flex items-center gap-2.5 border-b border-line px-10 py-5 text-13 font-medium text-sub">
      {stops.map((s, i) => (
        <Fragment key={s.label}>
          {i > 0 && <li aria-hidden="true" className={`w-11 shrink-0 border-t-2 transition-colors duration-500 ${stops[i - 1].state === "done" ? "border-solid border-success" : "border-dashed border-line"}`} />}
          <li aria-current={s.state === "now" ? "step" : undefined} className={`flex items-center gap-2.5 whitespace-nowrap ${s.state === "now" ? "font-bold text-main" : s.state === "done" ? "text-main" : ""}`}>
            <span className={`relative grid size-10 shrink-0 place-items-center rounded-full bg-sunken ${s.state === "now" || s.state === "done" ? "text-main" : "text-hint"} ${s.state === "now" && !busy ? "ring-2 ring-accent" : ""}`}>
              {s.state === "now" && busy && <span aria-hidden="true" className="absolute -inset-0.5 animate-spin rounded-full border-2 border-line border-t-accent motion-reduce:animate-none" />}
              <s.icon className="size-[21px]" aria-hidden="true" />
              {s.state === "done" && <span aria-hidden="true" className="absolute -bottom-1 -right-1 grid size-[18px] place-items-center rounded-full border-2 border-surface bg-success text-on-accent"><Check className="size-2.5" strokeWidth={3.5} /></span>}
            </span>
            {s.label}<span className="sr-only">{note[s.state]}</span>
          </li>
        </Fragment>
      ))}
    </ol>
  )
}

interface StepProps { conns: ProposedConnections; onSaved: (c: ProposedConnections) => void; onBusy: (b: boolean) => void; onNext: () => void }

/** 아래 버튼 줄: 왼쪽은 나중에 하기·취소, 오른쪽은 지금 할 일 하나 */
function Actions({ phase, canSubmit, onSubmit, onCancel, left }: { phase: "idle" | "testing" | "error"; canSubmit: boolean; onSubmit: () => void; onCancel: () => void; left: React.ReactNode }) {
  return (
    <div className="mt-9 flex items-center gap-3">
      {phase === "testing" ? <button type="button" className={ghostBig} onClick={onCancel}>취소</button> : left}
      {phase === "testing"
        ? <button type="button" disabled aria-busy="true" className={`${primaryBig} ml-auto cursor-progress disabled:bg-accent`}><Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />연결을 확인하는 중…</button>
        : <button type="button" disabled={!canSubmit} className={`${primaryBig} ml-auto`} onClick={onSubmit}>{phase === "error" ? "다시 연결하기" : "연결하기"}</button>}
    </div>
  )
}

function DatabaseStep({ conns, onSaved, onBusy, onNext }: StepProps) {
  const conn = conns.database
  const [editing, setEditing] = useState(false)
  const [mode, setMode] = useState<"url" | "parts">("url")
  const [value, setValue] = useState("")
  const [parts, setParts] = useState({ host: "", port: "5432", name: "myfinsight", user: "", password: "" })
  const c = useConnect("database", (cs) => { onSaved(cs); setEditing(false); setValue("") })
  useEffect(() => onBusy(c.phase === "testing"), [c.phase])  // eslint-disable-line react-hooks/exhaustive-deps
  const busy = c.phase === "testing"
  const parsed = mode === "url" ? parseDbUrl(value) : null
  const canSubmit = mode === "url" ? value.trim() !== "" : parts.host.trim() !== ""
  const part = (k: keyof typeof parts, label: string, opts: { placeholder?: string; type?: string; wide?: boolean } = {}) => (
    <label className={`block ${opts.wide ? "col-span-2" : ""}`}>
      <span className="mb-1.5 block text-13 font-semibold text-main">{label}</span>
      <input className={inputClass} type={opts.type ?? "text"} value={parts[k]} placeholder={opts.placeholder} readOnly={busy} autoComplete="off" spellCheck={false} onChange={(e) => { setParts({ ...parts, [k]: e.target.value }); c.dismiss() }} />
    </label>
  )

  if (conn.source === "env" && !conn.connected) {  // 환경변수의 주소가 닿지 않는다: 화면에서 고칠 수 없으니 원인만 알린다
    return (
      <section>
        <h1 className="t-display text-balance">팀 DB에 연결하지 못했습니다</h1>
        <div className="mt-7"><SavedField icon={Database} label="팀 DB 접속 주소" masked={conn.masked ?? "환경변수에 적힌 주소"} /></div>
        {conn.error && <ErrorNote error={conn.error} />}
        <FromEnv />
        <div className="mt-9 flex items-center"><button type="button" className={`${primaryBig} ml-auto`} onClick={onNext}>다음</button></div>
      </section>
    )
  }
  if (conn.connected && !editing) {
    return (
      <section aria-live="polite">
        <h1 className="t-display text-balance">팀 DB에 연결했습니다</h1>
        <div className="mt-7"><SavedField icon={Database} label="팀 DB 접속 주소" masked={conn.masked ?? "연결됨"} onChange={conn.source === "env" || !conns.can_save ? undefined : () => setEditing(true)} /></div>
        {conn.latest_trading_day && <Facts items={[{ label: "최신 거래일", value: conn.latest_trading_day }, ...dataStarts(conn).map((s) => ({ label: s.market ? `${s.market} 자료 시작일` : "자료 시작일", value: s.date }))]} />}
        {conn.source === "env" && <FromEnv />}
        <div className="mt-9 flex items-center"><button type="button" className={`${primaryBig} ml-auto`} onClick={onNext}>다음</button></div>
      </section>
    )
  }
  if (!conns.can_save) {
    return (
      <section>
        <h1 className="t-display text-balance">팀에서 받은 DB 주소를 넣어 주세요</h1>
        <NoSave line="DATABASE_URL=postgresql://…" />
        <div className="mt-9 flex items-center"><button type="button" className={`${primaryBig} ml-auto`} onClick={onNext}>다음</button></div>
        <p className="mt-2.5 text-13 text-sub">지금 연결하지 않아도 예시 데이터로 둘러볼 수 있습니다.</p>
      </section>
    )
  }
  return (
    <section aria-live="polite">
      <h1 className="t-display text-balance">팀에서 받은 DB 주소를 붙여 넣어 주세요</h1>
      {mode === "url" ? (
        <>
          <div className="mt-7"><SecretField icon={Database} label="팀에서 받은 DB 접속 주소" value={value} onChange={(v) => { setValue(v); c.dismiss() }} placeholder="postgresql://계정:비밀번호@서버:5432/이름" invalid={c.phase === "error"} busy={busy} describedBy="connect-db-error connect-db-notes" autoFocus /></div>
          {/* 붙여 넣으면 바로 풀어서 보여 준다. 실패하면 문제가 된 서버 주소에 표시 */}
          {parsed && <Facts items={[{ label: "서버", value: parsed.host, bad: c.error?.code === "host_not_found" }, { label: "포트", value: parsed.port }, { label: "데이터베이스", value: parsed.name || "없음", bad: c.error?.code === "database_not_found" }, { label: "계정", value: parsed.user || "없음" }]} />}
        </>
      ) : (
        <div className="mt-7 grid grid-cols-2 gap-x-3 gap-y-3.5">
          {part("host", "서버", { placeholder: "db.example.com", wide: true })}
          {part("port", "포트")}
          {part("name", "데이터베이스")}
          {part("user", "계정", { placeholder: "reader" })}
          {part("password", "비밀번호", { type: "password" })}
        </div>
      )}
      {c.error ? <ErrorNote id="connect-db-error" error={c.error} /> : (
        <>
          <Notes id="connect-db-notes" rows={databaseNotes(conns.store_label_ko)} />
          <div className="mx-5 mt-3 flex justify-end"><button type="button" className={linkClass} disabled={busy} onClick={() => setMode(mode === "url" ? "parts" : "url")}>{mode === "url" ? "항목별로 입력" : "주소 한 줄로 입력"}</button></div>
        </>
      )}
      <Actions phase={c.phase} canSubmit={canSubmit} onSubmit={() => void c.submit(mode === "url" ? value.trim() : buildDbUrl(parts))} onCancel={c.cancel}
        left={editing ? <button type="button" className={ghostBig} onClick={() => { setEditing(false); c.dismiss() }}>취소</button> : <button type="button" className={ghostBig} onClick={onNext}>나중에 하기</button>} />
      {!editing && !busy && <p className="mt-2.5 text-13 text-sub">지금 연결하지 않아도 예시 데이터로 둘러볼 수 있습니다.</p>}
    </section>
  )
}

function LlmStep({ conns, onSaved, onBusy, onNext, nextLabel }: StepProps & { nextLabel: string }) {
  const conn = conns.llm
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState("")
  const c = useConnect("llm", (cs) => { onSaved(cs); setEditing(false); setValue("") })
  useEffect(() => onBusy(c.phase === "testing"), [c.phase])  // eslint-disable-line react-hooks/exhaustive-deps
  const busy = c.phase === "testing"

  if (conn.stub_pinned) {  // 환경변수 MYFINSIGHT_LLM=stub: 키를 넣어도 쓰이지 않으니 입력칸 대신 푸는 방법을 알린다 (.env.example 을 그대로 복사하면 이 상태다)
    return (
      <section>
        <h1 className="t-display text-balance">OpenAI API 키를 넣어 주세요</h1>
        <div className="mt-7">
          <Alert tone="warning" title="서버가 연습 모드로 고정돼 있어 지금은 키를 넣을 수 없습니다.">
            <code className="rounded bg-surface px-1 font-mono text-12 text-main">.env</code> 파일에서 <code className="rounded bg-surface px-1 font-mono text-12 text-main">MYFINSIGHT_LLM=stub</code> 줄을 지우고 서버를 다시 켜 주세요.
          </Alert>
        </div>
        <div className="mt-9 flex items-center"><button type="button" className={`${primaryBig} ml-auto`} onClick={onNext}>{nextLabel}</button></div>
        <p className="mt-2.5 text-13 text-sub">지금 연결하지 않아도 미리 만든 답으로 둘러볼 수 있습니다.</p>
      </section>
    )
  }
  if (conn.connected && !editing) {
    return (
      <section aria-live="polite">
        <h1 className="t-display text-balance">OpenAI에 연결했습니다</h1>
        <div className="mt-7"><SavedField icon={OpenAiMark} label="OpenAI API 키" masked={conn.masked ?? "연결됨"} onChange={conn.source === "env" || !conns.can_save ? undefined : () => setEditing(true)} /></div>
        {conn.source === "env" && <FromEnv />}
        <div className="mt-9 flex items-center"><button type="button" className={`${primaryBig} ml-auto`} onClick={onNext}>{nextLabel}</button></div>
      </section>
    )
  }
  if (!conns.can_save) {
    return (
      <section>
        <h1 className="t-display text-balance">OpenAI API 키를 넣어 주세요</h1>
        <NoSave line="OPENAI_API_KEY=sk-…" />
        <div className="mt-9 flex items-center"><button type="button" className={`${primaryBig} ml-auto`} onClick={onNext}>{nextLabel}</button></div>
        <p className="mt-2.5 text-13 text-sub">지금 연결하지 않아도 미리 만든 답으로 둘러볼 수 있습니다.</p>
      </section>
    )
  }
  return (
    <section aria-live="polite">
      <h1 className="t-display text-balance">OpenAI API 키를 넣어 주세요</h1>
      <div className="mt-7"><SecretField icon={OpenAiMark} label="OpenAI API 키" value={value} onChange={(v) => { setValue(v); c.dismiss() }} placeholder="팀에서 받은 키 또는 직접 만든 키" invalid={c.phase === "error"} busy={busy} describedBy="connect-llm-error connect-llm-notes" autoFocus /></div>
      {c.error && <ErrorNote id="connect-llm-error" error={c.error} />}
      <Notes id="connect-llm-notes" rows={llmNotes(conn.cost_per_run_usd, conns.store_label_ko)} />
      {/* 필요한 사람만 찾는 것은 접어 둔다. 마지막 줄: 서버는 켤 때 설정 파일의 OPENAI_API_KEY 를 읽으므로 화면을 거치지 않는 길이 이미 있다 */}
      <div className="relative">
        <More label="자세히" className="ml-3.5 mr-5 mt-2">
          <ul className="ml-1.5 mt-1 list-disc space-y-1 pl-[18px] text-13 text-body">
            <li>키는 요청마다 붙어서 OpenAI가 어느 계정의 요청인지 확인하는 데 쓰입니다. 요청은 이 컴퓨터에서 OpenAI로 바로 가고 다른 서버를 거치지 않습니다.</li>
            <li>키를 새로 만든다면 이 앱에만 쓸 키로 만들고 OpenAI에서 사용 한도를 걸어 두기를 권합니다.</li>
            <li>화면에 넣고 싶지 않다면 앱 폴더의 <code className="rounded bg-sunken px-1 font-mono text-12 text-main">.env</code> 파일에 <code className="rounded bg-sunken px-1 font-mono text-12 text-main">OPENAI_API_KEY=sk-...</code> 한 줄을 적고 앱을 다시 켜면 됩니다.</li>
          </ul>
        </More>
        <a className={`${linkClass} absolute right-5 top-1.5`} href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer">API 키 만들기<ExternalLink className="size-3.5" aria-hidden="true" /></a>
      </div>
      <Actions phase={c.phase} canSubmit={value.trim() !== ""} onSubmit={() => void c.submit(value.trim())} onCancel={c.cancel}
        left={editing ? <button type="button" className={ghostBig} onClick={() => { setEditing(false); c.dismiss() }}>취소</button> : <button type="button" className={ghostBig} onClick={onNext}>나중에 하기</button>} />
      {!editing && !busy && <p className="mt-2.5 text-13 text-sub">지금 연결하지 않아도 미리 만든 답으로 둘러볼 수 있습니다.</p>}
    </section>
  )
}
