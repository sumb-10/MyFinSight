import type { ReportDoc } from "../../api/types"

// 상단 탭은 섹션 9개 대신 5개 묶음으로 보여 준다. 섹션 ID 는 서버 것 그대로이고, 묶음은 화면에서만 정한다.
// 모르는 섹션은 그 섹션 하나로 된 묶음이 되어 맨 뒤에 붙는다.

export interface NavGroup { id: string; label: string; heading: string; sections: string[] }

export const NAV_GROUPS: NavGroup[] = [
  { id: "summary", label: "개요", heading: "개요", sections: ["summary"] },
  { id: "selection", label: "종목 선정", heading: "종목 선정", sections: ["verdict", "construction", "companies"] },
  { id: "performance", label: "과거 성과", heading: "과거 성과", sections: ["performance"] },
  { id: "market", label: "시장·뉴스", heading: "시장·뉴스", sections: ["market"] },
  { id: "notes", label: "요청·주의·자료", heading: "요청 · 주의 사항 · 자료", sections: ["history", "assumptions", "references"] },
]

const BY_SECTION = new Map(NAV_GROUPS.flatMap((g) => g.sections.map((s) => [s, g.id] as const)))

/** 섹션이 속한 묶음 ID (모르는 섹션은 자기 ID) */
export const groupOf = (sectionId: string) => BY_SECTION.get(sectionId) ?? sectionId

/** 읽는 순서대로 펼친 섹션 순서 (화면 아래 접이식 섹션 정렬에 쓴다). */
export const SECTION_SEQUENCE = NAV_GROUPS.flatMap((g) => g.sections).filter((s) => s !== "summary")

/** 이 리포트에 실제로 있는 묶음과 그 안의 섹션. 요청 내역(history)은 화면이 늘 붙이므로 항상 있다고 본다. */
export function groupsFor(doc: ReportDoc): NavGroup[] {
  const present = new Set<string>([...doc.sections.map((s) => s.id), "history", ...(doc.summary ? ["summary"] : [])])
  const out = NAV_GROUPS.map((g) => ({ ...g, sections: g.sections.filter((s) => present.has(s)) })).filter((g) => g.sections.length)
  for (const s of doc.sections) if (!BY_SECTION.has(s.id)) out.push({ id: s.id, label: doc.nav.find((n) => n.id === s.id)?.title_ko ?? s.title_ko, heading: s.title_ko, sections: [s.id] })
  return out
}
