import type { PaperSummary } from "../../api/types"
import { inCur } from "./money"

// 같은 리포트로 만든 여러 모의투자 구분 — 서버가 주는 적용 전략명·시작일·초기 투자금만 쓴다 (목록·상세·시작 창 공통 표기).

export const paperStrategy = (p: Pick<PaperSummary, "strategy" | "name_ko">) => p.strategy?.name_ko || p.name_ko
/** 「전략 · 2026-10-30 시작 · 초기 20,000,000원」. shown = 바로 위에 이미 보이는 이름 (전략명과 같으면 전략명을 되풀이하지 않는다). */
export const paperBasis = (p: Pick<PaperSummary, "strategy" | "name_ko" | "start_date" | "initial_capital">, shown?: string) =>
  `${paperStrategy(p) === shown ? "" : `${paperStrategy(p)} · `}${p.start_date} 시작 · 초기 ${inCur(p.initial_capital.amount, p.initial_capital.currency)}`
/** 같은 리포트(report_id 또는 run_id)의 모의투자 */
export const samePapers = <T extends Pick<PaperSummary, "report_id" | "run_id">>(rows: T[], reportId: string) => rows.filter((r) => r.report_id === reportId || r.run_id === reportId)
