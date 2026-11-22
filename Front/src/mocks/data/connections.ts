// 연결 설정 목업 규칙. 실제 서버는 DB 와 OpenAI 에 접속해 보고 판정하지만, 목업은 값의 모양만 보고 정해진 대로 답한다.
// 시연·테스트에서 실패를 일부러 낼 수 있게 한 규칙:
//   팀 DB   서버 이름에 "exampel" 이 들었거나 .invalid 로 끝남 → 주소를 못 찾음 · 포트 1 → 응답 없음 · 계정 wrong → 계정·비밀번호 틀림 · 이름 nope → 데이터베이스 없음
//   분석 모델  sk-quota 로 시작 → 한도 · sk- 로 시작하는 20자 이상이 아니면 → 키가 틀림
// 실제 값(비밀번호·키 본문)은 어디에도 두지 않는다 — 목업 상태에는 가린 표시만 남긴다.
import type { ProposedConnectionError, ProposedConnectionKind } from "../../api/proposed"
import { parseDbUrl } from "../../features/connect/dbUrl"

export const MOCK_DB_MASKED = "postgresql://reader:••••••••@db.example.com:5432/myfinsight"
export const MOCK_KEY_MASKED = "sk-••••••••••••a3F9"
/** 시장별 자료 시작일 (그 시장 비교지수의 첫 가격 날짜). 합친 시작일은 그중 가장 늦은 날이다 */
export const MOCK_DATA_START_BY_MARKET: Record<string, string> = { US: "1993-01-29", KR: "2002-10-14" }
export const MOCK_DATA_START = "2002-10-14"
/** 분석 한 번의 사용료 어림 (USD). 실행 기록이 없는 처음 사용자에게 서버가 줄 기본값과 같다 (2026-11-03 시나리오 96건의 사용 기록 중앙값 0.09 를 어림) */
export const MOCK_COST_PER_RUN_USD = 0.1

export type ConnectionCheck = { ok: true; masked: string } | { ok: false; error: ProposedConnectionError }
const fail = (code: ProposedConnectionError["code"], value: string | null, raw: string): ConnectionCheck => ({ ok: false, error: { code, value, raw } })

export function checkConnection(kind: ProposedConnectionKind, value: string): ConnectionCheck {
  if (kind === "llm") {
    const key = value.trim()
    if (key.startsWith("sk-quota")) return fail("quota", null, "RateLimitError: You exceeded your current quota, please check your plan and billing details. (429)")
    if (!/^sk-[A-Za-z0-9_-]{17,}$/.test(key)) return fail("invalid_key", null, "AuthenticationError: Incorrect API key provided. (401)")
    return { ok: true, masked: `sk-••••••••••••${key.slice(-4)}` }
  }
  const p = parseDbUrl(value)
  if (!p) return fail("unknown", null, "ArgumentError: Could not parse SQLAlchemy URL from given URL string")
  if (p.host.includes("exampel") || p.host.endsWith(".invalid")) return fail("host_not_found", p.host, `OperationalError: could not translate host name "${p.host}" to address`)
  if (p.port === "1") return fail("no_response", `${p.host}:${p.port}`, `OperationalError: connection to server at "${p.host}", port ${p.port} failed: timeout expired`)
  if (p.user === "wrong") return fail("auth_failed", null, `OperationalError: password authentication failed for user "${p.user}"`)
  if (p.name === "nope") return fail("database_not_found", p.name, `OperationalError: database "${p.name}" does not exist`)
  return { ok: true, masked: `postgresql://${p.user ? `${p.user}:••••••••@` : ""}${p.host}:${p.port}/${p.name}` }
}
