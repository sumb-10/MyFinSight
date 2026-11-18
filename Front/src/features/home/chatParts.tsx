import { useEffect, useState, type ReactNode } from "react"
import { AlertCircle, AlertTriangle } from "lucide-react"

// 홈 대화창(RequestChat) 말풍선. 모양은 대화형 투자조건 설정(features/profile/chat/ProfileChatScreen.tsx)의 말풍선·입력 중 점을 본떴고,
// 색은 토큰(styles/tokens.css)으로 쓴다. 나타날 때 살짝 올라오는 .chat-in · 점 세 개 .chat-dot 은 index.css 의 공용 애니메이션.

/** 분석 모델 쪽 한 줄: 왼쪽 회색 말풍선 (꼬리 대신 말한 쪽 왼쪽 위 모서리만 직각, 2026-11-18).
 *  경고·오류(tone)도 면은 같은 회색이고 앞에 색 아이콘만 붙는다 (노랑·분홍 면은 대화창이 알록달록해 보여서). */
export function BotSays({ children, wide = false, tone = "plain" }: { children: ReactNode; wide?: boolean; tone?: "plain" | "warn" | "error" }) {
  const Icon = tone === "error" ? AlertCircle : tone === "warn" ? AlertTriangle : null
  return (
    <li className="chat-in flex">
      <div className={`min-w-0 rounded-bubble rounded-tl-none bg-bubble px-4 py-3 text-14 leading-6 text-main ${wide ? "flex-1" : "max-w-[85%]"} ${Icon ? "flex gap-2.5" : ""}`}>
        {Icon && <Icon className={`mt-1 size-4 shrink-0 ${tone === "error" ? "text-danger" : "text-warning"}`} aria-hidden="true" />}
        {Icon ? <div className="min-w-0 flex-1">{children}</div> : children}
      </div>
    </li>
  )
}

/** 내 쪽 한 줄: 오른쪽 파란 말풍선 (꼬리 대신 오른쪽 위 모서리만 직각). pending = 보냈지만 아직 서버가 답하지 않음 (조금 흐리게) */
export function ISay({ children, pending = false }: { children: ReactNode; pending?: boolean }) {
  return (
    <li className="chat-in flex justify-end">
      <p className={`max-w-[80%] whitespace-pre-line rounded-bubble rounded-tr-none bg-accent px-4 py-2.5 text-14 leading-6 text-on-accent ${pending ? "opacity-70" : ""}`}>{children}</p>
    </li>
  )
}

/** 화면에 나온 뒤 몇 초 지났는지 (1초마다 다시 그린다) */
export function useElapsed() {
  const [sec, setSec] = useState(0)
  useEffect(() => { const t = window.setInterval(() => setSec((s) => s + 1), 1000); return () => window.clearInterval(t) }, [])
  return sec
}

/** 기다림 표시의 점 세 개 (위아래로 튐, index.css .chat-dot). 대화창에서 움직이는 기다림 표시는 이것 하나로 통일 (2026-11-18, 반짝이는 글자와 함께 쓰면 움직임이 두 겹이라 뺌) */
export function Dots() {
  return <span aria-hidden className="flex shrink-0 items-center gap-1.5">{[0, 1, 2].map((i) => <span key={i} className="chat-dot size-2 rounded-full bg-hint" style={{ animationDelay: `${i * 0.2}s` }} />)}</span>
}

/** 분석 모델이 답을 만드는 중: 점 세 개만 든 말풍선 + 말풍선 바깥 아래에 작은 글씨로 지금 하는 일 (2026-11-18 사용자 결정, 메신저의 「읽음」·시간처럼).
 *  아래 글씨는 반짝임(index.css .chat-shimmer).
 *  문구는 두세 단어(「답변 반영 중…」). 5초가 넘으면 같은 줄 끝에 「N초」, 20초가 넘으면 「, 조금 더 걸릴 수 있어요」 (가운데 점 · 은 따로 떠 보여서 쓰지 않음).
 *  화면 읽기에는 label 만 한 번 알린다 (보이는 글자는 aria-hidden 이라 초가 바뀔 때마다 읽지 않는다). */
export function Typing({ label }: { label: string }) {
  const sec = useElapsed()
  return (
    <li className="chat-in flex flex-col items-start" role="status">
      <span className="sr-only">{label}</span>
      <span aria-hidden className="rounded-bubble rounded-tl-none bg-bubble px-4 py-3.5"><Dots /></span>
      <span aria-hidden className="chat-shimmer mt-1.5 pl-1 text-12">
        {label}{sec >= 5 && ` ${sec}초`}{sec >= 20 && ", 조금 더 걸릴 수 있어요"}
      </span>
    </li>
  )
}

/** 기다림이 길어질 때만 보이는 경과 시간 (2026-11-18 사용자 결정: 처음엔 문구만, 5초가 넘으면 「N초째 ○○ 중이에요」).
 *  20초가 넘으면 오래 걸릴 수 있다는 안내를 덧붙인다. doing = 「진행」·「해석」 등 */
export function ElapsedNote({ doing = "진행" }: { doing?: string }) {
  const sec = useElapsed()
  if (sec < 5) return null
  return <span aria-hidden className="mt-1 block text-12 text-sub">{doing} 중 {sec}초{sec >= 20 ? ", 조금 더 걸릴 수 있어요" : ""}</span>
}

/** 말풍선 안 버튼: main = 이 줄의 주 동작(파란 면), 나머지는 흰 면 (hover = 연파랑 tint, 보기 버튼과 같음) */
export const CHAT_BTN = "inline-flex min-h-9 items-center gap-1.5 rounded-control px-3.5 py-1.5 text-13 font-semibold transition disabled:cursor-not-allowed disabled:opacity-50"
export const CHAT_MAIN = `${CHAT_BTN} bg-accent text-on-accent enabled:hover:bg-accent-hover`
export const CHAT_QUIET = `${CHAT_BTN} bg-surface text-main enabled:hover:bg-tint`  // hover 를 sunken-hover 로 하면 말풍선 면(bubble)과 같아져 버튼이 사라진다
