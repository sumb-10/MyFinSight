// 목업 분석 실행 상태. 리포트가 있는 실행(완료)과, 진행 화면 확인용 상태(대기·진행·확인할 점·실패·취소)를 둔다.
// 단계 ID·묶음은 서버(executor/stages.py)와 같은 이름을 쓴다.
import type { ProposedRunCancel } from "../../api/proposed"
import type { RunPartial, RunRow, RunStatus, RunStep, StepStatus } from "../../api/types"
import { REPORTS, RUN_STATES } from "../scenarios"
import { stockOf } from "./stocks"
import { localIso } from "./util"

export const STEPS: [string, string, string][] = [
  ["01_request", "요청 확정", "conditions"], ["02_intent", "의도 해석", "conditions"],
  ["03_candidates", "후보 수집", "candidates"], ["04_tagging", "테마 판정", "candidates"], ["05_selection", "종목 선정", "candidates"], ["06_explain", "선정 이유", "candidates"], ["10f_current", "현재 구성", "candidates"],
  ["07_backtest_spec", "백테스트 조건", "backtest"], ["10_targets", "시작일 비중", "backtest"], ["10w_paths", "리밸런싱 경로", "backtest"], ["11_backtest", "백테스트", "backtest"],
  ["12_validation", "검증", "validation"], ["13_results", "결과 모음", "report"], ["14_report", "리포트", "report"],
]
const BUCKETS: [string, string][] = [["conditions", "조건과 자료 확인"], ["candidates", "종목 선정과 투자 비중 계산"], ["backtest", "과거 성과 분석"], ["validation", "내 투자조건 충족 여부 점검"], ["report", "분석 결과 정리 및 리포트 작성"]]

/** 목업 경고 9건 (중복 2쌍 포함). 서버는 단계 요약에 최대 2건만 붙이므로(「· 확인 필요 N건: a; b」) 화면은 일부만 볼 수 있다 — 전체 목록은 제안 계약 getRunWarnings 로. */
export const RUN_WARNINGS = [
  { step: "01_request", message_ko: "[목업] 분석 기준일(2026-10-30)의 환율 자료가 없어 직전 영업일(2026-10-29) 환율을 썼습니다." },
  { step: "03_candidates", message_ko: "[목업] KOSPI 200 종목은 이번 투자 대상 지수에 없어 후보에서 빠졌습니다." },
  { step: "03_candidates", message_ko: "[목업] 최소 거래대금 기준에 못 미친 종목 4개를 후보에서 뺐습니다." },
  { step: "03_candidates", message_ko: "[목업] 제외 종목 TSLA 는 후보에서 뺐습니다." },  // 요약에는 앞 2건만 → 세 번째는 전체 목록에서만 보인다
  { step: "05_selection", message_ko: "[목업] 선정 지표 자료가 없는 종목 2개를 후보에서 뺐습니다." },
  { step: "05_selection", message_ko: "[목업] 선정 지표 자료가 없는 종목 2개를 후보에서 뺐습니다." },  // 같은 단계의 중복 메시지 (묶어서 「2번」으로)
  { step: "07_backtest_spec", message_ko: "[목업] 백테스트 시작일의 환율 자료가 없어 직전 영업일 환율을 썼습니다." },
  { step: "10_targets", message_ko: "[목업] 뉴스 근거가 부족한 시점 3곳은 기준 비중을 그대로 썼습니다." },
  { step: "10w_paths", message_ko: "[목업] 뉴스 근거가 부족한 시점 3곳은 기준 비중을 그대로 썼습니다." },  // 다른 단계의 같은 문구 (나온 단계를 함께 표시)
]

export function steps(doneUntil: number, current: StepStatus | null, warnings = false): RunStep[] {
  return STEPS.map(([step, label_ko, bucket], i) => {
    const status: StepStatus = i < doneUntil ? "SUCCESS" : i === doneUntil && current ? current : "QUEUED"
    const ws = warnings ? RUN_WARNINGS.filter((w) => w.step === step) : []
    const summary = status === "SUCCESS" ? `[목업] ${label_ko} 완료${ws.length ? ` · 확인 필요 ${ws.length}건: ${ws.slice(0, 2).map((w) => w.message_ko).join("; ")}` : ""}` : null
    return { step, label_ko, bucket, status, started_at: status !== "QUEUED" ? "2026-11-04T09:00:00" : null, ended_at: status === "SUCCESS" ? "2026-11-04T09:01:00" : null, summary, error_code: status === "FAILED" ? "MOCK_STEP_FAILED" : null, error_message: status === "FAILED" ? "[목업] 백테스트 계산 중 가격 자료가 부족해 멈췄습니다." : null }
  })
}
export function buckets(st: RunStep[]) {
  return BUCKETS.map(([id, title_ko]) => { const s = st.filter((x) => x.bucket === id); const status: StepStatus = s.every((x) => x.status === "SUCCESS") ? "SUCCESS" : s.some((x) => x.status === "FAILED") ? "FAILED" : s.some((x) => x.status === "CANCELLED") ? "CANCELLED" : s.some((x) => x.status === "STARTED" || x.status === "SUCCESS") ? "STARTED" : "QUEUED"; return { id, title_ko, status } })
}

export function runStatus(id: string): RunStatus | null {
  const rep = REPORTS.find((r) => r.run_id === id)
  if (rep) { const st = steps(STEPS.length, null); return { run_id: id, request_id: rep.request_id, status: "success", queue_position: null, queued_at: `${rep.created_at}T08:40:00`, started_at: `${rep.created_at}T08:41:00`, finished_at: `${rep.created_at}T08:58:00`, buckets: buckets(st), steps: st, report_id: rep.id, error: null } }
  const s = RUN_STATES.find((x) => x.id === id)
  if (!s) return null
  const base = { run_id: id, request_id: "mock_req_normal", queued_at: "2026-11-04T09:00:00", report_id: null }
  if (s.state === "queued") { const st = steps(0, null); return { ...base, status: "queued", queue_position: 2, buckets: buckets(st), steps: st, error: null } }
  if (id === "mock_run_running") { const st = steps(5, "STARTED"); return { ...base, status: "running", queue_position: null, started_at: "2026-11-04T09:00:30", buckets: buckets(st), steps: st, error: null } }
  if (id === "mock_run_notices") { const st = steps(10, "STARTED", true); return { ...base, status: "running", queue_position: null, started_at: "2026-11-04T09:00:30", buckets: buckets(st), steps: st, error: null } }
  if (s.state === "failed") { const st = steps(10, "FAILED"); return { ...base, status: "failed", queue_position: null, started_at: "2026-11-04T09:00:30", finished_at: "2026-11-04T09:12:00", buckets: buckets(st), steps: st, error: { code: "MOCK_STEP_FAILED", message_ko: "[목업] 백테스트 계산 중 가격 자료가 부족해 멈췄습니다.", step: "11_backtest", actions: ["retry"] } } }
  const st = steps(6, "CANCELLED")
  return { ...base, status: "cancelled", queue_position: null, started_at: "2026-11-04T09:00:30", finished_at: "2026-11-04T09:05:00", buckets: buckets(st), steps: st, error: null, cancel: cancelInfo(st, "2026-11-04T09:04:58", "2026-11-04T09:05:00") } as RunStatus
}

/** 취소 결과 (제안): 언제 요청·완료됐는지, 어느 단계에서 멈췄는지. */
export function cancelInfo(st: RunStep[], requested_at: string, completed_at: string | null): ProposedRunCancel {
  const stopped = st.find((x) => x.status === "STARTED" || x.status === "CANCELLED")
  return { requested_at, completed_at, stopped_step: stopped?.step ?? null, stopped_step_label_ko: stopped?.label_ko ?? null, done_steps: st.filter((x) => x.status === "SUCCESS").length, immediate: true }
}

/* ───────── 이벤트 시퀀스 (7-3): 만든 시각부터 시간이 흐르면 대기 → 단계 진행 → 확인할 점 → 완료(또는 실패)로 저절로 바뀐다 ───────── */
// 단계 간격은 진행 화면의 상태 확인 간격(2.5초, RunScreen)보다 길게 둔다 — 짧으면 「진행 중」을 한 번도 못 보고 건너뛰는 단계가 생긴다.
export const LIVE_QUEUE_MS = 3000, LIVE_STEP_MS = 3000, CANCEL_MS = 1500
const FAIL_AT = STEPS.findIndex(([s]) => s === "11_backtest")
const iso = localIso

export interface LiveRun { started: number; ending: "success" | "failed"; request_id: string; report_id: string; cancel?: { at: number; frozen: number } }

/** t = 지금 시각(ms). 취소했으면 취소 시각에서 진행을 멈추고, CANCEL_MS 동안 「취소 처리 중」 뒤 「취소됨」. */
export function liveStatus(id: string, lv: LiveRun, now: number): RunStatus {
  const at = lv.cancel ? lv.cancel.frozen : now
  const t = at - lv.started
  const base = { run_id: id, request_id: lv.request_id, queued_at: iso(lv.started), report_id: null as string | null }
  const k = Math.floor((t - LIVE_QUEUE_MS) / LIVE_STEP_MS)
  const startedAt = iso(lv.started + LIVE_QUEUE_MS)
  let r: RunStatus
  if (t < LIVE_QUEUE_MS) { const st = steps(0, null); r = { ...base, status: "queued", queue_position: 1, buckets: buckets(st), steps: st, error: null } }
  else if (lv.ending === "failed" && k >= FAIL_AT) { const st = steps(FAIL_AT, "FAILED", true); return { ...base, status: "failed", queue_position: null, started_at: startedAt, finished_at: iso(lv.started + LIVE_QUEUE_MS + FAIL_AT * LIVE_STEP_MS), buckets: buckets(st), steps: st, error: { code: "MOCK_STEP_FAILED", message_ko: "[목업] 백테스트 계산 중 가격 자료가 부족해 멈췄습니다.", step: "11_backtest", actions: ["retry"] } } }
  else if (k >= STEPS.length) { const st = steps(STEPS.length, null, true); return { ...base, status: "success", queue_position: null, started_at: startedAt, finished_at: iso(lv.started + LIVE_QUEUE_MS + STEPS.length * LIVE_STEP_MS), buckets: buckets(st), steps: st, report_id: lv.report_id, error: null } }
  else { const st = steps(k, "STARTED", true); r = { ...base, status: "running", queue_position: null, started_at: startedAt, buckets: buckets(st), steps: st, error: null } }
  if (!lv.cancel) return r
  const cancelling = now - lv.cancel.at < CANCEL_MS
  if (cancelling) return { ...r, status: "cancelling", cancel: cancelInfo(r.steps, iso(lv.cancel.at), null) } as RunStatus
  const st = r.steps.map((x) => (x.status === "STARTED" || x.status === "QUEUED" ? { ...x, status: "CANCELLED" as const } : x))
  return { ...r, status: "cancelled", finished_at: iso(lv.cancel.at + CANCEL_MS), steps: st, buckets: buckets(st), cancel: cancelInfo(r.steps, iso(lv.cancel.at), iso(lv.cancel.at + CANCEL_MS)) } as RunStatus
}

export function runPartial(id: string): RunPartial | null {
  const rep = REPORTS.find((r) => r.run_id === id) ?? REPORTS[0]
  if (id === "mock_run_queued") return null
  return { run_id: id, intent: { summary_ko: `[목업] ${rep.themes.map((t) => t.label).join("·")} 기업 투자`, themes: rep.themes.map((t, i) => ({ id: `t${i + 1}`, label_ko: t.label })), template: rep.template, metric: "return_12m_1m" },
    selection: { as_of: "2026-10-30", metric: "return_12m_1m", n_selected: rep.tickers.length, n_target: rep.tickers.length, n_candidates: 18 + rep.tickers.length, n_tagged: 6 + rep.tickers.length, rows: rep.tickers.map((t, i) => ({ rank: i + 1, ticker: t, name: stockOf(t).name_en, sector: stockOf(t).sector_ko, metric_value: Math.round((0.42 - i * 0.05) * 10000) / 10000 })) } }
}

export function runRows(): RunRow[] {
  return [...RUN_STATES.map((s) => runStatus(s.id)!), ...REPORTS.map((r) => runStatus(r.run_id)!)].map((r) => ({ run_id: r.run_id, request_id: r.request_id, status: r.status, queued_at: r.queued_at, started_at: r.started_at ?? null, finished_at: r.finished_at ?? null, report_id: r.report_id ?? null, error_message: r.error?.message_ko ?? null }))
}
