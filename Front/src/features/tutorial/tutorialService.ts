import type { AnalysisService } from "../../api/service"
import type { ReportDoc } from "../../api/types"

// 튜토리얼 전용 읽기 전용 서비스: 예시 리포트 한 건만 돌려준다. 네트워크·목업 서비스(MockService)를 쓰지 않아 운영 빌드에서도 동작한다.
// 쓰기(모의투자 시작·조건 수정·다시 분석 등)는 모두 거절한다. 선택 기능(제안 계약)은 두지 않아 화면이 그 메뉴를 열지 않는다.

export const TUTORIAL_REPORT_ID = "tutorial_example"

const readOnly = () => Promise.reject(new Error("예시 화면에서는 실행되지 않습니다."))

export function createTutorialService(doc: ReportDoc): AnalysisService {
  return {
    mode: "api",  // 「목업」 표시 없이 실제 화면처럼 보이게
    health: readOnly,
    options: readOnly,
    getProfile: async () => null,
    saveProfile: readOnly,
    createRequest: readOnly,
    getRequest: readOnly,
    listRequests: async () => [],
    answer: readOnly,
    skip: readOnly,
    updateOverrides: readOnly,
    sendMessage: readOnly,
    confirm: readOnly,
    cancelRequest: readOnly,
    listRuns: async () => [],
    getRun: readOnly,
    cancelRun: readOnly,
    retryRun: readOnly,
    getRunPartial: async () => null,
    listReports: async () => [],
    getReport: async () => doc,
    rerun: readOnly,
    previewPaper: readOnly,
    createPaper: readOnly,
    listPaper: async () => [],
    getPaper: readOnly,
    refreshPaper: readOnly,
    stopPaper: readOnly,
    resumePaper: readOnly,
    createRevision: readOnly,
    getComparison: readOnly,
    getReportComparison: async () => null,
    getReportEvidence: async () => null,
    getReportEvidenceOne: async () => null,
    getReportCheckpoint: async () => null,
    getReportSeries: async () => null,
  }
}

/** 예시 리포트: 목업 「정상 추천」 시나리오(mock_rep_normal)를 만드는 함수를 그대로 쓴다. 튜토리얼을 열 때만 따로 내려받는다 (별도 묶음). */
export async function loadTutorialDoc(): Promise<ReportDoc> {
  const [{ buildReport }, { REPORTS }] = await Promise.all([import("../../mocks/data/report"), import("../../mocks/scenarios")])
  const sc = REPORTS.find((r) => r.id === "mock_rep_normal") ?? REPORTS[0]
  return buildReport(sc)
}
