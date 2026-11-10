import { useState } from "react"
import { Check, SendHorizontal } from "lucide-react"
import type { ProposedChatAnswer, ProposedChatQuestion } from "../../../api/proposed"
import { money } from "../format"

// 대화형 설정의 답하기. 메신저 챗봇처럼 두 군데로 나눈다.
// - QuickReplies: 마지막 질문 바로 아래, 내 쪽(오른쪽)에 뜨는 보기 (누르면 바로 보냄 · 여러 개 고르기는 「선택 완료」).
//   설명 없는 보기는 둥근 칩, 설명이 있는 보기(성향·시장·종목 기준)는 설명을 읽을 수 있게 카드.
// - Composer: 창 맨 아래 입력줄. 금액·숫자 질문이면 직접 입력, 아니면 「위 보기에서 골라 주세요」 안내.
// 답은 서버(지금은 목업)가 검사해 다시 물을지 정한다.

type Answer = Omit<ProposedChatAnswer, "question_id">
type Option = ProposedChatQuestion["options"][number]

const NUM = /^\d+(\.\d+)?$/

/** 천·백·십 단위까지 붙은 숫자 글 (「5천」「1천5백」「2000」). 못 읽으면 null. */
function smallUnits(s: string): number | null {
  let rest = s, total = 0
  for (const [u, mul] of [["천", 1000], ["백", 100], ["십", 10]] as const) {
    const i = rest.indexOf(u)
    if (i < 0) continue
    const part = rest.slice(0, i)
    if (part !== "" && !NUM.test(part)) return null
    total += (part === "" ? 1 : Number(part)) * mul
    rest = rest.slice(i + 1)
  }
  if (rest === "") return total
  return NUM.test(rest) ? total + Number(rest) : null
}

/** 금액 글을 원 단위 숫자로: 「2천만원」「1억 5천만」「2,000만」「1.5억」「20000000」. 못 읽으면 null. */
export function parseKrw(input: string): number | null {
  let rest = input.replace(/[\s,원₩]/g, ""), total = 0
  if (rest === "") return null
  for (const [u, mul] of [["억", 1e8], ["만", 1e4]] as const) {
    const i = rest.indexOf(u)
    if (i < 0) continue
    const n = smallUnits(rest.slice(0, i) || "1")
    if (n === null) return null
    total += n * mul
    rest = rest.slice(i + 1)
  }
  if (rest !== "") { const n = smallUnits(rest); if (n === null) return null; total += n }
  return Math.round(total)
}

/** 숫자 질문(기간·종목 수)의 글: 「3」「3년」「10개」. 소수점은 그대로 둔다 (정수가 아니면 서버가 「정수로 알려 주세요」로 다시 묻는다). */
export function parseCount(input: string): number | null {
  const t = input.replace(/[\s,년개종목]/g, "")
  return NUM.test(t) ? Number(t) : null
}

function Chip({ o, pressed, disabled, onClick }: { o: Option; pressed?: boolean; disabled: boolean; onClick: () => void }) {
  const card = !!o.help_ko
  return (
    <button type="button" aria-pressed={pressed} disabled={disabled} onClick={onClick}
      className={`${card ? "rounded-2xl px-3.5 py-2.5 text-left" : "rounded-full px-4 py-2"} border text-sm shadow-sm transition focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50 ${pressed ? "border-blue-500 bg-blue-50 text-blue-900" : "border-blue-200 bg-white text-blue-800 hover:border-blue-400 hover:bg-blue-50"}`}>
      <span className={`flex items-center gap-2 ${card ? "font-semibold text-slate-900" : "font-medium"}`}>
        {pressed && <Check className="size-4 shrink-0 text-blue-700" aria-hidden />}
        <span>{o.label_ko}</span>
        {o.recommended && <span className="shrink-0 rounded-md bg-blue-100 px-1.5 py-px text-[11px] font-bold text-blue-800">추천</span>}
      </span>
      {card && <span className="mt-1 block text-xs leading-5 text-slate-500">{o.help_ko}</span>}
    </button>
  )
}

const skipChip = (q: ProposedChatQuestion, busy: boolean, onAnswer: (a: Answer) => void) =>
  q.allow_skip && <button type="button" disabled={busy} onClick={() => onAnswer({ skip: true })} className="rounded-full px-3 py-2 text-sm text-slate-500 hover:bg-slate-100 hover:text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50">건너뛰기 (기본값 사용)</button>

/** 마지막 질문 아래 내 쪽에 뜨는 보기. */
export function QuickReplies({ q, busy, onAnswer }: { q: ProposedChatQuestion; busy: boolean; onAnswer: (a: Answer) => void }) {
  const [picked, setPicked] = useState<unknown[]>([])
  const cards = q.options.some((o) => o.help_ko)
  const wrap = cards ? "grid w-full max-w-[85%] gap-2 sm:grid-cols-2" : "flex max-w-[85%] flex-wrap justify-end gap-2"
  const hint = q.kind === "multi" ? "여러 개 골라도 돼요" : q.kind === "money" || q.kind === "number" ? "골라 주시거나 아래에 직접 적어 주세요" : "골라 주세요"

  if (q.kind === "multi") {
    const toggle = (v: unknown) => setPicked((xs) => (xs.includes(v) ? xs.filter((x) => x !== v) : [...xs, v]))
    return (
      <div role="group" aria-label={`${q.field_label_ko} 보기`} className="chat-in flex flex-col items-end gap-2 pt-1">
        <p className="text-[11px] font-medium text-slate-400">{hint}</p>
        <div className={wrap}>{q.options.map((o) => <Chip key={String(o.value)} o={o} pressed={picked.includes(o.value)} disabled={busy} onClick={() => toggle(o.value)} />)}</div>
        <div className="flex items-center gap-2">
          {skipChip(q, busy, onAnswer)}
          <button type="button" disabled={busy || picked.length === 0} onClick={() => onAnswer({ option_value: q.options.map((o) => o.value).filter((v) => picked.includes(v)) })}
            className="inline-flex items-center gap-1.5 rounded-full bg-blue-700 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-40">
            <Check className="size-4" aria-hidden />선택 완료 ({picked.length})
          </button>
        </div>
      </div>
    )
  }
  return (
    <div role="group" aria-label={`${q.field_label_ko} 보기`} className="chat-in flex flex-col items-end gap-2 pt-1">
      <p className="text-[11px] font-medium text-slate-400">{hint}</p>
      <div className={wrap}>{q.options.map((o) => <Chip key={String(o.value)} o={o} disabled={busy} onClick={() => onAnswer({ option_value: o.value })} />)}</div>
      {skipChip(q, busy, onAnswer)}
    </div>
  )
}

/** 창 맨 아래 입력줄. 직접 입력을 받는 질문(금액·숫자)에서만 쓸 수 있다. */
export function Composer({ q, busy, waitingText, onAnswer }: { q: ProposedChatQuestion | null; busy: boolean; waitingText?: string; onAnswer: (a: Answer) => void }) {
  const [text, setText] = useState("")
  const typed = !!q && (q.kind === "money" || q.kind === "number")
  const isMoney = q?.kind === "money"
  const unit = q?.input?.unit_ko ?? ""
  const n = text.trim() === "" ? null : isMoney ? parseKrw(text) : parseCount(text)
  const unreadable = text.trim() !== "" && n === null
  const range = q?.input ? (isMoney ? `${money(q.input.min, "KRW")} ~ ${money(q.input.max, "KRW")}` : `${q.input.min}~${q.input.max}${unit}`) : ""
  const example = isMoney ? "예: 2000만원, 20000000" : "예: 3"
  const placeholder = waitingText ?? (typed ? `숫자로 적어 주세요 (${example}) · ${range}` : "위 보기에서 골라 주세요")
  const off = busy || !typed || !!waitingText
  return (
    <form className="flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (q && typed && n !== null) { onAnswer({ number: n }); setText("") } }}>
      <label className="relative min-w-0 flex-1">
        <input aria-label={q && typed ? `${q.field_label_ko} 직접 입력` : "답 입력"} inputMode={isMoney ? "text" : "decimal"} autoComplete="off" disabled={off} placeholder={placeholder}
          value={text} onChange={(e) => setText(e.target.value)} aria-invalid={unreadable || undefined}
          className="h-11 w-full rounded-full border border-slate-300 bg-slate-50 pl-4 pr-24 text-sm text-slate-900 placeholder:text-slate-400 focus:border-blue-500 focus:bg-white focus:outline-none focus:ring-2 focus:ring-blue-200 disabled:cursor-not-allowed disabled:bg-slate-100" />
        <span className="pointer-events-none absolute inset-y-0 right-4 flex items-center gap-2 text-xs text-slate-500">
          {unreadable ? <span className="font-semibold text-amber-700">숫자로 적어 주세요</span>
            : n !== null && <span className="font-semibold text-blue-700">{isMoney ? money(n, "KRW") : n}</span>}
          {typed && unit}
        </span>
      </label>
      <button type="submit" aria-label="보내기" disabled={off || n === null}
        className="grid size-11 shrink-0 place-items-center rounded-full bg-blue-700 text-white shadow-sm transition hover:bg-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:bg-slate-300">
        <SendHorizontal className="size-4" aria-hidden />
      </button>
    </form>
  )
}
