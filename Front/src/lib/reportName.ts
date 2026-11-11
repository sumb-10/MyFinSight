import { proposedNameOf } from "../api/proposed"
import type { ReportRow } from "../api/types"

// 리포트 표시 이름 — 홈·사이드바·리포트 목록이 모두 이 함수 하나를 쓴다 (GET /reports 의 행). 리포트 상세 제목도 같은 이름이다.
// 서버가 정한 이름(proposed_name: 사용자가 바꾼 이름, 아니면 자동 이름)이 있으면 그것. 서버의 자동 이름은 리포트의 짧은 제목이다.
// 그 밖에는 짧은 제목(title_ko: 리포트 머리말 header.title_ko, LLM 이 요청을 6~20자로 줄인 것) → 투자 아이디어 첫 줄 → 요청 요약 → 선택 전략 이름 → 실행 ID.
// 예전에는 아이디어 원문이 기준이라 긴 아이디어는 제목이 몇 줄이 됐다 (2026-11-11 사용자 요청으로 짧은 제목으로 바꿈).
// 새 이름을 만들거나 저장하지 않는다.

const oneLine = (s: string | null | undefined) => (s ?? "").split("\n")[0].replace(/\s+/g, " ").trim()

export function reportName(r: Pick<ReportRow, "title_ko" | "idea" | "request_summary" | "strategy_name" | "run_id">): string {
  return proposedNameOf(r) ?? (oneLine(r.title_ko) || oneLine(r.idea) || oneLine(r.request_summary) || oneLine(r.strategy_name) || r.run_id)
}

/** 리포트 ID(또는 실행 ID)로 목록 행 찾기. */
export const findReportRow = <T extends Pick<ReportRow, "report_id" | "run_id">>(rows: T[] | null | undefined, id: string) => rows?.find((r) => r.report_id === id || r.run_id === id) ?? null
