import { proposedNameOf } from "../api/proposed"
import type { ReportRow } from "../api/types"

// 리포트 표시 이름 — 홈·사이드바·리포트 목록이 모두 이 함수 하나를 쓴다 (GET /reports 의 행). 리포트 상세 제목은 리포트의 짧은 제목(header.title_ko).
// 기준: 사용자가 입력한 투자 아이디어(idea). 리포트마다 다르고 목록·상세 어디서나 같은 값을 쓸 수 있는 유일한 기존 필드다.
//   (strategy_name 은 「낙폭 맞춤안 (…)」처럼 리포트끼리 거의 같고, 상세 제목 header.title_ko 는 목록 응답에 없다.)
// 없으면 요청 요약 → 선택 전략 이름 → 실행 ID 순서. 목업 모드에서는 제안 이름(proposed_name)이 있으면 그것을 쓴다.
// 새 이름을 만들거나 저장하지 않는다.

const oneLine = (s: string | null | undefined) => (s ?? "").split("\n")[0].replace(/\s+/g, " ").trim()

export function reportName(r: Pick<ReportRow, "idea" | "request_summary" | "strategy_name" | "run_id">): string {
  return proposedNameOf(r) ?? (oneLine(r.idea) || oneLine(r.request_summary) || oneLine(r.strategy_name) || r.run_id)
}

/** 리포트 ID(또는 실행 ID)로 목록 행 찾기. */
export const findReportRow = <T extends Pick<ReportRow, "report_id" | "run_id">>(rows: T[] | null | undefined, id: string) => rows?.find((r) => r.report_id === id || r.run_id === id) ?? null
