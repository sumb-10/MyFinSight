// 화면이 쓰는 단일 서비스 계약 (Front/docs/04 §8). 서버(backend/analysis/api) 만 데이터 원천이다. 샘플·오프라인 자료 모드는 없다.
import { api, ApiError, LLM_TIMEOUT_MS } from "./client"
import type { CheckpointDetail, ComparisonDoc, DialogState, EvidenceDetail, EvidencePage, EvidenceQuery, Health, Options, PaperDetail, PaperIn, PaperPreview, PaperSummary, ProfileFields, ProfileView, ReportDoc, ReportRow, RequestRow, RunPartial, RunRow, RunStatus, SeriesResponse } from "./types"

const LLM = { timeoutMs: LLM_TIMEOUT_MS }

export interface AnalysisService {
  readonly mode: "api"
  health(): Promise<Health>
  options(): Promise<Options>
  getProfile(): Promise<ProfileView | null>
  saveProfile(fields: ProfileFields): Promise<ProfileView>
  createRequest(input: { idea: string; overrides?: Record<string, unknown>; mode?: "new" | "rerun" | "revision"; base_report_id?: string | null }): Promise<DialogState>
  getRequest(id: string): Promise<DialogState>
  listRequests(): Promise<RequestRow[]>
  answer(id: string, seq: number, input: { option_value?: unknown; free_text?: string }): Promise<DialogState>
  skip(id: string, seq: number): Promise<DialogState>
  updateOverrides(id: string, overrides: Record<string, unknown>): Promise<DialogState>
  sendMessage(id: string, text: string): Promise<DialogState>
  confirm(id: string): Promise<{ run_id: string; queue_position: number | null }>
  cancelRequest(id: string): Promise<DialogState>
  listRuns(): Promise<RunRow[]>
  getRun(id: string): Promise<RunStatus>
  cancelRun(id: string): Promise<RunStatus>
  retryRun(id: string): Promise<RunStatus>
  getRunPartial(id: string): Promise<RunPartial | null>
  listReports(): Promise<ReportRow[]>
  getReport(id: string): Promise<ReportDoc>
  rerun(reportId: string): Promise<DialogState>
  previewPaper(input: PaperIn): Promise<PaperPreview>
  createPaper(input: PaperIn): Promise<PaperDetail>
  listPaper(): Promise<PaperSummary[]>
  getPaper(id: string): Promise<PaperDetail>
  refreshPaper(id: string): Promise<PaperDetail>
  stopPaper(id: string): Promise<PaperDetail>
  resumePaper(id: string): Promise<PaperDetail>
  createRevision(reportId: string, text: string): Promise<DialogState>
  getComparison(id: string): Promise<ComparisonDoc>
  getReportComparison(reportId: string): Promise<ComparisonDoc | null>
  // 라운드 4: 근거 색인 페이지·한 건, 체크포인트 상세, 전체 해상도 시계열. 서버가 404 를 주면 null (화면은 문서 안의 자료로 대신한다).
  getReportEvidence(reportId: string, q?: EvidenceQuery): Promise<EvidencePage | null>
  getReportEvidenceOne(reportId: string, eid: string): Promise<EvidenceDetail | null>
  getReportCheckpoint(reportId: string, seq: number, portfolioId?: string): Promise<CheckpointDetail | null>
  getReportSeries(reportId: string, dataset: "index" | "value_usd" | "drawdown", ids?: string[]): Promise<SeriesResponse | null>
}

const qs = (params: Record<string, unknown>) => {
  const u = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) { if (v === undefined || v === null || v === "") continue; u.set(k, Array.isArray(v) ? v.join(",") : String(v)) }
  const s = u.toString()
  return s ? `?${s}` : ""
}

async function orNull<T>(p: Promise<T>): Promise<T | null> {
  try { return await p } catch (e) { if (e instanceof ApiError && e.status === 404) return null; throw e }
}

export class HttpService implements AnalysisService {
  readonly mode = "api" as const
  health() { return api.get<Health>("/health") }
  options() { return api.get<Options>("/meta/options") }
  async getProfile() {
    try {
      return await api.get<ProfileView>("/profile")
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null
      throw e
    }
  }
  saveProfile(fields: ProfileFields) { return api.put<ProfileView>("/profile", fields) }
  createRequest(input: { idea: string; overrides?: Record<string, unknown>; mode?: "new" | "rerun" | "revision"; base_report_id?: string | null }) {
    return api.post<DialogState>("/requests", { idea: input.idea, overrides: input.overrides ?? {}, mode: input.mode ?? "new", base_report_id: input.base_report_id ?? null }, LLM)
  }
  getRequest(id: string) { return api.get<DialogState>(`/requests/${id}`) }
  listRequests() { return api.get<RequestRow[]>("/requests") }
  answer(id: string, seq: number, input: { option_value?: unknown; free_text?: string }) {
    return api.post<DialogState>(`/requests/${id}/answer`, { seq, option_value: input.option_value ?? null, free_text: input.free_text ?? null }, LLM)
  }
  skip(id: string, seq: number) { return api.post<DialogState>(`/requests/${id}/skip`, { seq }, LLM) }
  updateOverrides(id: string, overrides: Record<string, unknown>) { return api.post<DialogState>(`/requests/${id}/overrides`, { overrides }, LLM) }
  sendMessage(id: string, text: string) { return api.post<DialogState>(`/requests/${id}/message`, { text }, LLM) }
  confirm(id: string) { return api.post<{ run_id: string; queue_position: number | null }>(`/requests/${id}/confirm`) }
  cancelRequest(id: string) { return api.post<DialogState>(`/requests/${id}/cancel`) }
  listRuns() { return api.get<RunRow[]>("/runs") }
  getRun(id: string) { return api.get<RunStatus>(`/runs/${id}`) }
  cancelRun(id: string) { return api.post<RunStatus>(`/runs/${id}/cancel`) }
  retryRun(id: string) { return api.post<RunStatus>(`/runs/${id}/retry`) }
  getRunPartial(id: string) { return orNull(api.get<RunPartial>(`/runs/${id}/partial`)) }
  listReports() { return api.get<ReportRow[]>("/reports") }
  getReport(id: string) { return api.get<ReportDoc>(`/reports/${id}`) }
  rerun(reportId: string) { return api.post<DialogState>(`/reports/${reportId}/rerun`, undefined, LLM) }
  previewPaper(input: PaperIn) { return api.post<PaperPreview>("/paper/preview", input) }
  createPaper(input: PaperIn) { return api.post<PaperDetail>("/paper", input) }
  listPaper() { return api.get<PaperSummary[]>("/paper") }
  getPaper(id: string) { return api.get<PaperDetail>(`/paper/${id}`) }
  refreshPaper(id: string) { return api.post<PaperDetail>(`/paper/${id}/refresh`) }
  stopPaper(id: string) { return api.post<PaperDetail>(`/paper/${id}/stop`) }
  resumePaper(id: string) { return api.post<PaperDetail>(`/paper/${id}/resume`) }
  createRevision(reportId: string, text: string) { return api.post<DialogState>(`/reports/${reportId}/revisions`, { text }, LLM) }
  getComparison(id: string) { return api.get<ComparisonDoc>(`/comparisons/${id}`) }
  async getReportComparison(reportId: string) {
    try {
      return await api.get<ComparisonDoc>(`/reports/${reportId}/comparison`)
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null
      throw e
    }
  }
  getReportEvidence(reportId: string, q: EvidenceQuery = {}) { return orNull(api.get<EvidencePage>(`/reports/${reportId}/evidence${qs({ ...q, ids: q.ids })}`)) }
  getReportEvidenceOne(reportId: string, eid: string) { return orNull(api.get<EvidenceDetail>(`/reports/${reportId}/evidence/${encodeURIComponent(eid)}`)) }
  getReportCheckpoint(reportId: string, seq: number, portfolioId?: string) { return orNull(api.get<CheckpointDetail>(`/reports/${reportId}/checkpoints/${seq}${qs({ portfolio_id: portfolioId })}`)) }
  getReportSeries(reportId: string, dataset: "index" | "value_usd" | "drawdown", ids?: string[]) { return orNull(api.get<SeriesResponse>(`/reports/${reportId}/series${qs({ dataset, ids })}`)) }
}

export function createService(): AnalysisService {
  return new HttpService()
}

export async function createServiceAsync(): Promise<AnalysisService> {
  return new HttpService()
}
