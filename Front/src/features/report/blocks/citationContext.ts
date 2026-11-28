import { createContext } from "react"

/** 인용 ID 클릭 시 출처 패널을 여는 콜백·번호 표시. ReportDetail 이 제공한다.
 *  자주 고치는 blocks.tsx 밖에 둔다 (2026-11-16: 개발 중 blocks.tsx 를 고칠 때마다 이 컨텍스트가 새로 만들어져,
 *  열어 둔 페이지의 출처 번호가 [1] 대신 [ev123] 으로 보이고 눌러도 열리지 않았다 — Provider 와 읽는 쪽이 서로 다른 컨텍스트를 봄). */
export const CitationContext = createContext<{ onCite: (id: string, from?: string) => void; label: (id: string) => string } | null>(null)  // from = 번호가 붙어 있던 글 (근거 패널이 그 문장을 맨 위에 보여 준다)
