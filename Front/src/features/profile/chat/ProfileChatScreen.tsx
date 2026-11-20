import { useEffect, useRef, useState } from "react"
import { ListChecks } from "lucide-react"
import { useProfile, useService } from "../../../app/providers"
import { navigate } from "../../../app/router"
import { errorMessage } from "../../../api/client"
import { proposedRulesOf, type ProposedChatAnswer, type ProposedChatMessage, type ProposedChatQuestion, type ProposedProfileChat } from "../../../api/proposed"
import type { ProfileView } from "../../../api/types"
import { useResource } from "../../../state/useResource"
import { loadUi, saveUi } from "../../../state/uiStorage"
import { Alert, Button, ErrorState, Loading } from "../../../ui"
import { MockTag } from "../../report/proposedView"
import { money } from "../format"
import { ProfileScreen } from "../ProfileScreen"
import { Composer, QuickReplies } from "./ChatInput"
import { ChatReviewActions, ChatReviewSummary } from "./ChatReview"
import { Typing } from "../../home/chatParts"

// 대화형 초기 투자조건 (제안 기능): 서비스에 대화 메서드(startProfileChat 등)가 있을 때만 — 목업과 실제 서버(POST /profile/chat …) 모두.
// 없으면 기존 4단계 폼으로 연다. 대화는 초안만 만들고, 저장은 기존 saveProfile 로 한다.
//
// 모양은 메신저 창 하나: 위 막대(도우미·진행) / 가운데 대화(이 영역만 스크롤) / 아래 입력줄(요약 단계에선 저장 버튼).
// 보기는 마지막 질문 바로 아래 내 쪽에 「추천 답장」처럼 뜨고, 입력줄은 금액·숫자 직접 입력에만 쓴다.
// 대화는 아래부터 쌓이고(메신저처럼), 창 높이를 화면에 맞춰 두어 대화가 길어져도 브라우저 페이지는 스크롤되지 않는다.

type Answer = Omit<ProposedChatAnswer, "question_id">

export function ProfileChatScreen() {
  const svc = useService()
  const { profile, status, error, reload, set } = useProfile()
  if (!svc.startProfileChat || !svc.answerProfileChat || !svc.rewindProfileChat) return <ProfileScreen mode={profile ? "edit" : "setup"} />
  if (status === "loading") return <Loading />
  if (status === "error") return <ErrorState title="분석 서버에 연결할 수 없습니다" message={`${error ?? ""} 서버가 켜지면 다시 시작합니다.`} retry={() => void reload()} />
  return <ChatFlow hasProfile={!!profile} onSaved={(v) => { set(v); void reload(); navigate({ page: "home" }) }} />
}

/** 서버 응답 전에 바로 띄우는 내 답 말풍선 문구 (응답이 오면 서버 문구로 바뀐다). */
function answerLabel(q: ProposedChatQuestion, a: Answer) {
  if (a.skip) return "건너뛸게요 (기본값 사용)"
  if (a.number != null) return q.kind === "money" ? money(a.number, "KRW") : `${a.number}${q.input?.unit_ko ?? ""}`
  const v = a.option_value
  if (Array.isArray(v)) return q.options.filter((o) => v.includes(o.value)).map((o) => o.label_ko).join(", ")
  return q.options.find((o) => o.value === v)?.label_ko ?? ""
}

/** 말풍선 모양은 홈 대화창(features/home/chatParts)과 같다: 아이콘 없음, 도우미는 회색 면(bubble) · 위 모서리 직각, 나는 파란 면 · 오른쪽 위 직각 (2026-11-18). */
function Bubble({ m, first, onEdit, children }: { m: ProposedChatMessage; first: boolean; onEdit?: () => void; children?: React.ReactNode }) {
  if (m.role === "bot") return (
    <li className={`chat-in flex ${first ? "pt-2" : ""}`}>
      <div className={`${children ? "w-full max-w-[85%] pb-3" : "max-w-[80%]"} rounded-bubble rounded-tl-none bg-bubble px-4 py-2.5 text-14 leading-6 text-main`}>
        <p className="whitespace-pre-line"><span className="sr-only">도우미: </span>{m.text_ko}</p>
        {children && <div className="mt-2.5">{children}</div>}
      </div>
    </li>
  )
  return (
    <li className="chat-in flex items-end justify-end gap-2 pt-2">
      {onEdit && <button type="button" onClick={onEdit} aria-label={`‘${m.text_ko}’ 답 고치기`} className="mb-1 shrink-0 rounded-chip px-1 text-12 text-sub hover:text-accent hover:underline">고치기</button>}
      <p className="max-w-[75%] rounded-bubble rounded-tr-none bg-accent px-4 py-2.5 text-14 leading-6 text-on-accent"><span className="sr-only">내 답: </span>{m.text_ko}</p>
    </li>
  )
}

function ChatFlow({ hasProfile, onSaved }: { hasProfile: boolean; onSaved: (v: ProfileView) => void }) {
  const svc = useService()
  const options = useResource(() => svc.options(), [svc])
  const allowZero = !!proposedRulesOf(options.data)?.allow_zero_initial_amount
  const [chat, setChat] = useState<ProposedProfileChat | null>(null)
  const [busy, setBusy] = useState(false)
  const [typing, setTyping] = useState(false)           // 봇 응답을 기다리는 중 (「…」)
  const [pending, setPending] = useState<string | null>(null)  // 보냈지만 아직 응답이 없는 내 답
  const [error, setError] = useState("")
  const [saveError, setSaveError] = useState("")
  const started = useRef(false)
  const listRef = useRef<HTMLDivElement>(null)
  const reviewRef = useRef<HTMLLIElement>(null)

  const run = async (f: () => Promise<ProposedProfileChat>) => {
    setBusy(true); setTyping(true); setError("")
    try { setChat(await f()) } catch (e) { setError(errorMessage(e)) } finally { setBusy(false); setTyping(false); setPending(null) }
  }
  const start = () => { saveUi({ profileChat: null }); setChat(null); return run(() => svc.startProfileChat!()) }
  useEffect(() => {  // 처음 한 번만 (개발 모드 이중 실행에도 대화 하나). 폼에 다녀왔으면 그때의 대화에서 이어 간다.
    if (started.current) return
    started.current = true
    const saved = loadUi().profileChat
    if (saved) setChat(saved); else void start()
  }, [])
  // 새 말이 붙으면 대화 영역 안에서만 아래로 내린다 (scrollIntoView 는 브라우저 페이지까지 움직여서 쓰지 않는다).
  // 요약 단계에서는 요약 카드 머리가 보이게 맞춘다.
  useEffect(() => {
    const el = listRef.current
    if (!el) return
    const top = chat?.state === "review" && reviewRef.current ? Math.max(0, reviewRef.current.offsetTop - 120) : el.scrollHeight
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
    el.scrollTo?.({ top, behavior: reduce ? "auto" : "smooth" })
  }, [chat?.messages.length, chat?.state, pending, typing])

  const answer = (a: Answer) => {
    const q = chat?.question
    if (!chat || !q) return
    setPending(answerLabel(q, a))
    void run(() => svc.answerProfileChat!(chat.chat_id, { question_id: q.id, ...a }))
  }
  const rewind = (questionId: string) => { if (chat) void run(() => svc.rewindProfileChat!(chat.chat_id, questionId)) }
  const toForm = () => { saveUi({ profileDraft: chat && chat.asked_fields.length ? chat.draft : null, profileChat: chat?.progress.done ? chat : null }); navigate({ page: "profile", mode: hasProfile ? "edit" : "setup" }) }
  const save = async () => {
    if (!chat) return
    setBusy(true); setSaveError("")
    try { const v = await svc.saveProfile({ ...chat.draft, note: hasProfile ? "대화로 다시 설정" : "첫 등록" }); saveUi({ profileDraft: null, profileChat: null }); onSaved(v) }
    catch (e) { setSaveError(`${errorMessage(e)} 답한 내용은 그대로 있습니다.`) }
    finally { setBusy(false) }
  }

  const done = chat?.progress.done ?? 0, total = chat?.progress.total ?? 11
  const msgs = chat?.messages ?? []
  // 보기는 지금 질문을 묻는 마지막 도우미 말풍선 안에 넣는다 (홈 대화창과 같은 구조). 그런 말풍선이 없으면 따로 회색 말풍선으로
  const openQ = chat?.question && !typing && !pending ? chat.question : null
  const last = msgs[msgs.length - 1]
  const qAt = openQ && last?.role === "bot" && last.question_id === openQ.id ? msgs.length - 1 : -1
  return (
    <div className="profile-chat mx-auto max-w-3xl">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between sm:gap-8">
        <div className="min-w-0">
          <p className="mb-2 flex items-center text-12 font-bold tracking-widest text-accent">{hasProfile ? "다시 설정" : "처음 설정"}<MockTag /></p>
          <h1 className="t-display">내 프로필을 정해봅시다</h1>
          <p className="mt-2 t-body">질문 {total}개에 답하면 마지막에 한 번에 확인하고 저장합니다.</p>
        </div>
        <div className="flex shrink-0 gap-2"><Button variant="neutral" disabled={busy} onClick={toForm}><ListChecks className="size-4" aria-hidden />폼으로 한 번에 입력</Button></div>
      </header>

      {/* 이미 투자조건이 있으면 (수정 화면의 「대화로 다시 설정」, 2026-11-18): 대화는 기본값에서 다시 시작한다는 것을 먼저 알린다 */}
      {hasProfile && <Alert tone="info" className="mt-5" title={`질문 ${total}개에 처음부터 답해요`}>묻지 않은 항목은 기본값으로 정해져요. 마지막에 「이대로 저장」을 누르기 전까지 지금 투자조건은 그대로예요.</Alert>}

      {/* 대화창: 높이를 화면에 맞춰 고정 → 페이지 대신 가운데 대화 영역만 스크롤 */}
      <div className="mt-5 flex flex-col overflow-hidden rounded-card bg-surface" style={{ height: hasProfile ? "clamp(24rem, calc(100vh - 21rem), 46rem)" : "clamp(26rem, calc(100vh - 15rem), 48rem)" }}  /* 다시 설정 안내가 있으면 그 높이만큼 줄여 입력줄이 화면 안에 */>
        <div className="flex shrink-0 items-center gap-3 border-b border-line px-6 py-3.5">
          <div className="min-w-0 flex-1">
            <p className="t-title">투자조건 도우미</p>
            <p className="t-meta">{chat?.state === "review" ? "모두 답했어요 · 확인하고 저장해 주세요" : chat?.question ? `지금 묻는 것: ${chat.question.field_label_ko}` : "대화를 준비하고 있어요"}</p>
          </div>
          <div className="flex w-40 shrink-0 items-center gap-2">
            <div role="progressbar" aria-label="답한 질문" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done} className="h-1.5 flex-1 overflow-hidden rounded-full bg-line">
              <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${Math.round((done / total) * 100)}%` }} />
            </div>
            <span className="text-12 font-semibold tabular-nums text-sub">{done}/{total}</span>
          </div>
        </div>

        <div ref={listRef} className="relative min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pb-4 pt-2">
          <section aria-label="대화" className="flex min-h-full flex-col justify-end">
            <ol aria-live="polite" className="space-y-2">
              {msgs.map((m, i) => <Bubble key={m.id} m={m} first={m.role === "bot" && msgs[i - 1]?.role !== "bot"} onEdit={m.editable && m.question_id && !busy ? () => rewind(m.question_id!) : undefined}>
                {i === qAt && openQ && <QuickReplies key={openQ.id} q={openQ} busy={busy} onAnswer={answer} />}
              </Bubble>)}
              {pending && <li className="flex justify-end pt-2"><p className="max-w-[75%] rounded-bubble rounded-tr-none bg-accent px-4 py-2.5 text-14 leading-6 text-on-accent opacity-70"><span className="sr-only">내 답: </span>{pending}</p></li>}
              {typing && <Typing label="답 확인 중…" />}
              {openQ && qAt < 0 && <li className="chat-in flex"><div className="w-full max-w-[85%] rounded-bubble rounded-tl-none bg-bubble px-4 py-3"><QuickReplies key={openQ.id} q={openQ} busy={busy} onAnswer={answer} /></div></li>}
              {chat?.state === "review" && !typing && <li ref={reviewRef} className="chat-in flex pt-2"><div className="min-w-0 flex-1"><ChatReviewSummary chat={chat} allowZero={allowZero} /></div></li>}
            </ol>
          </section>
        </div>

        <section aria-label={chat?.state === "review" ? "저장" : "답하기"} className="shrink-0 border-t border-line px-4 py-3">
          {error && <div className="mb-3"><Alert tone="error" title="대화를 이어가지 못했습니다">{error} <button type="button" className="font-semibold underline" onClick={() => void start()}>처음부터 다시 시작</button></Alert></div>}
          {chat?.state === "review" && !typing
            ? <ChatReviewActions chat={chat} allowZero={allowZero} busy={busy} saveError={saveError} onSave={() => void save()} onEditInForm={toForm} onRestart={() => void start()} />
            : <Composer key={chat?.question?.id ?? "none"} q={chat?.question ?? null} busy={busy} onAnswer={answer}
                waitingText={!chat ? "대화를 준비하고 있어요…" : typing ? "도우미가 답하는 중…" : undefined} />}
        </section>
      </div>
    </div>
  )
}
