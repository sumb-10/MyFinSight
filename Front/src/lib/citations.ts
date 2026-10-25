import type { Block, EvidenceRecord, ReportDoc, Section } from "../api/types"

/** 본문 인용 ID: 뉴스 ev123 · 공시 dc45 · 재무 지표 fin:… · 계산값 calc:… (backend/analysis/common/citations.py 와 같다). */
export const CITE_RE = /\[(ev\d+|dc\d+|fin:[^\]\s]+|calc:[^\]\s]+)\]/g

export const kindOf = (id: string): EvidenceRecord["kind"] => (id.startsWith("ev") ? "news" : id.startsWith("dc") ? "disclosure" : id.startsWith("fin:") ? "financial" : id.startsWith("calc:") ? "calc" : "unknown")

export const findCitations = (text: string): string[] => Array.from(text.matchAll(CITE_RE), (m) => m[1])

/** 블록 하나에서 읽는 순서대로 인용 ID 를 모은다 (문단·카드·기업 근거·타임라인 뷰·근거 참조). */
export function blockCitations(b: Block): string[] {
  switch (b.type) {
    case "paragraphs": return b.items.flatMap(findCitations)
    case "cards": return b.items.flatMap((c) => findCitations(c.text_ko))
    case "companies": return b.items.flatMap((it) => [...it.rationale_ko.flatMap(findCitations), ...(it.fact_id ? [it.fact_id] : [])])
    case "timeline": return b.items.flatMap((it) => it.views.flatMap((v) => v.evidence_ids))
    case "evidence_ref": return b.ids ?? []
    default: return []
  }
}

/** 문서 전체의 인용 ID 를 읽는 순서로, 중복 없이. 번호 [1], [2]… 는 이 순서다 (근거 색인의 위치가 아니다). */
export function collectCitations(doc: Pick<ReportDoc, "sections">): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const s of doc.sections) for (const b of s.blocks) for (const id of blockCitations(b)) if (!seen.has(id)) { seen.add(id); out.push(id) }
  return out
}

export function citationNumbers(doc: Pick<ReportDoc, "sections">): Map<string, number> {
  return new Map(collectCitations(doc).map((id, i) => [id, i + 1]))
}

export interface CitedIn { section_id: string; block_title_ko: string; text_ko: string }

/** 이 근거를 인용한 문장들 (출처 패널의 "이 근거를 인용한 문장"). */
export function citedIn(doc: Pick<ReportDoc, "sections">, id: string): CitedIn[] {
  const tag = `[${id}]`
  const out: CitedIn[] = []
  const push = (s: Section, title: string, text: string) => { if (text.includes(tag)) out.push({ section_id: s.id, block_title_ko: title, text_ko: text }) }
  for (const s of doc.sections) for (const b of s.blocks) {
    const title = ("title_ko" in b && b.title_ko) || s.title_ko
    if (b.type === "paragraphs") b.items.forEach((t) => push(s, title, t))
    else if (b.type === "cards") b.items.forEach((c) => push(s, c.title_ko || title, c.text_ko))
    else if (b.type === "companies") b.items.forEach((it) => it.rationale_ko.forEach((t) => push(s, `${it.ticker} · ${it.name}`, t)))
    else if (b.type === "timeline") b.items.forEach((it) => it.views.forEach((v) => { if (v.evidence_ids.includes(id)) out.push({ section_id: s.id, block_title_ko: `${it.date} 뷰`, text_ko: v.summary_ko }) }))
  }
  return out
}
