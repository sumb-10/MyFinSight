import { useState } from "react"
import { Check, SendHorizontal } from "lucide-react"
import type { ProposedChatAnswer, ProposedChatQuestion } from "../../../api/proposed"
import { Button, inputClass } from "../../../ui"
import { money } from "../format"

// 대화형 설정의 답 입력. 질문 종류(kind)마다 모양만 다르고, 답은 서버(지금은 목업)가 검사해 다시 물을지 정한다.
// choice = 보기를 누르면 바로 보냄 · multi = 여러 개 고르고 「선택 완료」 · money/number = 빠른 보기 + 직접 입력.

type Answer = Omit<ProposedChatAnswer, "question_id">
type Option = ProposedChatQuestion["options"][number]

const digits = (s: string) => s.replace(/[^\d]/g, "")
const grouped = (s: string) => (s ? Number(s).toLocaleString("ko-KR") : "")

function OptionButton({ o, pressed, disabled, onClick }: { o: Option; pressed?: boolean; disabled: boolean; onClick: () => void }) {
  return (
    <button type="button" aria-pressed={pressed} disabled={disabled} onClick={onClick}
      className={`rounded-xl border px-3.5 py-2.5 text-left text-sm transition focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50 ${pressed ? "border-blue-400 bg-blue-50 text-blue-900" : "border-slate-200 bg-white text-slate-800 hover:border-blue-200 hover:bg-blue-50/40"}`}>
      <span className="flex items-center gap-2 font-semibold">
        {pressed && <Check className="size-4 shrink-0 text-blue-700" aria-hidden />}
        <span>{o.label_ko}</span>
        {o.recommended && <span className="shrink-0 rounded-md bg-blue-100 px-1.5 py-px text-[11px] font-bold text-blue-800">추천</span>}
      </span>
      {o.help_ko && <span className="mt-1 block text-xs leading-5 text-slate-500">{o.help_ko}</span>}
    </button>
  )
}

export function ChatInput({ q, busy, onAnswer }: { q: ProposedChatQuestion; busy: boolean; onAnswer: (a: Answer) => void }) {
  const [picked, setPicked] = useState<unknown[]>([])
  const [text, setText] = useState("")
  const skip = q.allow_skip && <Button variant="ghost" disabled={busy} onClick={() => onAnswer({ skip: true })}>건너뛰기 (기본값 사용)</Button>

  if (q.kind === "choice") return (
    <div className="space-y-3">
      <div className={`grid gap-2 ${q.options.some((o) => o.help_ko) ? "sm:grid-cols-2" : "sm:grid-cols-4"}`}>
        {q.options.map((o) => <OptionButton key={String(o.value)} o={o} disabled={busy} onClick={() => onAnswer({ option_value: o.value })} />)}
      </div>
      {skip}
    </div>
  )

  if (q.kind === "multi") {
    const toggle = (v: unknown) => setPicked((xs) => (xs.includes(v) ? xs.filter((x) => x !== v) : [...xs, v]))
    return (
      <div className="space-y-3">
        <div className="grid gap-2 sm:grid-cols-3">
          {q.options.map((o) => <OptionButton key={String(o.value)} o={o} pressed={picked.includes(o.value)} disabled={busy} onClick={() => toggle(o.value)} />)}
        </div>
        <div className="flex items-center gap-3">
          <Button disabled={busy || picked.length === 0} onClick={() => onAnswer({ option_value: q.options.map((o) => o.value).filter((v) => picked.includes(v)) })}><Check className="size-4" aria-hidden />선택 완료 ({picked.length})</Button>
          {skip}
        </div>
      </div>
    )
  }

  // money · number: 빠른 보기 + 직접 입력
  const unit = q.input?.unit_ko ?? ""
  const isMoney = q.kind === "money"
  const n = text === "" ? null : Number(text)
  const range = q.input ? (isMoney ? `${money(q.input.min, "KRW")} ~ ${money(q.input.max, "KRW")}` : `${q.input.min}~${q.input.max}${unit}`) : ""
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {q.options.map((o) => <OptionButton key={String(o.value)} o={o} disabled={busy} onClick={() => onAnswer({ option_value: o.value })} />)}
      </div>
      <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (n !== null) onAnswer({ number: n }) }}>
        <label className="block min-w-0 flex-1">
          <span className="mb-1 block text-xs font-semibold text-slate-600">직접 입력 <span className="font-normal text-slate-500">({range})</span></span>
          <span className="relative block">
            <input aria-label={`${q.field_label_ko} 직접 입력`} inputMode="numeric" autoComplete="off" disabled={busy} value={isMoney ? grouped(text) : text}
              onChange={(e) => setText(digits(e.target.value))} className={`${inputClass} pr-12`} />
            <span className="pointer-events-none absolute inset-y-0 right-3.5 flex items-center text-sm text-slate-500">{unit}</span>
          </span>
        </label>
        <Button type="submit" disabled={busy || n === null}><SendHorizontal className="size-4" aria-hidden />보내기</Button>
      </form>
      {isMoney && n !== null && <p className="text-xs text-slate-500">{money(n, "KRW")}</p>}
      {skip}
    </div>
  )
}
