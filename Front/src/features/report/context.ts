import { createContext, useContext } from "react"
import type { ReportDoc } from "../../api/types"

/** scope: 처음 보여 줄 범위 — 본문에 쓰인 근거(cited, 기본) / 읽은 자료 전체(all) */
export interface DrawerFilter { ids?: string[] | null; title?: string; kind?: string; ticker?: string; scope?: "cited" | "all" }

/** 리포트 화면 안에서 블록들이 쓰는 공통 동작: 근거 열기, 출처 드로어, 섹션 이동, 리밸런싱 시점 선택. ReportDetail 이 제공한다. */
export interface ReportCtx {
  reportId: string
  doc: ReportDoc
  numberOf: (id: string) => string
  openEvidence: (id: string, from?: string) => void  // from = 번호가 붙어 있던 글
  openDrawer: (f: DrawerFilter) => void
  jump: (sectionId: string, anchor?: string) => void  // anchor: 섹션 안에서 바로 보여 줄 요소 id
  selectedRb: number | null
  setSelectedRb: (seq: number | null) => void
  openCompany: string | null
  setOpenCompany: (ticker: string | null) => void
  openPanel?: (p: "calc" | "exec") => void
}

export const ReportContext = createContext<ReportCtx | null>(null)
export const useReport = () => useContext(ReportContext)
