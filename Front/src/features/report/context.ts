import { createContext, useContext } from "react"
import type { ReportDoc } from "../../api/types"

export interface DrawerFilter { ids?: string[] | null; title?: string; kind?: string; ticker?: string }

/** 리포트 화면 안에서 블록들이 쓰는 공통 동작: 근거 열기, 출처 드로어, 섹션 이동, 리밸런싱 시점 선택. ReportDetail 이 제공한다. */
export interface ReportCtx {
  reportId: string
  doc: ReportDoc
  numberOf: (id: string) => string
  openEvidence: (id: string) => void
  openDrawer: (f: DrawerFilter) => void
  jump: (sectionId: string) => void
  selectedRb: number | null
  setSelectedRb: (seq: number | null) => void
  openCompany: string | null
  setOpenCompany: (ticker: string | null) => void
}

export const ReportContext = createContext<ReportCtx | null>(null)
export const useReport = () => useContext(ReportContext)
