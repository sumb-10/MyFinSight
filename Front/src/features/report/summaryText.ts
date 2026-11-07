import type { ReportDoc, ReportSummary } from "../../api/types"

// 요약 카드용 문장 도우미. 판정은 서버 summary.validation 그대로이고, 여기서는 읽기 쉬운 한 줄·체크리스트로 바꾸기만 한다.

export type ConditionStatus = "pass" | "warn" | "fail" | "flag" | "info"
export interface ConditionItem { key: string; name: string; status: ConditionStatus }

/** 서버 규칙 이름(name_ko) → 화면용 짧은 이름 */
const SHORT_NAME: Record<string, string> = { 최대낙폭: "낙폭", 목표수익: "목표 수익", "비교지수 대비": "비교지수 대비 성과", "변동성 적합": "변동성" }
/** 주의·미충족일 때 붙이는 서술 (이름 뒤에 은/는 이 붙는다) */
const ISSUE_TEXT: Record<string, string> = { 최대낙폭: "허용 손실보다 컸습니다", 목표수익: "목표에 못 미쳤습니다", "비교지수 대비": "비교지수보다 낮았습니다", "변동성 적합": "기준보다 높았습니다" }

export const shortRuleName = (name: string) => SHORT_NAME[name] ?? name

/** 받침이 있으면 「은」, 없으면 「는」. 한글이 아닌 끝 글자는 「는」. */
export function topic(word: string): string {
  const c = word.trim().slice(-1).charCodeAt(0)
  if (c >= 0xac00 && c <= 0xd7a3) return `${word}${(c - 0xac00) % 28 ? "은" : "는"}`
  return `${word}는`
}

export const isIssue = (s: string) => s === "warn" || s === "fail" || s === "flag"

/** 조건별 결과 목록: 서버 rules_ko(참고 info 제외) + 이름만 온 미충족·주의 규칙. */
export function conditionItems(v: ReportSummary["validation"]): ConditionItem[] {
  const rules = v.rules_ko ?? []
  const out: ConditionItem[] = rules.filter((r) => r.status !== "info").map((r) => ({ key: r.rule, name: r.name_ko, status: r.status as ConditionStatus }))
  const named = new Set(rules.map((r) => r.name_ko))
  for (const r of v.failed_rules_ko ?? []) if (!named.has(r)) out.push({ key: `f:${r}`, name: r, status: "fail" })
  for (const r of v.warned_rules_ko ?? []) if (!named.has(r)) out.push({ key: `w:${r}`, name: r, status: "warn" })
  return out
}

export function conditionCounts(items: ConditionItem[]) {
  return { pass: items.filter((x) => x.status === "pass").length, issue: items.filter((x) => isIssue(x.status)).length }
}

/** 충족·미충족을 한 문장으로: 「낙폭·목표 수익 조건은 지켰고, 변동성은 기준보다 높았습니다.」 판정할 항목이 없으면 null. */
export function conditionSentence(v: ReportSummary["validation"]): string | null {
  const items = conditionItems(v)
  const pass = items.filter((x) => x.status === "pass").map((x) => shortRuleName(x.name))
  const issues = items.filter((x) => isIssue(x.status)).map((x) => `${topic(shortRuleName(x.name))} ${ISSUE_TEXT[x.name] ?? "기준을 충족하지 못했습니다"}`)
  if (!pass.length && !issues.length) return null
  if (!issues.length) return `${pass.join("·")} 조건을 모두 지켰습니다.`
  const tail = issues.join(", ")
  return pass.length ? `${pass.join("·")} 조건은 지켰고, ${tail}.` : `${tail}.`
}

/** 화면 문장의 내부 약어 「BL 1」 같은 구성 번호를 지운다 (「현재 구성 BL 1: 실적 전망」 → 「현재 구성: 실적 전망」). */
export const stripInternalCodes = (s: string) => s.replace(/\s*\bBL\s*\d+\b/g, "")

/** 요약(summary)의 한국어 문장에서만 내부 약어를 지운다. 상세 섹션은 원문 그대로 두어 전문 정보가 남는다. */
export function plainSummary(doc: ReportDoc): ReportDoc {
  if (!doc.summary) return doc
  let changed = false
  const fix = (v: unknown, key: string): unknown => {
    if (typeof v === "string") { if (key.endsWith("_ko")) { const t = stripInternalCodes(v); if (t !== v) { changed = true; return t } } return v }
    if (Array.isArray(v)) { const out = v.map((x) => fix(x, key)); return out.some((x, i) => x !== v[i]) ? out : v }
    if (v && typeof v === "object") {
      let out: Record<string, unknown> | null = null
      for (const [k, x] of Object.entries(v)) { const y = fix(x, k); if (y !== x) (out ??= { ...(v as Record<string, unknown>) })[k] = y }
      return out ?? v
    }
    return v
  }
  const summary = fix(doc.summary, "summary") as ReportSummary
  return changed ? { ...doc, summary } : doc
}
