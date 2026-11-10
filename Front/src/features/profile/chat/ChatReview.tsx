import { PencilLine, RotateCcw, Save } from "lucide-react"
import type { ProposedProfileChat } from "../../../api/proposed"
import { Alert, Button, Disclosure } from "../../../ui"
import { profileRows, type ProfileRow } from "../compare"
import { validateProfile } from "../validate"

// 대화형 설정의 마지막 단계: 답한 값 · 답에 맞춰 정한 값(이유와 함께) · 기본값으로 둔 값을 나눠 보여 주고 저장한다. 검사는 4단계 폼과 같은 규칙(validateProfile).
// 요약 카드는 대화 안(봇 말풍선 자리)에, 저장 버튼 줄은 대화창 아래 입력 자리에 둔다 → 요약이 길어도 저장 버튼은 늘 보인다.

function Rows({ rows, notes }: { rows: ProfileRow[]; notes?: Record<string, string> }) {
  return (
    <dl className="grid grid-cols-1 gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
      {rows.map((r) => <div key={r.key} className="min-w-0"><dt className="text-xs font-semibold text-slate-500">{r.label}</dt><dd className="mt-0.5 break-words font-semibold text-slate-900">{r.value}</dd>{notes?.[r.key] && <dd className="mt-0.5 text-xs leading-5 text-slate-500">{notes[r.key]}</dd>}</div>)}
    </dl>
  )
}

const errorsOf = (chat: ProposedProfileChat, allowZero: boolean) => Object.values(validateProfile(chat.draft, { allowZero }))

export function ChatReviewSummary({ chat, allowZero }: { chat: ProposedProfileChat; allowZero: boolean }) {
  const rows = profileRows(chat.draft)
  const notes = chat.derived_fields ?? {}
  const asked = rows.filter((r) => chat.asked_fields.includes(r.key) && !(r.key in notes))
  const derived = rows.filter((r) => r.key in notes)
  const rest = rows.filter((r) => !chat.asked_fields.includes(r.key) && !(r.key in notes))
  const errors = errorsOf(chat, allowZero)
  return (
    <section aria-labelledby="chat-review-title" className="rounded-2xl rounded-tl-sm border border-blue-200 bg-white p-5 shadow-sm">
      <h2 id="chat-review-title" className="text-base font-bold text-slate-950">이렇게 정리했어요</h2>
      <p className="mt-1 text-sm text-slate-600">질문 {chat.progress.done}개에 답하신 내용입니다. 저장하면 기본 투자조건으로 기록됩니다.</p>
      <div className="mt-4"><Rows rows={asked} /></div>
      {derived.length > 0 && <div className="mt-5 border-t border-slate-100 pt-4"><h3 className="mb-3 text-sm font-bold text-slate-900">답에 맞춰 정한 조건 {derived.length}개</h3><Rows rows={derived} notes={notes} /></div>}
      <Disclosure className="mt-4" size="sm" title="기본값으로 둔 조건" summary={`${rest.length}개 · 저장한 뒤에도 바꿀 수 있습니다`}>
        <div className="pt-3"><Rows rows={rest} /></div>
      </Disclosure>
      {errors.length > 0 && <div className="mt-4"><Alert tone="error" title="저장하기 전에 고칠 항목이 있습니다"><ul className="list-disc pl-5">{errors.map((e) => <li key={e}>{e}</li>)}</ul></Alert></div>}
    </section>
  )
}

export function ChatReviewActions({ chat, allowZero, busy, saveError, onSave, onEditInForm, onRestart }: {
  chat: ProposedProfileChat; allowZero: boolean; busy: boolean; saveError: string
  onSave: () => void; onEditInForm: () => void; onRestart: () => void
}) {
  const blocked = errorsOf(chat, allowZero).length > 0
  return (
    <div className="space-y-3">
      {saveError && <Alert tone="error" title="저장하지 못했습니다">{saveError}</Alert>}
      <div className="flex flex-wrap items-center gap-2">
        <Button disabled={busy || blocked} onClick={onSave}><Save className="size-4" aria-hidden />이대로 저장</Button>
        <Button variant="secondary" disabled={busy} onClick={onEditInForm}><PencilLine className="size-4" aria-hidden />폼에서 세부 수정</Button>
        <Button variant="ghost" disabled={busy} onClick={onRestart}><RotateCcw className="size-4" aria-hidden />처음부터 다시</Button>
      </div>
    </div>
  )
}
