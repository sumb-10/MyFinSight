// 목업 모드의 바뀌는 상태 (이름 변경·투자조건 저장·새 요청·모의투자 등). 이 탭의 sessionStorage 에만 두고 서버로 보내지 않는다.
// 리포트 문서·백테스트처럼 정해진 자료는 시나리오에서 매번 같은 값으로 다시 만들므로 저장하지 않는다.
import type { ProposedMessageResult } from "../../api/proposed"
import type { DialogState, ProfileFields, ProfileVersion, UserRequest } from "../../api/types"
import type { PaperScenario } from "../scenarios"
import type { LiveRun } from "../data/runs"
import type { ProfileChatState } from "../data/profileChat"
import { SEEN_KEYS } from "../../lib/seen"

import { clearGuideRecord } from "../../features/tutorial/guideRecord"

export const MOCK_STORE_KEY = "myfinsight.mock.store.v1"

export interface MockState {
  v: 1
  profileVariant: "default" | "zero" | "none"            // none = 처음 사용자 (기본 이력 없이 목업에서 저장한 버전만)
  savedVersions: ProfileVersion[]                       // 목업에서 저장한 투자조건 버전 (기본 이력 뒤에 붙음)
  reportNames: Record<string, string | null>            // 사용자가 바꾼 리포트 이름 (null = 자동 이름)
  reportRenamedAt: Record<string, string>
  deletedReports: string[]                                 // 목업에서 삭제한 리포트 ID (목록·상세에서 빠진다)
  paperNames: Record<string, { mode: "linked" } | { mode: "custom"; name_ko: string }>
  paperStatus: Record<string, "active" | "stopped">
  createdPapers: PaperScenario[]
  requests: Record<string, DialogState>                 // 목업에서 새로 만든·바뀐 요청
  messages: Record<string, ProposedMessageResult[]>        // 말로 보태기 처리 결과 (바뀐 조건 전후 포함)
  drafts: Record<string, { req: UserRequest; touched: string[]; base: ProfileFields }>  // 진행 중인 요청의 지금 조건, 바꾼 항목, 비교 기준(요청을 만들 때의 기본 투자조건)
  runs: Record<string, { cancel_at: number }>              // 정해진 진행 상태 실행을 취소한 시각 (ms)
  live: Record<string, LiveRun>                           // 이벤트 시퀀스 실행 (만든 시각부터 저절로 진행)
  profileChats: Record<string, ProfileChatState>          // 대화형 초기 투자조건 (질문별 답, 마지막 다시 묻기 안내)
  interpreting: Record<string, { from?: number; until: number }>  // 새 요청이 '해석 중'으로 보이는 시각 (ms, 실제 서버처럼 번호를 먼저 주고 뒤에서 해석. from 부터 지난 만큼 단계가 나아감)
  seq: number
}

export const initialState = (): MockState => ({ v: 1, profileVariant: "default", savedVersions: [], reportNames: {}, reportRenamedAt: {}, deletedReports: [], paperNames: {}, paperStatus: {}, createdPapers: [], requests: {}, messages: {}, drafts: {}, runs: {}, live: {}, profileChats: {}, interpreting: {}, seq: 1 })

export function loadState(): MockState {
  try {
    const raw = window.sessionStorage.getItem(MOCK_STORE_KEY)
    if (raw) { const s = JSON.parse(raw) as MockState; if (s?.v === 1) return { ...initialState(), ...s } }
  } catch { /* 목업 상태가 깨져도 초기 상태로 계속 */ }
  return initialState()
}

export function saveState(s: MockState) {
  try { window.sessionStorage.setItem(MOCK_STORE_KEY, JSON.stringify(s)) } catch { /* 저장 실패해도 화면은 계속 (새로고침 시 초기화) */ }
}

export function clearState() {
  try { window.sessionStorage.removeItem(MOCK_STORE_KEY); window.sessionStorage.removeItem(SEEN_KEYS.mock) } catch { /* ignore */ }  // 확인 기록(새 리포트·리밸런싱 알림)도 처음으로
  clearGuideRecord()  // 리포트 가이드 안내 기록도 처음으로
}
