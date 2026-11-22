// 연결 설정의 공용 조각: 처음 설정 흐름(ConnectFlow)과 「연결 설정」 화면(ConnectionSettings)이 같은 입력칸·안내·오류 표시를 쓴다.
import { useRef, useState } from "react"
import { AlertCircle, CheckCircle2, ChevronDown, Eye, EyeOff } from "lucide-react"
import { errorMessage } from "../../api/client"
import type { ProposedConnectionError, ProposedConnectionKind, ProposedConnections } from "../../api/proposed"
import { useHealth, useService } from "../../app/providers"
import { errorCopy } from "./copy"

type Icon = React.ElementType

/** 연결 하나를 확인·저장하는 흐름. testing 동안 「취소」하면 결과를 기다리지 않고, 뒤늦게 성공해 저장된 값은 지운다 (취소 = 저장하지 않음). */
export function useConnect(kind: ProposedConnectionKind, onSaved: (c: ProposedConnections) => void) {
  const svc = useService()
  const { reload } = useHealth()
  const [phase, setPhase] = useState<"idle" | "testing" | "error">("idle")
  const [error, setError] = useState<ProposedConnectionError | null>(null)
  const run = useRef(0)
  const submit = async (value: string) => {
    const my = ++run.current
    setPhase("testing"); setError(null)
    try {
      const r = await svc.saveConnection!(kind, value)
      if (my !== run.current) {  // 그사이 취소했다. 새로 시작한 확인이 없을 때만 되돌린다 (있으면 그 확인이 덮어쓴다)
        if (r.ok && run.current === my + 1) void svc.clearConnection!(kind).then(reload, () => {})
        return
      }
      if (r.ok) { setPhase("idle"); onSaved(r.connections); reload() }  // 연습 모드 알림이 바로 바뀌게 서버 상태도 다시 읽는다
      else { setError(r.error ?? { code: "unknown", value: null, raw: null }); setPhase("error") }
    } catch (e) {
      if (my !== run.current) return
      setError({ code: "unknown", value: null, raw: errorMessage(e) }); setPhase("error")
    }
  }
  const cancel = () => { run.current++; setPhase("idle") }
  /** 값을 고치기 시작하면 지난 오류 표시를 지운다 */
  const dismiss = () => { if (phase === "error") { setPhase("idle"); setError(null) } }
  return { phase, error, submit, cancel, dismiss }
}

/** 큰 입력칸: 왼쪽 아이콘이 무엇을 넣는 칸인지 알려 준다. 값은 가려 두고 눈 버튼으로 본다. */
export function SecretField({ icon: Icon, label, value, onChange, placeholder, invalid = false, busy = false, describedBy, autoFocus = false }: {
  icon: Icon; label: string; value: string; onChange: (v: string) => void; placeholder: string; invalid?: boolean; busy?: boolean; describedBy?: string; autoFocus?: boolean
}) {
  const [show, setShow] = useState(false)
  return (
    <div className={`connect-field flex h-16 items-center gap-3.5 rounded-box border pl-5 pr-2.5 transition ${invalid ? "border-danger bg-surface focus-within:ring-4 focus-within:ring-danger/15" : "border-transparent bg-sunken focus-within:border-focus focus-within:bg-surface focus-within:ring-4 focus-within:ring-focus/20"}`}>
      <Icon className="size-6 shrink-0 text-main" aria-hidden="true" />
      {/* autoComplete off: 브라우저가 주소·키를 「비밀번호 저장」 대상으로 삼지 않게 */}
      <input type={show ? "text" : "password"} value={value} onChange={(e) => onChange(e.target.value)} readOnly={busy} autoFocus={autoFocus} autoComplete="off" spellCheck={false}
        aria-label={label} aria-invalid={invalid} aria-describedby={describedBy} placeholder={placeholder}
        className="h-full min-w-0 flex-1 bg-transparent font-mono text-15 text-main outline-none placeholder:font-sans placeholder:text-hint read-only:text-sub" />
      <button type="button" aria-label={`${label} ${show ? "숨기기" : "보기"}`} aria-pressed={show} onClick={() => setShow((v) => !v)}
        className="grid size-11 shrink-0 place-items-center rounded-control text-sub transition hover:bg-sunken-hover hover:text-main focus:outline-none focus-visible:ring-2 focus-visible:ring-focus">
        {show ? <EyeOff className="size-5" aria-hidden="true" /> : <Eye className="size-5" aria-hidden="true" />}
      </button>
    </div>
  )
}

/** 저장된 값: 가린 표시만 보여 준다 (다시 읽어 올 수 없다). */
export function SavedField({ icon: Icon, label, masked, onChange }: { icon: Icon; label: string; masked: string; onChange?: () => void }) {
  return (
    <div role="group" aria-label={label} className="flex h-16 items-center gap-3.5 rounded-box bg-sunken pl-5 pr-2.5">
      <Icon className="size-6 shrink-0 text-main" aria-hidden="true" />
      <code className="min-w-0 flex-1 truncate font-mono text-14 text-main">{masked}</code>
      {onChange && <button type="button" aria-label={`${label} 바꾸기`} onClick={onChange} className="h-10 shrink-0 rounded-control px-3 text-14 font-semibold text-accent transition hover:bg-tint focus:outline-none focus-visible:ring-2 focus-visible:ring-focus">바꾸기</button>}
    </div>
  )
}

/** 값이 데이터일 때의 이름표-값 (붙여 넣은 주소를 푼 값, 연결된 DB 의 자료 범위). bad = 실패한 부분 */
export function Facts({ items }: { items: { label: string; value: string; bad?: boolean }[] }) {
  return (
    <dl className="mx-5 mt-4 flex flex-wrap gap-x-8 gap-y-2.5">
      {items.map((it) => (
        <div key={it.label} className="min-w-0">
          <dt className="text-12 text-sub">{it.label}</dt>
          <dd className={`text-14 font-semibold [overflow-wrap:anywhere] ${it.bad ? "text-danger underline decoration-wavy underline-offset-4" : "text-main"}`}>{it.value}</dd>
        </div>
      ))}
    </dl>
  )
}

/** 세 줄 안내: 아이콘 | 굵은 구절 | 설명 문장. 구절 열은 가장 긴 구절 폭에 맞춰져 설명이 한 줄로 가지런히 선다.
 *  굵은 구절과 설명은 서로 다른 정보를 맡는다 (구절을 풀어 쓴 설명은 두 번 읽게 할 뿐이다). */
export function Notes({ id, rows }: { id?: string; rows: { icon: Icon; title: string; text: string }[] }) {
  return (
    <ul id={id} className="mx-5 mt-[18px] grid grid-cols-[18px_max-content_1fr] items-center gap-x-2.5 gap-y-2.5 text-13">
      {rows.map((r) => (
        <li key={r.title} className="contents">
          <r.icon className="size-[18px] text-sub" aria-hidden="true" />
          <b className="whitespace-nowrap pr-2.5 font-bold text-main">{r.title}</b>
          <span className="text-body">{r.text}</span>
        </li>
      ))}
    </ul>
  )
}

const summaryClass = "inline-flex min-h-8 cursor-pointer list-none items-center gap-1 rounded-chip px-1.5 text-13 font-semibold text-sub transition hover:bg-sunken hover:text-main focus:outline-none focus-visible:ring-2 focus-visible:ring-focus [&::-webkit-details-marker]:hidden"

/** 접어 두는 안내 (필요한 사람만 펼친다) */
export function More({ label, children, className = "" }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <details className={`group ${className}`}>
      <summary className={summaryClass}>{label}<ChevronDown className="size-4 transition-transform group-open:rotate-180" aria-hidden="true" /></summary>
      {children}
    </details>
  )
}

/** 실패 안내: 원인 한 줄(+ 문제가 된 값) · 확인할 것 한 줄 · 자세한 오류 */
export function ErrorNote({ id, error }: { id?: string; error: ProposedConnectionError }) {
  const c = errorCopy(error)
  return (
    <div id={id} role="alert" className="mx-5 mt-4">
      <p className="flex items-start gap-1.5 text-14 font-semibold text-danger">
        <AlertCircle className="mt-1 size-4 shrink-0" aria-hidden="true" />
        <span>{c.title}{c.value ? <>: <code className="break-all font-mono text-13 font-normal">{c.value}</code></> : "."}</span>
      </p>
      {c.fix && <p className="ml-[22px] mt-0.5 text-14 text-body">{c.fix}</p>}
      {c.raw && <More label="자세한 오류 보기" className="ml-4 mt-2.5"><p className="mt-1.5 break-all rounded-chip bg-sunken px-3 py-2.5 font-mono text-12 text-body">{c.raw}</p></More>}
    </div>
  )
}

/** 연결 상태 표시 */
export function StateChip({ connected }: { connected: boolean }) {
  return connected
    ? <span className="inline-flex h-7 shrink-0 items-center gap-1 whitespace-nowrap rounded-full bg-success-tint px-2.5 text-12 font-semibold text-success"><CheckCircle2 className="size-3.5" aria-hidden="true" />연결됨</span>
    : <span className="inline-flex h-7 shrink-0 items-center whitespace-nowrap rounded-full bg-sunken px-2.5 text-12 font-semibold text-sub">연결 전</span>
}

/** 흐름의 큰 버튼 (공용 Button 보다 크다: 한 화면에 할 일이 하나라서) */
export const primaryBig = "inline-flex min-h-[52px] min-w-[148px] items-center justify-center gap-2 whitespace-nowrap rounded-control bg-accent px-6 text-[16px] font-bold text-on-accent transition hover:bg-accent-hover focus:outline-none focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-[#d1d6db]"
export const ghostBig = "-ml-4 inline-flex min-h-[52px] items-center whitespace-nowrap rounded-control px-4 text-15 font-semibold text-body transition hover:bg-sunken-hover focus:outline-none focus-visible:ring-2 focus-visible:ring-focus"
export const linkClass = "inline-flex items-center gap-1 whitespace-nowrap rounded text-13 font-semibold text-accent hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-focus"
