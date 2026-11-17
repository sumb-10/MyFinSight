import type { ReactNode } from "react"
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

/** 분석 모델이 답을 만드는 중 (점 세 개). label = 화면 읽기용 설명 */
export function Typing({ label }: { label: string }) {
  return (
    <li className="chat-in flex">
      <p role="status" className="flex items-center gap-1 rounded-bubble rounded-tl-none bg-bubble px-4 py-3.5">
        <span className="sr-only">{label}</span>
        {[0, 1, 2].map((i) => <span key={i} aria-hidden className="chat-dot size-1.5 rounded-full bg-hint" style={{ animationDelay: `${i * 0.15}s` }} />)}
      </p>
    </li>
  )
}

/** 말풍선 안 버튼: main = 이 줄의 주 동작(파란 면), 나머지는 흰 면 (hover = 연파랑 tint, 보기 버튼과 같음) */
export const CHAT_BTN = "inline-flex min-h-9 items-center gap-1.5 rounded-control px-3.5 py-1.5 text-13 font-semibold transition disabled:cursor-not-allowed disabled:opacity-50"
export const CHAT_MAIN = `${CHAT_BTN} bg-accent text-on-accent enabled:hover:bg-accent-hover`
export const CHAT_QUIET = `${CHAT_BTN} bg-surface text-main enabled:hover:bg-tint`  // hover 를 sunken-hover 로 하면 말풍선 면(bubble)과 같아져 버튼이 사라진다
