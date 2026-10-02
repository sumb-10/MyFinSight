import { INITIAL_FIXTURES } from "./fixtures"
import type { AppData, PaperPortfolio, Profile, Report } from "./types"

const STORAGE_KEY = "myfinsight.local.v1"

const emptyData = (): AppData => ({
  version: 4,
  profile: null,
  reports: structuredClone(INITIAL_FIXTURES.reports),
  paperPortfolios: structuredClone(INITIAL_FIXTURES.paperPortfolios),
})

export const localDataService = {
  load(): AppData {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return emptyData()
    const parsed = JSON.parse(raw) as AppData
    if (
      !Array.isArray(parsed.reports) ||
      !Array.isArray(parsed.paperPortfolios)
    ) {
      throw new Error("저장 데이터 형식을 읽을 수 없습니다.")
    }
    if (parsed.version !== 4) {
      const migrated = { ...emptyData(), profile: parsed.profile }
      this.save(migrated)
      return migrated
    }
    return parsed
  },
  save(data: AppData) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
  },
  saveProfile(data: AppData, profile: Profile) {
    const next = { ...data, profile: structuredClone(profile) }
    this.save(next)
    return next
  },
  saveReport(data: AppData, report: Report) {
    const next = {
      ...data,
      reports: [
        structuredClone(report),
        ...data.reports.filter((item) => item.id !== report.id),
      ],
    }
    this.save(next)
    return next
  },
  savePaper(data: AppData, paper: PaperPortfolio) {
    const next = {
      ...data,
      paperPortfolios: [
        structuredClone(paper),
        ...data.paperPortfolios.filter((item) => item.id !== paper.id),
      ],
    }
    this.save(next)
    return next
  },
  reset() {
    localStorage.removeItem(STORAGE_KEY)
    return emptyData()
  },
}
