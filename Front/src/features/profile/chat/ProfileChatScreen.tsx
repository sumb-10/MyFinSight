import { useEffect, useRef, useState } from "react"
import { Bot, ListChecks } from "lucide-react"
import { useProfile, useService } from "../../../app/providers"
import { navigate } from "../../../app/router"
import { errorMessage } from "../../../api/client"
import { proposedRulesOf, type ProposedChatAnswer, type ProposedChatMessage, type ProposedProfileChat } from "../../../api/proposed"
import type { ProfileView } from "../../../api/types"
import { useResource } from "../../../state/useResource"
import { loadUi, saveUi } from "../../../state/uiStorage"
import { Alert, Button, ErrorState, Loading } from "../../../ui"
import { MockTag } from "../../report/proposedView"
import { ProfileScreen } from "../ProfileScreen"
import { ChatInput } from "./ChatInput"
import { ChatReview } from "./ChatReview"

// 대화형 초기 투자조건 (제안 기능): 서비스에 대화 메서드(startProfileChat 등)가 있을 때만 — 지금은 목업뿐.
// 없으면(실제 서버) 기존 4단계 폼으로 연다. 대화는 초안만 만들고, 저장은 기존 saveProfile 로 한다.

export function ProfileChatScreen() {
  const svc = useService()
  const { profile, status, error, reload, set } = useProfile()
  if (!svc.startProfileChat || !svc.answerProfileChat || !svc.rewindProfileChat) return <ProfileScreen mode={profile ? "edit" : "setup"} />
  if (status === "loading") return <Loading />
  if (status === "error") return <ErrorState title="분석 서버에 연결할 수 없습니다" message={`${error ?? ""} 서버가 켜지면 다시 시작합니다.`} retry={() => void reload()} />
  return <ChatFlow hasProfile={!!profile} onSaved={(v) => { set(v); void reload(); navigate({ page: "home" }) }} />
}

function Bubble({ m, onEdit }: { m: ProposedChatMessage; onEdit?: () => void }) {
  if (m.role === "bot") return (
    <li className="flex gap-2.5">
      <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-full bg-blue-50 text-blue-700"><Bot className="size-4" aria-hidden /></span>
      <p className="max-w-[78%] whitespace-pre-line rounded-2xl rounded-tl-sm bg-slate-100 px-4 py-2.5 text-sm leading-6 text-slate-800"><span className="sr-only">도우미: </span>{m.text_ko}</p>
    </li>
  )
  return (
    <li className="flex flex-col items-end gap-1">
      <p className="max-w-[78%] rounded-2xl rounded-tr-sm bg-blue-700 px-4 py-2.5 text-sm leading-6 text-white"><span className="sr-only">내 답: </span>{m.text_ko}</p>
      {onEdit && <button type="button" onClick={onEdit} aria-label={`‘${m.text_ko}’ 답 고치기`} className="rounded px-1 text-xs text-slate-500 hover:text-blue-700 hover:underline focus:outline-none focus:ring-2 focus:ring-blue-500">고치기</button>}
    </li>
  )
}

function ChatFlow({ hasProfile, onSaved }: { hasProfile: boolean; onSaved: (v: ProfileView) => void }) {
  const svc = useService()
  const options = useResource(() => svc.options(), [svc])
  const allowZero = !!proposedRulesOf(options.data)?.allow_zero_initial_amount
  const [chat, setChat] = useState<ProposedProfileChat | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [saveError, setSaveError] = useState("")
  const started = useRef(false)
  const endRef = useRef<HTMLDivElement>(null)

  const run = async (f: () => Promise<ProposedProfileChat>) => {
    setBusy(true); setError("")
    try { setChat(await f()) } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  const start = () => { saveUi({ profileChat: null }); return run(() => svc.startProfileChat!()) }
  useEffect(() => {  // 처음 한 번만 (개발 모드 이중 실행에도 대화 하나). 폼에 다녀왔으면 그때의 대화에서 이어 간다.
    if (started.current) return
    started.current = true
    const saved = loadUi().profileChat
    if (saved) setChat(saved); else void start()
  }, [])
  useEffect(() => { endRef.current?.scrollIntoView?.({ block: "end", behavior: "smooth" }) }, [chat?.messages.length, chat?.state])

  const answer = (a: Omit<ProposedChatAnswer, "question_id">) => { if (chat?.question) void run(() => svc.answerProfileChat!(chat.chat_id, { question_id: chat.question!.id, ...a })) }
  const rewind = (questionId: string) => { if (chat) void run(() => svc.rewindProfileChat!(chat.chat_id, questionId)) }
  const toForm = () => { saveUi({ profileDraft: chat && chat.asked_fields.length ? chat.draft : null, profileChat: chat?.progress.done ? chat : null }); navigate({ page: "profile", mode: hasProfile ? "edit" : "setup" }) }
  const save = async () => {
    if (!chat) return
    setBusy(true); setSaveError("")
    try { const v = await svc.saveProfile({ ...chat.draft, note: hasProfile ? "대화로 다시 설정" : "첫 등록" }); saveUi({ profileDraft: null, profileChat: null }); onSaved(v) }
    catch (e) { setSaveError(`${errorMessage(e)} 답한 내용은 그대로 있습니다.`) }
    finally { setBusy(false) }
  }

  const done = chat?.progress.done ?? 0, total = chat?.progress.total ?? 1
  return (
    <div className="mx-auto max-w-3xl">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between sm:gap-8">
        <div className="min-w-0">
          <p className="mb-2 flex items-center text-xs font-bold tracking-widest text-blue-700">처음 설정<MockTag /></p>
          <h1 className="text-3xl font-bold tracking-tight text-slate-950">대화로 기본 투자조건을 정해요</h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">질문 {total}개에 답하면 분석에 쓸 기본 투자조건을 만듭니다. 마지막에 한 번에 확인하고 저장합니다.</p>
        </div>
        <div className="flex shrink-0 gap-2"><Button variant="neutral" disabled={busy} onClick={toForm}><ListChecks className="size-4" aria-hidden />폼으로 한 번에 입력</Button></div>
      </header>

      <div className="mt-6 flex items-center gap-3">
        <div role="progressbar" aria-label="답한 질문" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done} className="h-2 flex-1 overflow-hidden rounded-full bg-slate-200">
          <div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${Math.round((done / total) * 100)}%` }} />
        </div>
        <span className="text-xs font-semibold tabular-nums text-slate-600">{done}/{total}</span>
      </div>

      {error && <div className="mt-4"><Alert tone="error" title="대화를 이어가지 못했습니다">{error} <button type="button" className="font-semibold underline" onClick={() => void start()}>처음부터 다시 시작</button></Alert></div>}

      <section aria-label="대화" className="mt-4 rounded-2xl border border-slate-200 bg-white p-5">
        {!chat ? <Loading label="대화를 준비하는 중…" /> : (
          <ol aria-live="polite" className="space-y-3">
            {chat.messages.map((m) => <Bubble key={m.id} m={m} onEdit={m.editable && m.question_id && !busy ? () => rewind(m.question_id!) : undefined} />)}
          </ol>
        )}
      </section>

      {chat?.question && (
        <section aria-label="답하기" className="mt-4 rounded-2xl border border-slate-200 bg-white p-5">
          <p className="mb-3 text-xs font-bold text-slate-500">{chat.question.field_label_ko}</p>
          <ChatInput key={chat.question.id} q={chat.question} busy={busy} onAnswer={answer} />
        </section>
      )}
      {chat?.state === "review" && (
        <div className="mt-4"><ChatReview chat={chat} allowZero={allowZero} busy={busy} saveError={saveError} onSave={() => void save()} onEditInForm={toForm} onRestart={() => void start()} /></div>
      )}
      <div ref={endRef} />
    </div>
  )
}
