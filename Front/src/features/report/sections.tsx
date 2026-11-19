import { useState } from "react"
import { BookOpenText, Info, ListChecks, Sigma } from "lucide-react"
import type { Block, CardsBlock, CompaniesBlock, ReportDoc, Section, TableBlock, WeightsCompareBlock } from "../../api/types"
import { fmt, ko } from "../../lib/format"
import { groupBlocks } from "../../lib/reportNormalize"
import { Button, Disclosure, Pagination } from "../../ui"
import { AlertList, allKpis, ConditionRules, keyAlerts, KpiTable, MoreLink, NewsEffect, StatusPill } from "./Dashboard"
import { Cards, CitedText, Paragraphs, RenderBlock } from "./blocks/blocks"
import { useReport } from "./context"
import { metricName } from "./metrics"
import { DEFAULT_VOL_PREF, RISK_TOLERANCE_RANGE, VOL_PREF_LABEL } from "../../lib/tendency"
import { glossaryOf, HelpTip, Term, TermIndex, termsInText, type TermItem } from "./terms"
import { SubPart } from "./SubPart"
import { buildFlowSteps } from "./buildFlow"
import { ThemeScope } from "./blocks/ThemeScope"
import { chosenDescOf, compareRowOf, MockTag, proposed, reasonsOf, strategyInfoOf } from "./proposedView"
import { analysisRisk, benchName, idByLabel, isShortWindow, shortWindowNote } from "./wording"

// 「자세한 분석 보기」의 섹션 본문. 섹션마다 위에 핵심 요약(서버 summary·블록에서 고른 값)을 두고, 서버 블록은 순서대로 그리되
// 긴 문단·큰 비교표는 접어서 둔다. 어떤 블록도 버리지 않는다 — 분류하지 못한 블록은 원래 순서대로 끝에 그린다.

const PROSE: Record<string, string> = {
  verdict: "선택 근거 자세히 보기", construction: "포트폴리오 비중 결정 설명", companies: "선정 과정 설명", market: "시장 분석 원문",
  performance: "성과 해석", assumptions: "분석의 전제", references: "자세한 설명",
}

/** 한 섹션에 문단 묶음이 둘 이상이면 내용(서버 src: 14a 해석 · 14b 서술 · 14c 시장 분석)에 맞는 다른 이름을 쓴다. 같은 이름이 반복되지 않게. */
const PROSE_BY_SRC: Record<string, Record<string, string>> = {
  market: { "14b": "아이디어 해석", "14c": "주요 뉴스와 공시" },
  construction: { "14b": "포트폴리오 비중 결정 설명", "14a": "뉴스 반영 해석" },
}
const proseLabel = (sec: string, bs: Block[]) => (bs[0]?.src && PROSE_BY_SRC[sec]?.[bs[0].src]) || PROSE[sec] || "자세한 설명"

type Entry = { kind: "group"; title: string; open: boolean; blocks: Block[] } | { kind: "prose"; blocks: Block[] } | { kind: "block"; b: Block }

/** 블록 → 표시 단위: 같은 묶음(group_ko)은 하나로, 이어진 문단도 하나로. */
function entries(blocks: Block[]): Entry[] {
  const out: Entry[] = []
  for (const g of groupBlocks(blocks)) {
    if (g.group_ko) { out.push({ kind: "group", title: g.group_ko, open: !!g.open, blocks: g.blocks }); continue }
    for (const b of g.blocks) {
      const last = out[out.length - 1]
      if (b.type === "paragraphs") { if (last?.kind === "prose") last.blocks.push(b); else out.push({ kind: "prose", blocks: [b] }) } else out.push({ kind: "block", b })
    }
  }
  return out
}

const paraCount = (bs: Block[]) => bs.reduce((n, b) => n + (b.type === "paragraphs" ? b.items.length : 0), 0)
const textLen = (b: Block) => (b.type === "cards" ? b.items.reduce((n, c) => n + c.text_ko.length, 0) : 0)

export { SubPart }

/** narrow: 좁은 카드 안(예: 「참고: 뉴스를 반영한 투자의견으로 블랙리터만 최적화를 했다면?」 뉴스 카드 안, 폭 약 708px)에서도 용어를 오른쪽에 — 오른쪽으로 두는 기준을 672px(@2xl)로, 용어 칸을 208px 로 (2026-11-16). */
function ProseFold({ label, blocks, lead, terms, tight, narrow }: { label: string; blocks: Block[]; lead?: React.ReactNode; terms?: TermItem[]; tight?: boolean; narrow?: boolean }) {
  const body = <div className="min-w-0 space-y-4">{lead}{blocks.map((b, i) => b.type === "paragraphs" ? <Paragraphs key={i} items={b.items} tone={b.tone} tight={tight} /> : null)}</div>
  return (
    <Disclosure title={label} summary={paraCount(blocks) ? `${paraCount(blocks)}문단` : undefined}>
      {terms && terms.length > 0 ? (
        // 넓으면 같은 카드 안에 왼쪽 본문 · 오른쪽 「본문에 나온 용어」(256px, 용어 이름을 누르면 아래에 설명), 좁으면 본문 아래 접이식 (2026-11-16 사용자 요청)
        <div className="@container">
          <div className={`grid grid-cols-1 gap-6 ${narrow ? "@2xl:grid-cols-[minmax(0,1fr)_13rem]" : "@3xl:grid-cols-[minmax(0,1fr)_16rem]"}`}>
            {body}
            <aside aria-label="본문에 나온 용어" className={`hidden self-start rounded-xl border border-slate-200 bg-slate-50/70 p-4 ${narrow ? "@2xl:sticky @2xl:top-20 @2xl:block" : "@3xl:sticky @3xl:top-20 @3xl:block"}`}>
              <h4 className="mb-1 text-sm font-semibold text-slate-900">본문에 나온 용어</h4>
              <TermIndex items={terms} />
            </aside>
          </div>
          <div className={`mt-4 ${narrow ? "@2xl:hidden" : "@3xl:hidden"}`}><Disclosure size="sm" title="본문에 나온 용어" summary={`${terms.length}개`}><TermIndex items={terms} /></Disclosure></div>
        </div>
      ) : body}
    </Disclosure>
  )
}

/** 카드 묶음 표시 이름 (2026-11-16 사용자 요청): 「다음에 검토할 수 있는 선택지」 → 「다음 분석에서 바꿔 볼 조건」, 「선택지 N」 → 「조건 N」.
 *  서버 자료는 그대로 읽는다(저장된 리포트도 같은 이름으로 보인다). */
export function cardsView(b: CardsBlock): CardsBlock {
  if (!/^다음에 검토할 수 있는 선택지/.test(b.title_ko ?? "")) return b
  return { ...b, title_ko: "다음 분석에서 바꿔 볼 조건", items: b.items.map((c) => {
    const m = c.title_ko.match(/^선택지 (\d+)$/)
    return m ? { ...c, title_ko: actionTitle(c.text_ko) ?? `조건 ${m[1]}` } : c
  }) }
}

/** 제목이 번호뿐인 카드(2026-11-19 이전 리포트)의 제목을 본문 첫 구절로: 제목만 읽어도 어떤 조건인지 알 수 있게 (2026-11-19 사용자 요청).
 *  「다음 분석에서 백테스트 기간을 3년으로 설정해 보면, …」 → 「백테스트 기간을 3년으로 설정해 보기」,
 *  「A와 B를 필수 포함 목록에서 빼고, …」 → 「A와 B를 필수 포함에서 빼고 다시 고르기」. 알아볼 수 없으면 null(번호 제목). */
export function actionTitle(text: string): string | null {
  const t = text.replace(/\*\*/g, "").replace(/^\[목업\]\s*/, "").trim()
  const must = t.match(/^(.{1,60}?[을를]) 필수 포함 (?:목록|종목)?에서 빼/)
  if (must) return `${must[1]} 필수 포함에서 빼고 다시 고르기`
  const m = t.match(/^(?:다음 분석에서\s+)?([^,.]{4,60}?)면,/)
  if (!m || /려$/.test(m[1])) return null
  return `${m[1].replace(/으$/, "")}기`
}

/** 서버 블록을 순서대로: 묶음·문단·큰 비교표·긴 카드 묶음은 접는다 (묶음은 서버의 group_open 과 관계없이 접힌 채 — 성과의 「검증 상세」만 예외). */
export function Blocks({ blocks, doc, sec }: { blocks: Block[]; doc: ReportDoc; sec: string }) {
  const es = entries(blocks)
  const labels = es.map((e) => (e.kind === "prose" ? proseLabel(sec, e.blocks) : ""))
  const nth = (i: number) => { const same = labels.filter((l, j) => l && l === labels[i] && j <= i).length; return labels.filter((l) => l === labels[i]).length > 1 ? `${labels[i]} (${same})` : labels[i] }  // 서버 src 가 없어 이름이 겹치면 순서 번호
  return (
    <div className="space-y-4">
      {es.map((e, i) => {
        if (e.kind === "group") return <Disclosure key={i} title={e.title} summary={`${e.blocks.length}개 항목`}><div className="space-y-5">{e.blocks.map((b, j) => <RenderBlock key={j} b={b} doc={doc} />)}</div></Disclosure>
        // 용어 목록·출처 번호 정리(tight)는 종합 판단의 「선택 근거 자세히 보기」와 포트폴리오 구성의 「비중 결정 설명」(묶음 밖 14b 문단)에만 (2026-11-16 사용자 요청)
        // + 「5. 시장·뉴스 → 주요 뉴스와 공시」(14c) + 「7. 주의 사항과 전제 → 분석의 전제」(14b) (2026-11-16 사용자 요청)
        const rich = e.kind === "prose" && (sec === "verdict" || (sec === "construction" && e.blocks[0]?.src === "14b" && !e.blocks[0]?.group_ko) || (sec === "market" && e.blocks[0]?.src === "14c") || (sec === "assumptions" && e.blocks[0]?.src === "14b"))
        if (e.kind === "prose") return <ProseFold key={i} label={nth(i)} blocks={e.blocks} tight={rich} terms={rich ? termsInText(glossaryOf(doc), e.blocks.flatMap((b) => (b.type === "paragraphs" ? b.items : []))) : undefined} />
        const b = e.b
        if (b.type === "weights_compare") return <Disclosure key={i} title="전략별 포트폴리오 비중 비교표" summary={`${b.columns.length}개 전략 · ${b.rows.length}종목`}><RenderBlock b={b} doc={doc} /></Disclosure>
        // 카드 묶음을 접을 때는 접이식 제목만 — 펼쳤을 때 같은 제목이 안에서 한 번 더 나오지 않게 (2026-11-16 사용자 요청)
        if (b.type === "cards" && (b.items.length >= 3 || textLen(b) > 600)) { const cb = cardsView(b); return <Disclosure key={i} title={cb.title_ko ?? "자세히 보기"} summary={`${b.items.length}개`}><Cards b={{ ...cb, title_ko: undefined }} /></Disclosure> }
        if (b.type === "cards") return <RenderBlock key={i} b={cardsView(b)} doc={doc} />
        if (b.type === "bar" && sec === "construction" && /기준 비중 대비 변화$/.test(b.title_ko ?? "")) return <Disclosure key={i} title="포트폴리오 비중 변화 그래프" summary={b.title_ko?.replace(/: 기준 비중 대비 변화$/, "")}><RenderBlock b={b} doc={doc} /></Disclosure>  // 위 뉴스 의견 카드의 비중 변화를 그래프로 다시 그린 것이라 접어 둔다
        if (isCompareTable(b)) return <Disclosure key={i} title="전체 전략 비교표" summary={`${b.rows.length}개`}><StrategyTable doc={doc} t={b} /></Disclosure>
        return <RenderBlock key={i} b={b} doc={doc} />
      })}
    </div>
  )
}

const blocksOf = <T extends Block["type"]>(doc: ReportDoc, type: T, sec?: string) => doc.sections.filter((s) => !sec || s.id === sec).flatMap((s) => s.blocks).filter((b) => b.type === type) as Extract<Block, { type: T }>[]

/** 섹션 본문. 섹션 ID 는 서버 것 그대로. */
export function SectionBody({ s, doc }: { s: Section; doc: ReportDoc }) {
  const hasPerf = doc.sections.some((x) => x.id === "performance")
  switch (s.id) {
    case "verdict": { const bs = hasPerf ? s.blocks.filter((b) => b.type !== "kpis") : s.blocks; return <><VerdictWhy doc={doc} />{bs.length > 0 && <SubPart title="더 자세히"><Blocks blocks={bs} doc={doc} sec={s.id} /></SubPart>}</> }  // KPI 전체는 「과거 투자 성과」 맨 위에
    case "construction": return <ConstructionBody s={s} doc={doc} />
    case "market": return <><MarketTopics s={s} doc={doc} /><SubPart title="시장 분석 상세"><Blocks blocks={s.blocks.map((b) => riskRowsKo(b, doc))} doc={doc} sec={s.id} /></SubPart></>
    case "companies": return <CompaniesBody blocks={companyBlocks(s.blocks).map((b) => rejectKo(b, doc))} doc={doc} sec={s.id} />
    case "performance": return <PerformanceBody s={s} doc={doc} />
    case "assumptions": return <><Cautions doc={doc} s={s} /><SubPart title="결과를 읽을 때 유의할 점"><Blocks blocks={s.blocks} doc={doc} sec={s.id} /></SubPart></>
    case "references": return <><ReferencesTop doc={doc} s={s} /><SubPart title="자료 출처·용어·근거 색인"><Blocks blocks={s.blocks} doc={doc} sec={s.id} /></SubPart></>
    default: return <SubPart title={s.title_ko}><Blocks blocks={s.blocks} doc={doc} sec={s.id} /></SubPart>
  }
}

/** 요청 조건 표의 성향 값: 투자성향 코드(conservative 등)는 투자조건 화면의 이름 범위로, 변동성 선호(low 등)는 변동성 기준 이름으로. 두 값은 서로 다른 것이라 따로 쓴다. */
function riskRowsKo(b: Block, doc: ReportDoc): Block {
  if (b.type !== "table" || (b.title_ko !== "요청 내용" && b.title_ko !== "성향 해석 (소프트 조건)")) return b
  const risk = analysisRisk(doc)
  return { ...b, rows: b.rows.map((r) => {
    if (r.k === "투자성향" && typeof r.v === "string" && risk.code) return { ...r, v: `${r.v.replace(/^\w+/, risk.tendency ?? RISK_TOLERANCE_RANGE[risk.code]).replace(/손실 시 (sell|hold|buy_more)\b/, (_m, x: string) => `손실 시 ${ko(x)}`)}${risk.exact ? " [목업]" : ""}` }
    if (r.k === "변동성 선호" && risk.pref) return { ...r, v: `${VOL_PREF_LABEL[risk.pref]}${risk.prefDiffers && risk.code ? ` · 투자성향(${risk.tendency ?? RISK_TOLERANCE_RANGE[risk.code]})의 기본 기준(${VOL_PREF_LABEL[DEFAULT_VOL_PREF[risk.code]]})과 다르게 적용` : ""}${risk.exact ? " [목업]" : ""}` }
    return r
  }) }
}

/** 제외 이유 코드(서버 m3 screen)를 한국어로 보여 준다. 코드는 괄호로 남긴다. 모르는 코드는 그대로. */
const REJECT_KO: Record<string, string> = { metric_missing: "선정 지표를 계산할 자료 없음", rank_beyond_n: "선정 지표 순위가 선정 개수 밖", weight_capacity: "포트폴리오 비중 한도 안에 담을 수 없음" }
function rejectKo(b: Block, doc?: ReportDoc): Block {
  if (b.type !== "table" || !b.columns.some((c) => c.key === "reason") || !b.columns.some((c) => c.key === "ticker")) return b
  const names = proposed(doc)?.structured?.exclusion_reasons ?? REJECT_KO  // 서버가 이름을 주면(제안 계약) 그것을 쓴다
  const mock = !!proposed(doc)?.structured?.exclusion_reasons  // 표 안 글자라 「목업」 표시 대신 [목업]
  return { ...b, rows: b.rows.map((r) => {
    const code = typeof r.reason === "string" ? r.reason : ""
    const key = Object.keys(names).find((k) => code === k || code.startsWith(`${k} `))
    return key ? { ...r, reason: `${names[key]}${code.includes("eps<=0") ? " (EPS 0 이하 또는 재무 자료 없음)" : ""} (${code})${mock ? " [목업]" : ""}` } : r
  }) }
}

/** 2. 기업별 근거 본문: 큰 파트 둘 — 선정된 종목과 근거 / 선정되지 않은 후보. 맞지 않는 블록은 「그 밖의 내용」으로 (버리지 않는다). */
function CompaniesBody({ blocks, doc, sec }: { blocks: Block[]; doc: ReportDoc; sec: string }) {
  const used = new Set<Block>()
  const take = (f: (b: Block) => boolean) => { const r = blocks.filter((b) => !used.has(b) && f(b)); r.forEach((b) => used.add(b)); return r }
  const list = take((b) => !b.group_ko && b.type === "companies")
  take((b) => !b.group_ko && (b.type === "funnel" || b.type === "paragraphs" || b.type === "callout"))  // 「종목을 고른 과정」(선정 과정 설명·단계)은 그리지 않는다 (2026-11-15 사용자 요청)
  const out = take((b) => !!b.group_ko || b.type === "table")
  const rest = blocks.filter((b) => !used.has(b))
  return (
    <>
      {list.length > 0 && <SubPart title="선정 종목"><Blocks blocks={list} doc={doc} sec={sec} /></SubPart>}
      {out.length > 0 && <SubPart title="선정되지 않은 후보"><Blocks blocks={out} doc={doc} sec={sec} /></SubPart>}
      {rest.length > 0 && <SubPart title="그 밖의 내용"><Blocks blocks={rest} doc={doc} sec={sec} /></SubPart>}
    </>
  )
}

/** 기업별 근거 섹션: 「선정 지표」 설명 상자는 따로 두지 않고 「선정 과정」 제목 옆 ? 도움말로 옮긴다 (2026-11-14 사용자 요청).
 *  설명 상자가 없는 예전 리포트는 기업 목록의 지표 이름·방향으로 짧게 만든다. 서버 문장은 그대로 쓴다. */
/** 서버 표 「분석 기준일 선정 목록과 백테스트 시작일 재선정 목록의 차이」는 화면 제목만 「시점별 선정 종목 비교」로 (2026-11-16 사용자 요청). 서버 블록은 그대로 둔다. */
function selectionDiffTitle(b: TableBlock): TableBlock {
  return /^분석 기준일 선정 목록과 백테스트 시작일 재선정 목록의 차이/.test(b.title_ko ?? "") ? { ...b, title_ko: "시점별 선정 종목 비교" } : b
}

function companyBlocks(blocks: Block[]): Block[] {
  const note = blocks.find((b) => b.type === "callout" && b.title_ko === "선정 지표")
  const comp = blocks.find((b) => b.type === "companies") as CompaniesBlock | undefined
  const fallback = comp ? `이 분석은 ${comp.metric_ko}${metricName(comp.metric) ? `(${metricName(comp.metric)})` : ""}이(가) ${comp.direction === "asc" ? "낮은" : "높은"} 순서로 골랐습니다.` : null
  const text = note && note.type === "callout" ? note.text_ko : fallback  // 문서는 화면에 오기 전에 지표 ID 괄호가 이미 빠져 있다 (ReportDetail)
  const help = text ? `선정 지표는 투자할 기업을 고르기 위한 지표입니다. 후보 기업을 이 지표 순서로 줄 세워 위에서부터 고릅니다. ${text}` : null
  return blocks.filter((b) => b !== note).map((b) => (b.type === "funnel" && help ? { ...b, help_ko: help } : b.type === "table" ? excludedTable(selectionDiffTitle(b), comp) : b))
}

/** 「후보였지만(테마에는 해당하지만) 최종 선정에서 빠진 예」 표를 읽기 쉽게 (2026-11-14 사용자 요청).
 *  제목은 실제 자료임이 드러나게(「예」는 예시처럼 보인다), 제외 이유 코드는 문장으로, 「지표값」 열은 지표 이름으로. 값·종목은 서버 그대로. */
function excludedTable(b: TableBlock, comp: CompaniesBlock | undefined): TableBlock {
  const m = /^(?:후보였지만|테마에는 해당하지만) 최종 선정에서 빠진 예 \((.+?) 기준\)$/.exec(b.title_ko ?? "")
  if (!m) return b
  const metric = comp?.metric_ko || "선정 지표"
  const n = comp ? comp.items.filter((x) => x.in_selection_now).length : null
  const REASON: Record<string, string> = {
    "순위 밖": `${metric} 순위가 낮아 최종 ${n ? `${n}개` : "선정"}에 들지 못함`,
    "섹터 선호(순위가 더 낮은 다른 섹터 종목에 자리를 내줌)": "한 섹터에 몰리지 않도록, 순위가 더 낮은 다른 섹터 종목에 자리를 내줌",
    "섹터 선호(같은 섹터 종목이 많아 다른 섹터 종목을 먼저 뽑음)": "같은 섹터 종목이 이미 많아, 다른 섹터 종목을 먼저 뽑음",
    "지표 자료 없음": `${metric}을(를) 계산할 자료가 없음`,
    "최근 12개월 배당 확인 안 됨": "최근 12개월 동안 배당을 준 기록이 없음",
  }
  const reasonKey = b.columns.find((c) => c.label_ko === "제외 이유")?.key
  return {
    ...b, title_ko: `선정에서 빠진 후보 (${m[1]} 기준)`,
    note_ko: [b.note_ko, "순위가 높았던 종목부터 일부만 실었습니다."].filter(Boolean).join(" "),
    columns: b.columns.map((c) => (c.label_ko === "지표값" ? { ...c, label_ko: metric } : c)),
    rows: reasonKey ? b.rows.map((r) => { const v = String(r[reasonKey] ?? ""); return { ...r, [reasonKey]: REASON[v] ?? v } }) : b.rows,
  }
}

/* ───────── 5-1 왜 이런 투자 전략이 선택되었나요? ───────── */

/** 「핵심 판단 이유」 아래 한 줄: 「선택 전략: 최소분산」. 추천 여부 표시는 두지 않는다 (2026-11-14 사용자 요청). */
function VerdictResult({ sm }: { sm: NonNullable<ReportDoc["summary"]> }) {
  return <span className="text-sm text-slate-700">선택 전략: <b className="font-semibold text-slate-900">{sm.verdict.chosen_label_ko}</b></span>
}

/** 선택 전략 설명 한 줄 (낙폭 맞춤안이면 어떤 구성인지, 2026-11-20 사용자 요청: 「이 전략을 고른 이유」 목록이 아니라 선택 전략에 둔다). */
function ChosenDesc({ doc }: { doc: ReportDoc }) {
  const d = chosenDescOf(doc)
  return d ? <span className="mt-1 block text-sm leading-6 text-slate-600" data-testid="chosen-desc">{d}</span> : null
}

function VerdictWhy({ doc }: { doc: ReportDoc }) {
  const sm = doc.summary
  if (!sm) return null
  const o = { short: isShortWindow(doc), shortNote: shortWindowNote(doc) }
  const reasons = reasonsOf(doc, o.short)  // 구조화된 판단 이유(제안 계약)가 있으면 그것, 없으면 서버가 " · " 로 이어 붙인 문장을 틀대로 읽는다
  return (
    <>
      <SubPart title="이 전략을 고른 이유" desc={<><span className="mt-1 inline-flex flex-wrap items-center gap-x-2 gap-y-1"><VerdictResult sm={sm} />{proposed(doc)?.structured?.reasons?.length ? <MockTag /> : null}</span><ChosenDesc doc={doc} /></>}>
        {reasons.length ? (
          <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200" aria-label="이 전략을 고른 이유">
            {reasons.map(({ t, r }, i) => (
              <li key={i} className="flex gap-3 px-4 py-3">
                <span className={`mt-1.5 size-2 shrink-0 rounded-full ${r.tone === "good" ? "bg-emerald-500" : r.tone === "warn" ? "bg-amber-500" : "bg-slate-400"}`} aria-hidden />
                <div className="min-w-0">
                  {r.title && <p className="text-sm font-bold text-slate-950">{r.title}</p>}
                  <p className={r.title ? "mt-0.5 text-sm leading-6 text-slate-700" : "text-sm leading-6 text-slate-800"}><CitedText text={r.title ? r.desc : t} /></p>
                </div>
              </li>
            ))}
          </ul>
        ) : <p className="text-sm text-slate-600">요약된 판단 이유가 없습니다.</p>}
        {o.short && reasons.some(({ r }) => r.annual) && <p className="text-xs leading-5 text-slate-600">연 환산 표시: {o.shortNote}</p>}
      </SubPart>
    </>
  )
}

/* ───────── 5-2 투자 종목과 비중은 어떻게 결정됐나요? ───────── */

function BuildFlow({ doc }: { doc: ReportDoc }) {
  const steps = buildFlowSteps(doc)  // 단계별 짧은 설명은 기존 리포트 자료로 만든다 (buildFlow.ts, 2026-11-16 사용자 요청)
  return (
    <SubPart title="포트폴리오 비중이 정해진 과정">
      <ol className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-4" aria-label="포트폴리오 비중 결정 과정">
        {steps.map((x, i) => (
          <li key={x.t} className={`relative rounded-xl border p-3 ${x.off ? "border-dashed border-slate-300 bg-white text-slate-500" : "border-slate-200 bg-slate-50"}`}>
            {/* 원 안 숫자는 가로·세로 가운데 (inline-grid + place-items-center + leading-none, 원 크기는 그대로 size-5).
                글자 상자의 위·아래 여백을 브라우저마다 다르게 읽어(Chrome 은 숫자가 약 1px 아래, Safari 는 위) 상자만 가운데 두면 숫자가 치우친다
                → text-box 로 상자를 숫자 높이(대문자 높이~기준선)로 잘라 어느 브라우저에서나 숫자 자체가 가운데 오게 한다 (2026-11-16 픽셀 측정) */}
            <p className="flex items-center gap-2 text-sm font-semibold text-slate-900"><span className="inline-grid size-5 shrink-0 place-items-center rounded-full border border-slate-400 bg-white text-[11px] font-bold leading-none tabular-nums text-slate-700" aria-hidden><span className="block [text-box:trim-both_cap_alphabetic]">{i + 1}</span></span>{x.t}</p>
            <p className="mt-1 break-words text-xs leading-5 text-slate-600">{x.d}</p>
          </li>
        ))}
      </ol>
    </SubPart>
  )
}

/** 기준 비중 vs 선택 전략 비중 (같은 표·같은 시점: 서버 비교표의 백테스트 시작일 값). 선택 전략이 표에 없으면 그리지 않고 어디서 보는지 안내한다. */
function ChosenWeights({ doc, children }: { doc: ReportDoc; children?: React.ReactNode }) {
  const wc0 = blocksOf(doc, "weights_compare", "construction")[0] as WeightsCompareBlock | undefined
  const cvb = proposed(doc)?.chosen_vs_baseline
  const chosen = doc.header.chosen_portfolio_id
  // 선택 전략이 서버 비교표에 없을 때(낙폭 맞춤안 등) 제안 계약의 「선택 vs 기준」 값이 있으면 같은 모양의 표로 바꿔 그린다
  const wc: WeightsCompareBlock | undefined = wc0 && wc0.columns.some((c) => c.id === chosen) ? wc0 : cvb ? { type: "weights_compare", title_ko: "", baseline_id: cvb.baseline_id, columns: [{ id: cvb.chosen_id, label_ko: cvb.chosen_label_ko, kind: "", rule_ko: "" }, ...(cvb.baseline_id !== cvb.chosen_id ? [{ id: cvb.baseline_id, label_ko: cvb.baseline_label_ko, kind: "", rule_ko: "" }] : [])], rows: cvb.rows.map((r) => ({ ticker: r.ticker, name: r.name, sector: "", weights: { [cvb.chosen_id]: r.chosen, [cvb.baseline_id]: r.baseline } })), cash: { [cvb.chosen_id]: cvb.cash.chosen, [cvb.baseline_id]: cvb.cash.baseline }, ex_ante: {} } : wc0
  if (!wc) return children ? <SubPart title="백테스트 시작일의 기준 비중과 선택 전략 비중">{children}</SubPart> : null
  const col = wc.columns.find((c) => c.id === chosen)
  const base = wc.columns.find((c) => c.id === wc.baseline_id)
  if (!col || !base) return <SubPart title="백테스트 시작일의 기준 비중과 선택 전략 비중">{children || <p className="text-sm text-slate-600">선택 전략의 포트폴리오 비중은 개요의 종목 구성과 투자 금액, 리밸런싱 기록에 있습니다.</p>}</SubPart>
  const same = col.id === base.id
  const rows = [...wc.rows].sort((a, b) => (b.weights[col.id] ?? 0) - (a.weights[col.id] ?? 0))
  // 묶은 세로 막대 (2026-11-15 사용자 요청: 점 그래프 대신 비교가 바로 보이는 다른 그래프로). 종목마다 기준(회색)·선택(파랑) 막대를 같은 바닥선에 나란히,
  // 막대 위에 값(%). 차이(%p) 숫자는 쓰지 않는다
  const top = Math.max(0.01, ...wc.rows.flatMap((r) => [r.weights[col.id] ?? 0, r.weights[base.id] ?? 0]), wc.cash[col.id] ?? 0, wc.cash[base.id] ?? 0)
  const step = top > 0.5 ? 0.1 : 0.05
  const max = Math.ceil(top / step - 1e-3) * step  // 눈금이 깔끔하게 끝나도록 5%·10% 단위로 올림
  const ticks = Array.from({ length: Math.round(max / step) + 1 }, (_, i) => i * step)
  const h = (v: number | undefined) => `${(Math.min(Math.max(v ?? 0, 0), max) / max) * 100}%`
  const num = (v: number | undefined) => ((v ?? 0) * 100).toFixed(1)
  const items = [...rows.map((r) => ({ key: r.ticker, label: r.ticker, name: r.name, a: r.weights[col.id], b: r.weights[base.id] })), ...(((wc.cash[col.id] ?? 0) >= 0.0005 || (wc.cash[base.id] ?? 0) >= 0.0005) ? [{ key: "cash", label: "현금", name: "현금", a: wc.cash[col.id], b: wc.cash[base.id] }] : [])]
  const H = "h-48 sm:h-60"
  const bar = (v: number | undefined, cls: string, label: string) => (
    <span className="flex h-full w-full max-w-8 flex-col justify-end">
      <span className={`relative w-full rounded-t-sm ${cls}`} style={{ height: h(v) }}><span className={`absolute inset-x-0 bottom-full mb-0.5 whitespace-nowrap text-center tabular-nums ${label}`}>{num(v)}</span></span>
    </span>
  )
  return (
    <SubPart title="백테스트 시작일의 기준 비중과 선택 전략 비중" desc={wc !== wc0 ? <MockTag /> : undefined}>
      {same && <p className="text-xs text-slate-600">선택 전략이 기준 비중({base.label_ko})과 같습니다.</p>}{/* 예전에는 파트 설명줄이 「선택 전략 = 기준 비중」을 알렸다 — 설명줄을 질문으로 바꿔 범례 자리로 (2026-11-16) */}
      {!same && <p className="flex flex-wrap gap-4 text-xs text-slate-600"><span className="inline-flex items-center gap-1.5"><i className="inline-block size-3 rounded-sm bg-slate-300" />기준 비중 ({base.label_ko})</span><span className="inline-flex items-center gap-1.5"><i className="inline-block size-3 rounded-sm bg-blue-600" />선택 전략 비중 ({col.label_ko})</span><span className="text-slate-500">막대 위 숫자 = 포트폴리오 비중(%)</span></p>}
      {/* 좁은 화면은 종목마다 최소 폭을 지키고 옆으로 밀어 본다 (티커·숫자가 잘리지 않게) */}
      <div className="overflow-x-auto"><div className="flex gap-2 pt-4" style={{ minWidth: `${2.5 + items.length * (same ? 2.5 : 3.5)}rem` }}>
        <div aria-hidden className={`relative ${H} w-8 shrink-0 text-right text-[11px] tabular-nums text-slate-500`}>{ticks.map((t) => <span key={t} className="absolute right-0 translate-y-1/2" style={{ bottom: h(t) }}>{Math.round(t * 100)}%</span>)}</div>
        <div className="min-w-0 flex-1">
          <div className={`relative ${H}`}>
            <span aria-hidden className="pointer-events-none absolute inset-0">{ticks.map((t, i) => <span key={t} className={`absolute inset-x-0 h-px ${i === 0 ? "bg-slate-300" : "bg-slate-100"}`} style={{ bottom: h(t) }} />)}</span>
            <ul aria-label="종목별 포트폴리오 비중 비교" className="relative flex h-full items-end">
              {items.map((x) => (
                <li key={x.key} aria-label={same ? `${x.label} ${fmt(x.a, "pct1")}` : `${x.label} 기준 ${fmt(x.b, "pct1")}, 선택 ${fmt(x.a, "pct1")}`} title={same ? `${x.label} ${fmt(x.a, "pct1")}` : `${x.label} · 기준 ${fmt(x.b, "pct1")} · 선택 ${fmt(x.a, "pct1")}`} className="flex h-full min-w-0 flex-1 items-end justify-center gap-0.5 px-0.5 sm:gap-1 sm:px-1.5">
                  {!same && bar(x.b, "bg-slate-300", "text-[11px] text-slate-500")}
                  {bar(x.a, "bg-blue-600", "text-[11px] font-semibold text-slate-900")}
                </li>
              ))}
            </ul>
          </div>
          <div aria-hidden className="flex">{items.map((x) => <span key={x.key} title={x.name} className="min-w-0 flex-1 truncate px-0.5 pt-1.5 text-center text-xs font-medium text-slate-700">{x.label}</span>)}</div>
        </div>
      </div></div>
      {children && <div className="pt-3">{children}</div>}
    </SubPart>
  )
}

/** 선택 전략 비중 아래 금액 표의 이름: 서버 「배분 금액 (최소분산, 백테스트 시작일 초기 투자금 13,755 USD 기준, 원화는 시작일 환율)」을
 *  무엇을 언제 얼마로 나눈 표인지 바로 보이게 바꾼다 (2026-11-14 사용자 요청). 틀이 다르면 서버 제목 그대로. */
const START_AMOUNT = /^배분 금액 \((.+?), 백테스트(?: 시작일)? 초기 투자금 ([\d,.]+ USD) 기준(, 원화는 시작일 환율)?\)$/
function startAmount(b: Block, doc: ReportDoc): Block {
  const m = b.type === "table" ? START_AMOUNT.exec(b.title_ko ?? "") : null
  if (!m || b.type !== "table") return b
  const start = doc.header.backtest_period?.as_of ?? doc.header.backtest_period?.start  // 첫 투자일 = 첫 거래일(백테스트 시작일). start 는 요청한 기간 시작이라 휴일일 수 있다 (2022-11-05 토요일)
  return { ...b, title_ko: `백테스트 시작일 투자 금액 (${m[1]})`, subtitle_ko: `백테스트를 시작한 날${start ? `(${start})` : ""} 첫 투자금 ${m[2]}를 선택 전략(${m[1]}) 포트폴리오 비중대로 종목마다 나눈 금액입니다.${m[3] ? " 원화는 그날 환율로 계산했습니다." : ""} 이후 매달 적립한 금액과 리밸런싱은 아래 「과거 비중 조정 기록」에 있습니다.` }
}

/** 「분석 기준일의 종목과 비중」 파트 이름: '분석 기준일' 이라는 말 대신 그 날짜로 (2026-11-16 사용자 요청).
 *  연도까지 쓴다 — 백테스트 시작일과 월·일이 같은 경우가 많다(1·3년 백테스트). 날짜가 없으면 예전 이름. */
export function nowTitle(doc: Pick<ReportDoc, "header">): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(doc.header.selection_as_of ?? "")
  return m ? `${m[1]}년 ${Number(m[2])}월 ${Number(m[3])}일의 종목과 포트폴리오 비중` : "분석한 날의 종목과 포트폴리오 비중"
}

/** 3. 포트폴리오 구성 본문 (2026-11-14 사용자 요청: 파트가 무엇을 뜻하는지 헷갈림 → 질문 하나에 파트 하나).
 *  과정 → 선택 전략의 비중·금액 → 다른 전략과 비교 → 뉴스 반영 전략(BL) → 운용 기록 → 분석 기준일 구성 → 그 밖의 내용.
 *  서버 블록은 종류·제목·묶음으로 자리를 정하고, 어디에도 맞지 않는 블록은 맨 아래에 원래 순서대로 — 버리는 블록은 없다. */
function ConstructionBody({ s, doc }: { s: Section; doc: ReportDoc }) {
  const chosen = doc.header.chosen_portfolio_id
  const wc = blocksOf(doc, "weights_compare", "construction")[0] as WeightsCompareBlock | undefined
  const chosenBl = !!wc?.columns.some((c) => c.id === chosen && c.kind === "black_litterman")
  const used = new Set<Block>()
  const take = (f: (b: Block, t: string) => boolean) => { const r = s.blocks.filter((b) => !used.has(b) && f(b, (b as { title_ko?: string | null }).title_ko ?? "")); r.forEach((b) => used.add(b)); return r }
  const top = (b: Block) => !b.group_ko
  const blT = (t: string) => /Black-Litterman|뉴스 뷰/.test(t)
  const now = take((b) => b.group_ko === "분석 기준일의 현재 구성")
  // 「현재 구성 (분석 기준일 …)」 안내 상자는 뉴스 기간·계산 세부값이라 따로 두지 않고 「종목·비중을 정한 근거」(예전 이름 「현재 구성 설명」) 토글 맨 위에 작은 글씨로 (2026-11-14·15 사용자 요청)
  const nowNote = now.filter((b) => b.type === "callout" && /^현재 구성 \(분석 기준일/.test(b.title_ko ?? ""))
  const nowProse = now.filter((b) => b.type === "paragraphs")
  const amount = take((b, t) => top(b) && b.type === "table" && t.startsWith("배분 금액")).map((b) => startAmount(b, doc))
  take((b, t) => top(b) && ((b.type === "bar" && /기준 비중 대비 변화$/.test(t)) || (b.type === "paragraphs" && b.src === "14a")))  // 비중 변화 그래프·뉴스 반영 해석은 그리지 않는다 (2026-11-15 사용자 요청)
  const bl = take((b, t) => top(b) && ((b.type === "cards" && blT(t)) || (b.type === "callout" && blT(t))))
  // 기준 전략 등 BL 이 아닌 전략의 기간 성과 한 줄(「시가총액비중 (walk-forward)」)은 그리지 않는다 — 비중 비교 파트에 성과 숫자가 끼어 헷갈리고,
  // 같은 성과가 「4. 과거 성과 → 전략 비교」에 모든 전략과 나란히 있다 (2026-11-14 사용자 요청). BL 의 것은 BL 고유 설명이 있어 위 bl 파트에 남긴다
  take((b, t) => top(b) && b.type === "callout" && /\(walk-forward\)$/.test(t))
  const compare = take((b) => top(b) && (b.type === "weights_compare" || (b.type === "paragraphs" && b.src === "14b")))
  const runs = take((b) => top(b) && b.type === "timeline")
  const rest = s.blocks.filter((b) => !used.has(b))
  const pill = (t: string, cls: string) => <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${cls}`}>{t}</span>
  return (
    <>
      {/* 3. 포트폴리오 구성 파트 순서 (2026-11-16 사용자 표): 1 과정 → 2 분석 기준일 → 3 백테스트 시작일 비중 → 4 전략별 → 5 뉴스 반영 → 6 조정 기록 */}
      <BuildFlow doc={doc} />
      {now.length > 0 && <SubPart title={nowTitle(doc)}><NowParts now={now} nowProse={nowProse} nowNote={nowNote} doc={doc} /></SubPart>}{/* 예전 「분석 기준일의 현재 구성」 묶음 안에서처럼 접지 않고 그대로 그린다 (카드마다 접힘이 들쭉날쭉하지 않게) */}
      <ChosenWeights doc={doc}>{amount.length > 0 ? <Blocks blocks={amount} doc={doc} sec={s.id} /> : null}</ChosenWeights>
      {compare.length > 0 && <SubPart title="전략별 투자 비중"><Blocks blocks={compare} doc={doc} sec={s.id} /></SubPart>}
      {bl.length > 0 && <SubPart title="뉴스를 반영한 포트폴리오 비중" badge={chosenBl ? pill("선택 전략", "bg-blue-600 text-white") : pill("비교용 구성", "bg-slate-100 text-slate-600")}>
        {/* 카드 묶음 제목 「뉴스로 조정한 비중 (백테스트 시작일 · Black-Litterman)」은 파트 제목과 겹쳐 뺀다 (2026-11-16 사용자 요청). 카드가 많으면 예전처럼 접되 제목은 쉬운 말로 */}
        {bl.map((b, i) => b.type === "cards"
          ? (b.items.length >= 3 ? <Disclosure key={i} title="뉴스로 만든 구성" summary={`${b.items.length}개`}><Cards b={{ ...b, title_ko: undefined }} /></Disclosure> : <Cards key={i} b={{ ...b, title_ko: undefined }} />)
          : <RenderBlock key={i} b={b} doc={doc} />)}
      </SubPart>}
      {runs.length > 0 && <SubPart title="과거 포트폴리오 비중 조정 기록"><Blocks blocks={runs} doc={doc} sec={s.id} /></SubPart>}
      {rest.length > 0 && <SubPart title="그 밖의 내용"><Blocks blocks={rest} doc={doc} sec={s.id} /></SubPart>}
    </>
  )
}

/** 「분석 기준일의 종목과 비중」 안 (2026-11-16 사용자 요청):
 *  ① 뉴스로 조정한 비중 — 의견 카드 안 「뉴스로 만든 투자 의견」과 「숫자로 보기」 사이에 「종목·비중을 정한 근거」
 *  ② 추천 전략 구성 — 추천 전략의 배분 비중(도넛)과 배분 금액 표.
 *  선택 전략이 뉴스를 쓰면 ①→②, 쓰지 않으면 ② 다음에 ①을 접힌 「참고: 뉴스를 반영한 투자의견으로 블랙리터만 최적화를 했다면?」으로 (2026-11-19 사용자 요청: 블랙리터만 설명 두 줄을 그 밑에).
 *  뉴스 의견 카드가 없으면(뉴스 반영 끔 등) 「종목·비중을 정한 근거」는 예전처럼 맨 위. 어디에도 맞지 않는 블록은 맨 아래 그대로 (버리지 않음). */
function NowParts({ now, nowProse, nowNote, doc }: { now: Block[]; nowProse: Block[]; nowNote: Block[]; doc: ReportDoc }) {
  // 「계산 기준」 안내 상자(뉴스·공시 기간·건수)는 빼고, 기간·건수는 아래 본문에 한 번만 (2026-11-16 사용자 요청)
  // 본문에 나온 용어·공백 정리도 다른 본문처럼 (2026-11-16 사용자 요청)
  const fold = nowProse.length > 0 ? <ProseFold label="종목·포트폴리오 비중을 정한 근거" blocks={nowProse} tight narrow terms={termsInText(glossaryOf(doc), nowProse.flatMap((b) => (b.type === "paragraphs" ? b.items : [])))} /> : null
  const rest = now.filter((b) => b.type !== "paragraphs" && !nowNote.includes(b))
  const news = rest.filter((b): b is CardsBlock => b.type === "cards" && /^현재 구성 BL \d+:/.test(b.title_ko ?? ""))
  const rec = rest.filter((b) => b.type === "donut" || (b.type === "table" && (b.title_ko ?? "").startsWith("배분 금액")))
  const other = rest.filter((b) => !news.includes(b as CardsBlock) && !rec.includes(b))
  // 선택 전략이 뉴스를 쓰는가: 뉴스 반영 구성(bl_N · wf_bl_news)이거나 그것을 바탕으로 한 낙폭 맞춤안 (2026-11-16 사용자 요청).
  // 쓰지 않으면 추천 전략 구성을 맨 앞에 두고, 뉴스 카드는 접힌 「참고」로 내린다 — 추천 비중에 뉴스가 반영된 것처럼 읽히지 않게
  const usesNews = /(^|_)(bl_\d+|bl_news)$/.test(doc.header.chosen_portfolio_id ?? "")
  const newsCards = news.map((b, i) => <Cards key={i} b={b} between={i === 0 ? fold : undefined} />)
  const recPart = rec.length > 0 && (
    <section aria-label="추천 전략 구성" className="space-y-3">
      <h4 className="text-base font-semibold text-slate-900">추천 전략 구성</h4>{/* 제목 아래 작은 설명은 없앴다 (2026-11-16 사용자 요청) */}
      {rec.map((b, i) => <RenderBlock key={i} b={b} doc={doc} />)}
    </section>
  )
  return (
    <div className="space-y-6">
      {news.length === 0 && fold}
      {news.length > 0 && usesNews && newsCards}
      {recPart}
      {news.length > 0 && !usesNews && (
        <Disclosure title="참고: 뉴스를 반영한 투자의견으로 블랙리터만 최적화를 했다면?" summary="선택 전략에는 반영하지 않음">
          <div className="space-y-4">
            <p className="text-xs leading-5 text-slate-500">분석 모델이 기사 제목과 공시를 읽고 제안한 투자 의견을 기준 비중에 반영한 비교용 구성입니다.<br />
              블랙리터만(Black-Litterman)은 기준 비중을 출발점으로 두고, 투자 의견을 얼마나 확신하는지에 따라 비중을 조금씩 옮기는 방법입니다. 확신이 약하면 기준 비중에 가깝게, 강할수록 의견 쪽으로 더 옮깁니다.</p>
            {newsCards}
          </div>
        </Disclosure>
      )}
      {other.map((b, i) => <RenderBlock key={i} b={b} doc={doc} />)}
    </div>
  )
}

/* ───────── 5-4 시장과 뉴스는 어떻게 분석했나요? ───────── */

function MarketTopics({ s, doc }: { s: Section; doc: ReportDoc }) {
  const rep = useReport()
  const themes = s.blocks.find((b) => b.type === "table" && b.title_ko === "추출한 테마") as TableBlock | undefined
  const ne = doc.summary?.news_effect
  const topics = proposed(doc)?.market_topics
  const KIND: Record<string, string> = { market: "전체 시장", industry: "관련 산업", theme: "투자 테마", evidence: "뉴스·공시 근거" }
  return (
    <>
      {topics && topics.length > 0 && (
        <SubPart title="주제별 요약">
          <p className="-mt-1 flex items-center text-xs text-slate-500">주제 분류<MockTag /></p>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {topics.map((t) => (
              <div key={t.id} className="flex flex-col rounded-xl border border-slate-200 p-4">
                <p className="text-xs font-semibold text-blue-700">{KIND[t.kind] ?? t.kind}</p>
                <h4 className="mt-0.5 text-base font-semibold text-slate-900">{t.title_ko}</h4>
                <p className="mt-1.5 text-sm leading-6 text-slate-700">{t.summary_ko}</p>
                {t.points_ko.length > 0 && <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-xs leading-5 text-slate-600">{t.points_ko.map((x, i) => <li key={i}>{x}</li>)}</ul>}
                {rep && t.evidence_ids.length > 0 && <button type="button" onClick={() => rep.openDrawer({ ids: t.evidence_ids, title: t.title_ko })} className="mt-auto self-start pt-2 text-xs font-semibold text-blue-700 hover:underline">근거 {t.evidence_ids.length}건 보기</button>}
              </div>
            ))}
          </div>
        </SubPart>
      )}
      {/* 분석 범위: 투자 테마만 카드 폭 전체로 (테마는 넓으면 2~3칸으로 나란히). 「시장 분석에 인용한 뉴스·공시」는 아래 「시장 분석 상세」에 같은 자료가 있어 두지 않는다 (2026-11-14 사용자 요청) */}
      {themes && (
        <SubPart title="분석한 투자 테마">
          {/* 「투자 테마 N개」 제목과 바깥 테두리 카드는 없앴다 (2026-11-16 사용자 요청) — 테마 카드만 바로 */}
          <div>
            <ul aria-label="분석한 투자 테마" className={`grid grid-cols-1 gap-3 ${themes.rows.length === 2 ? "sm:grid-cols-2" : themes.rows.length >= 3 ? "sm:grid-cols-2 lg:grid-cols-3" : ""}`}>{themes.rows.map((r, i) => <li key={i} className="rounded-lg bg-slate-50 px-3 py-2.5 text-sm leading-6"><b className="font-semibold text-slate-900">{String(r.label ?? "")}</b>{r.desc ? <div className="mt-1.5"><ThemeScope text={String(r.desc)} size="xs" /></div> : null}</li>)}</ul>
          </div>
        </SubPart>
      )}
      {ne && <SubPart title="뉴스 반영 전후 성과"><NewsEffect n={ne} /></SubPart>}
    </>
  )
}

/* ───────── 5-5 과거 투자 성과는 어땠나요? ───────── */

const isCompareTable = (b: Block): b is TableBlock => b.type === "table" && b.columns.some((c) => c.key === "sharpe") && b.columns.some((c) => c.key === "mdd")

/* 4. 투자 조건 충족 여부 → 「조건별 근거 보기」 (서버 묶음 이름 「검증 상세」, 2026-11-16 사용자 요청): 기본으로 접고,
   예전 리포트의 두 표(검증 규칙 · 전체 포트폴리오 검증 요약)는 규칙 번호·수준 열 없이 새 이름으로 보여 준다. 새 리포트는 서버가 새 표를 준다. */
const VAL_GROUP = "검증 상세", VAL_TITLE = "조건별 근거 보기"
const RULE_PLAIN: Record<string, string> = { R1: "최대낙폭과 허용 한도", R1b: "비교지수와 최대낙폭 비교", R2: "목표 수익률 달성 여부", R3: "비교지수와 수익률 비교", R7: "변동성 기준 충족 여부", R4b: "조정일 사이 종목 비중 변화", R5b: "조정일 사이 업종 비중 변화", R9: "주식과 현금 비중" }
/** 판정 없이 값만 보여 주는 참고 항목의 결과 이름 (2026-11-20 사용자 요청: '측정 결과' 는 뜻이 잘 드러나지 않음). 서버 validation_text.MEASURED 와 같은 말. */
const MEASURED = "참고(판정 없음)"
const MEASURED_NOTE_TAIL = "참고(판정 없음)는 기준 충족 여부를 판정하지 않고 값만 알려 주는 항목입니다."
const MEASURED_NOTE = `판정 보류는 평가 기간이 짧아 기준 충족 여부를 판단하지 않은 항목, ${MEASURED_NOTE_TAIL}`
export function validationTableView(b: Block, chosenLabel?: string | null): Block {
  if (b.type !== "table") return b
  const t = b.title_ko ?? ""
  if (/^검증 규칙 \(/.test(t) && b.columns.some((c) => c.key === "rule")) {
    const res = (r: Record<string, unknown>) => { const st = String(r.status ?? ""); if (st === "참고") return ["R2", "R7"].includes(String(r.rule)) && /vs|목표/.test(String(r.msg ?? "")) && /창이 짧아|참고만/.test(String(r.msg ?? "")) ? "판정 보류" : MEASURED; return st === "통과" ? "충족" : st }
    return { ...b, title_ko: t.replace(/^검증 규칙/, "선택 전략의 조건별 결과"), note_ko: MEASURED_NOTE,
      columns: [{ key: "name", label_ko: "점검 항목", format: "text" }, { key: "msg", label_ko: "기준과 측정값", format: "text" }, { key: "status", label_ko: "결과", format: "text" }] as TableBlock["columns"],
      rows: b.rows.map((r) => ({ ...r, name: RULE_PLAIN[String(r.rule)] ?? r.name, status: res(r) })) }
  }
  // 새 리포트(서버가 준 표)와 덧씌운 글의 표: 예전 이름 '측정 결과' → '참고(판정 없음)' (2026-11-20 사용자 요청)
  if (/^선택 전략의 조건별 결과/.test(t) && b.rows.some((r) => r.status === "측정 결과")) {
    return { ...b, note_ko: b.note_ko ? b.note_ko.replace(/측정 결과는 기준 충족 여부를 따지지 않고 값을 알려 주는 항목입니다\.?/, MEASURED_NOTE_TAIL) : MEASURED_NOTE,
      rows: b.rows.map((r) => (r.status === "측정 결과" ? { ...r, status: MEASURED } : r)) }
  }
  if (t === "전체 포트폴리오 검증 요약" && b.columns.some((c) => c.key === "warns")) {
    const plain = (x: unknown) => String(x ?? "-").split(", ").filter((y) => y && y !== "-").map((y) => { const m = /^(R\d+b?) (.+?)( \(허용 초과\))?$/.exec(y); return m ? `${RULE_PLAIN[m[1]] ?? m[2]}${m[3] ? "(허용 초과)" : ""}` : y })
    return { ...b, title_ko: "전략별 점검 결과", note_ko: undefined,
      columns: [{ key: "name", label_ko: "전략", format: "text" }, { key: "status", label_ko: "결과", format: "text" }, { key: "reason", label_ko: "이유", format: "text" }] as TableBlock["columns"],
      rows: b.rows.map((r) => { const f = plain(r.fails), w = plain(r.warns); return { ...r, status: chosenLabel && r.name === chosenLabel ? `${r.status} · 최종 선택` : r.status, reason: [...f.map((x) => `${x}: 미통과`), ...w.map((x) => `${x}: 주의`)].join(" · ") || "-" } }) }
  }
  return b
}
function PerformanceBody({ s, doc }: { s: Section; doc: ReportDoc }) {
  const A: Entry[] = [], B: Entry[] = [], C: Entry[] = [], V: Entry[] = [], top: Entry[] = [], prose: Entry[] = [], other: Entry[] = []
  for (const e of entries(s.blocks)) {
    if (e.kind === "group") {
      const hasRule = e.blocks.some((b) => b.type === "table" && b.columns.some((c) => c.key === "rule"))
      if (hasRule || e.title.includes("검증")) V.push(e); else if (/연도|월별/.test(e.title)) A.push(e); else other.push(e)
    } else if (e.kind === "prose") prose.push(e)
    else {
      const b = e.b
      if (b.type === "kpis") continue  // KPI 전체는 아래 「주요 성과 지표」
      if (b.type === "callout") top.push(e)
      else if (b.type === "line") A.push(e)
      else if (b.type === "area") B.push(e)
      else if (isCompareTable(b) || b.type === "bar") C.push(e)
      else other.push(e)
    }
  }
  const draw = (es: Entry[]) => es.map((e, i) => e.kind === "group" ? (e.title === VAL_GROUP
      ? <Disclosure key={i} title={VAL_TITLE} summary={`${e.blocks.length}개 항목`}><div className="space-y-5">{e.blocks.map((b, j) => <RenderBlock key={j} b={validationTableView(b, doc.header.chosen_label_ko)} doc={doc} />)}</div></Disclosure>  // 기본으로 접음 (2026-11-16)
      : <Disclosure key={i} title={e.title} summary={`${e.blocks.length}개 항목`} defaultOpen={e.open}><div className="space-y-5">{e.blocks.map((b, j) => <RenderBlock key={j} b={b} doc={doc} />)}</div></Disclosure>)
    // 「성과 해석」에도 본문에 나온 용어 목록·공백·출처 번호 정리 (2026-11-16 사용자 요청)
    : e.kind === "prose" ? <ProseFold key={i} label={PROSE.performance} blocks={e.blocks} tight terms={termsInText(glossaryOf(doc), e.blocks.flatMap((b) => (b.type === "paragraphs" ? b.items : [])))} />
    : isCompareTable(e.b) ? <Disclosure key={i} title="전체 전략 비교표" summary={`${e.b.rows.length}개`}><StrategyTable doc={doc} t={e.b} /></Disclosure>
    : <RenderBlock key={i} b={e.b} doc={doc} />)
  const cmp = C.map((e) => (e.kind === "block" && isCompareTable(e.b) ? e.b : null)).find(Boolean) ?? null
  const sm = doc.summary
  return (
    <>
      <SubPart title="주요 성과 지표" info={isShortWindow(doc) ? <>{shortWindowNote(doc)} 전체 기간 수익률은 연평균이 아닌 기간 전체의 수익률입니다.</> : undefined}><KpiTable kpis={allKpis(doc)} doc={doc} />{top.length > 0 && draw(top)}</SubPart>
      {A.length > 0 && <SubPart title="수익률 추이">{draw(A)}</SubPart>}
      <SubPart title="하락과 변동성"><RiskFacts doc={doc} cmp={cmp} />{draw(B)}</SubPart>
      {(C.length > 0 || cmp) && <SubPart title="전략 비교">{cmp && <CompareMini doc={doc} t={cmp} />}{draw(C)}</SubPart>}
      <SubPart id="perf-validation" title="투자 조건 충족 여부">{sm && <ConditionRules v={sm.validation} verdict={sm.verdict} bench={benchName(sm)} doc={doc} />}{draw(V)}</SubPart>
      {(prose.length > 0 || other.length > 0) && <SubPart title="더 자세히">{draw(prose)}{draw(other)}</SubPart>}
    </>
  )
}

const chosenRow = (doc: ReportDoc, t: TableBlock | null) => t?.rows.find((r) => r.name === doc.header.chosen_label_ko) ?? null

function RiskFacts({ doc, cmp }: { doc: ReportDoc; cmp: TableBlock | null }) {
  const k = allKpis(doc)
  const mdd = k.find((x) => x.id === "mdd"), sharpe = k.find((x) => x.id === "sharpe")
  const row = chosenRow(doc, cmp)
  const vol = typeof row?.vol === "number" ? row.vol : null
  const tiles: [string, string, string | null, string][] = []  // [이름, 값, 비교지수 값, 용어(? 도움말)]
  if (mdd) tiles.push([mdd.label_ko, fmt(mdd.value, mdd.format), mdd.benchmark_value != null ? `${mdd.benchmark_label_ko ?? "비교지수"} ${fmt(mdd.benchmark_value, mdd.format)}` : null, "최대낙폭"])
  if (vol !== null) tiles.push(["변동성 (연)", fmt(vol, "pct"), null, "변동성"])
  if (sharpe) tiles.push([sharpe.label_ko, fmt(sharpe.value, sharpe.format), sharpe.benchmark_value != null ? `${sharpe.benchmark_label_ko ?? "비교지수"} ${fmt(sharpe.benchmark_value, sharpe.format)}` : null, "Sharpe"])
  if (!tiles.length) return null
  return (
    <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {tiles.map(([l, v, bm, term]) => <div key={l} className="rounded-xl border border-slate-200 p-3"><dt className="flex items-center gap-1 text-xs font-semibold text-slate-600"><span>{l}</span><Term t={term} label={l} /></dt><dd className="mt-1 text-xl font-bold tabular-nums text-slate-950">{v}</dd>{bm && <dd className="text-xs tabular-nums text-slate-500">{bm}</dd>}</div>)}
    </dl>
  )
}

type Role = "chosen" | "baseline" | "bench" | "other"
const ROLE: Record<Role, [string, "green" | "amber" | "slate"]> = { chosen: ["최종 선택", "green"], baseline: ["기준 전략", "slate"], bench: ["시장 비교지수", "slate"], other: ["후보", "slate"] }
const COL_LABEL: Record<string, string> = { cagr: "연평균 수익률(CAGR)", mdd: "최대낙폭(MDD)", excess: "비교지수 대비 (CAGR 차이)" }
const COL_TERM: Record<string, string> = { cagr: "CAGR", vol: "변동성", sharpe: "Sharpe", mdd: "최대낙폭", irr: "XIRR" }

/** 비교표 행의 역할: 최종 선택(서버 선택 전략 이름) · 기준 전략(비중 비교표의 기준) · 비교지수(서버 종류) · 그 밖의 후보. 순위는 다시 매기지 않는다. */
function useRoles(doc: ReportDoc) {
  const wc = blocksOf(doc, "weights_compare", "construction")[0] as WeightsCompareBlock | undefined
  const baseName = wc?.columns.find((c) => c.id === wc.baseline_id)?.label_ko
  const ids = idByLabel(doc)
  const role = (r: Record<string, unknown>): Role => { const x = compareRowOf(doc, r.name); if (x) return x.role === "benchmark" ? "bench" : x.role === "candidate" ? "other" : x.role; return r.name === doc.header.chosen_label_ko ? "chosen" : r.kind === "비교지수" ? "bench" : baseName && r.name === baseName ? "baseline" : "other" }
  return { role, idOf: (name: unknown) => compareRowOf(doc, name)?.id ?? ids.get(String(name)) }
}

function StrategyName({ name, id, doc }: { name: string; id?: string; doc: ReportDoc }) {
  const info = strategyInfoOf(doc, id)
  const mock = (id && proposed(doc)?.explanations?.strategies?.[id]) || compareRowOf(doc, name)  // 설명·역할이 목업 값
  // 물음표는 이름 바로 뒤에 (2026-11-16 사용자 요청): 마지막 단어와 아이콘을 줄바꿈 없이 묶어, 이름이 두 줄 이상이어도 아이콘이 이름 끝에 붙는다.
  // 아이콘은 글자 한 줄 높이(1lh) 상자 안 가운데 — 글자와 세로 가운데가 맞는다
  const words = name.split(" ")
  const last = words.pop() ?? name
  const head = words.join(" ")
  return (
    <span className="min-w-0 font-medium text-slate-800">
      {head && `${head} `}<span className="whitespace-nowrap">{last}{info && <span className="ml-1 inline-flex h-[1lh] items-center align-top"><HelpTip label={name}>{info.short} {info.help}</HelpTip></span>}</span>{mock && <MockTag />}
    </span>
  )
}

function ColHead({ c }: { c: { key: string; label_ko: string } }) {
  return <span className="inline-flex items-center justify-end gap-0.5">{COL_LABEL[c.key] ?? c.label_ko}{COL_TERM[c.key] && <Term t={COL_TERM[c.key]} label={COL_LABEL[c.key] ?? c.label_ko} />}</span>
}

/** 서버 비교표에서 선택 전략·기준 전략·비교지수 행만 골라 같은 열로 보여 준다 (값은 표 그대로). 아래에 선택 전략과의 차이(표 값의 뺄셈)를 적는다. */
function CompareMini({ doc, t }: { doc: ReportDoc; t: TableBlock }) {
  const { role, idOf } = useRoles(doc)
  const order: Role[] = ["chosen", "baseline", "bench"]
  const picked = order.flatMap((x) => t.rows.filter((r) => role(r) === x).map((r) => ({ r, x })))
  if (!picked.length) return null
  const cols = t.columns.filter((c) => ["cagr", "mdd", "sharpe", "final"].includes(c.key))
  const chosen = picked.find((p) => p.x === "chosen")?.r
  const diff = (r: Record<string, unknown>, k: string) => (typeof chosen?.[k] === "number" && typeof r[k] === "number" ? (chosen[k] as number) - (r[k] as number) : null)
  const vs = chosen ? picked.filter((p) => p.x !== "chosen" && (p.x === "baseline" || p.r.name === picked.find((q) => q.x === "bench")?.r.name)) : []
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-xl border border-slate-200">
        <table className="w-full min-w-[600px] text-sm">
          <thead><tr className="border-b border-slate-200 bg-slate-50 text-left text-xs font-semibold text-slate-600"><th className="px-3 py-2">포트폴리오</th>{cols.map((c) => <th key={c.key} className="whitespace-nowrap px-3 py-2 text-right"><ColHead c={c} /></th>)}</tr></thead>
          <tbody>{picked.map(({ r, x }, i) => <tr key={i} className={`border-b border-slate-100 ${x === "chosen" ? "bg-blue-50/60" : ""}`}><td className="px-3 py-2"><span className="flex flex-wrap items-center gap-2"><StatusPill tone={ROLE[x][1]}>{ROLE[x][0]}</StatusPill><StrategyName name={String(r.name)} id={idOf(r.name)} doc={doc} /></span></td>{cols.map((c) => <td key={c.key} className={`whitespace-nowrap px-3 py-2 text-right tabular-nums ${x === "chosen" ? "font-semibold text-slate-950" : "text-slate-700"}`}>{fmt(r[c.key], c.format)}</td>)}</tr>)}</tbody>
        </table>
      </div>
      {vs.length > 0 && (
        <ul className="space-y-0.5 text-xs leading-5 text-slate-600" aria-label="선택 전략과의 차이">
          {vs.map(({ r, x }) => { const dc = diff(r, "cagr"), dm = diff(r, "mdd"); return <li key={String(r.name)}><b className="font-semibold text-slate-800">선택 전략 − {x === "baseline" ? "기준 전략" : String(r.name)}</b>: 연평균 수익률(CAGR) {dc === null ? "–" : fmt(dc, "pp")} · 최대낙폭 {dm === null ? "–" : fmt(dm, "pp")}{dm !== null && dm < 0 ? " (더 크게 하락)" : dm !== null && dm > 0 ? " (덜 하락)" : ""}</li> })}
        </ul>
      )}
      {isShortWindow(doc) && <p className="text-xs leading-5 text-slate-500">{shortWindowNote(doc)}</p>}
    </div>
  )
}

const PAGE_ROWS = 25

/** 전체 전략 비교표: 서버 표의 모든 열·값 그대로 + 역할 표시·전략 설명. 최종 선택은 서버 판정을 따르며, 수익률이 가장 높은 전략과 다를 수 있다. */
function StrategyTable({ doc, t }: { doc: ReportDoc; t: TableBlock }) {
  const { role, idOf } = useRoles(doc)
  const [page, setPage] = useState(0)
  const pages = Math.max(1, Math.ceil(t.rows.length / PAGE_ROWS))
  const rows = t.rows.slice(page * PAGE_ROWS, (page + 1) * PAGE_ROWS)
  const cols = t.columns.filter((c) => c.key !== "name")
  return (
    <div className="space-y-3">
      {t.title_ko && <h3 className="text-base font-semibold text-slate-900">{t.title_ko}</h3>}
      <div className="overflow-x-auto rounded-xl border border-slate-200">
        <table className="w-full min-w-[960px] text-sm">
          <thead><tr className="border-b border-slate-200 bg-slate-50 text-left text-xs font-semibold text-slate-600"><th className="px-3 py-2">역할</th><th className="min-w-[14rem] px-3 py-2">{t.columns.find((c) => c.key === "name")?.label_ko ?? "포트폴리오"}</th>{cols.map((c) => <th key={c.key} className={`whitespace-nowrap px-3 py-2 ${c.format && c.format !== "text" ? "text-right" : ""}`}><ColHead c={c} /></th>)}</tr></thead>
          <tbody>
            {rows.map((r, i) => {
              const x = role(r)
              return (
                <tr key={i} className={`border-b border-slate-100 align-top ${x === "chosen" ? "bg-blue-50/60" : x === "bench" ? "bg-slate-50/60" : ""}`}>
                  <td className="whitespace-nowrap px-3 py-2"><StatusPill tone={ROLE[x][1]}>{ROLE[x][0]}</StatusPill></td>
                  <td className="px-3 py-2"><StrategyName name={String(r.name)} id={idOf(r.name)} doc={doc} /></td>
                  {cols.map((c) => { const v = r[c.key]; const num = c.format && c.format !== "text"; return <td key={c.key} className={`px-3 py-2 ${num ? `whitespace-nowrap text-right tabular-nums ${x === "chosen" ? "font-semibold text-slate-950" : "text-slate-700"}` : `text-slate-700 ${c.key === "kind" || c.key === "status" ? "whitespace-nowrap" : ""}`}`}>{num ? fmt(v, c.format) : String(v ?? "–")}</td> })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <Pagination page={page} pages={pages} onChange={setPage} total={t.rows.length} pageSize={PAGE_ROWS} />
      {t.note_ko && <p className="text-xs leading-5 text-slate-500">{t.note_ko}</p>}
    </div>
  )
}

/* ───────── 5-7 투자 전에 무엇을 주의해야 하나요? ───────── */

function Cautions({ doc, s }: { doc: ReportDoc; s: Section }) {
  const sm = doc.summary
  if (!sm) return null
  const alerts = keyAlerts(sm)
  const notRecommended = sm.verdict.status !== "recommended" && sm.verdict.status !== "recommended_warn"
  const cardTexts = new Set(s.blocks.flatMap((b) => (b.type === "cards" ? b.items.map((c) => c.text_ko) : [])))
  const next = sm.next_actions_ko.filter((t) => !cardTexts.has(t))  // 아래 「다음 분석에서 바꿔 볼 조건」(서버 이름 「다음에 검토할 수 있는 선택지」)과 같은 문장은 한 번만
  const info = sm.validation.info_plain_ko ?? sm.validation.info_notes_ko ?? []  // 쉬운 문장(2026-11-16)이 있으면 그 문장
  return (
    <SubPart title="중요한 주의 사항">
      {notRecommended && <AlertList items={[{ tone: "slate", tag: "추천 결과", text: sm.verdict.label_plain_ko ?? sm.verdict.label_ko }]} label="추천 결과" />}
      {alerts.length ? <AlertList items={alerts} /> : <p className="text-sm text-slate-600">미충족·주의 항목이 없습니다.</p>}
      {/* 「분석 중 확인한 점」 상자는 두지 않는다: 같은 문장이 아래 「분석 중 확인한 점」 표에 더 자세히(전체 건수·날짜) 있다 (2026-11-14 사용자 요청) */}
      {info.length > 0 && <div className="rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-3.5"><StatusPill tone="slate" icon={Info}>참고</StatusPill><ul className="mt-2.5 list-disc space-y-3 pl-5 text-sm leading-6 text-slate-700">{info.map((t, i) => <li key={i}><CitedText text={t} /></li>)}</ul></div>}
      {next.length > 0 && <div><p className="text-xs font-semibold text-slate-600">다음 검토 사항</p><ul className="mt-1 space-y-1 text-sm leading-6 text-slate-700">{next.map((t, i) => <li key={i} className="flex gap-2"><span className="text-slate-400">{i + 1}.</span><span><CitedText text={t} /></span></li>)}</ul></div>}
    </SubPart>
  )
}

/* ───────── 5-8 어떤 자료를 근거로 분석했나요? ───────── */

const KIND_HELP: Record<string, string> = { news: "금융 뉴스 헤드라인", disclosure: "기업 공시 목록", financial: "재무·가격 데이터", calc: "계산·분석 결과값" }

function ReferencesTop({ doc, s }: { doc: ReportDoc; s: Section }) {
  const rep = useReport()
  const byKind = doc.evidence_summary?.by_kind ?? {}
  const total = doc.evidence_summary?.total ?? doc.evidence.length
  const calc = s.blocks.find((b) => b.type === "table" && b.title_ko === "계산 조건") as TableBlock | undefined
  const fx = calc?.rows.find((r) => r.k === "환율(기준일)")?.v
  const h = doc.header
  return (
    <>
      <SubPart title="분석에 사용한 자료" desc={`근거 자료 ${total}건${doc.evidence_summary ? ` · 본문 인용 ${doc.evidence_summary.cited}건` : ""}`}>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          {Object.entries(byKind).filter(([, n]) => n > 0).map(([k, n]) => (
            <button key={k} type="button" disabled={!rep} onClick={() => rep?.openDrawer({ ids: null, kind: k, title: `${ko(k)} 자료` })} className="rounded-xl border border-slate-200 bg-white p-3 text-left hover:border-blue-300 hover:bg-blue-50/40 focus:outline-none focus:ring-2 focus:ring-blue-500">
              <span className="block text-xs font-semibold text-slate-500">{ko(k)}</span><span className="mt-0.5 block text-xl font-bold tabular-nums text-slate-950">{n}건</span><span className="block text-[11px] text-slate-500">{KIND_HELP[k] ?? ""}</span>
            </button>
          ))}
        </div>
        {rep && <Button variant="secondary" onClick={() => rep.openDrawer({ ids: null, title: "출처 전체" })}><BookOpenText className="size-4" />전체 자료 검색 ({total})</Button>}
      </SubPart>
      <SubPart title="계산 조건과 실행 기록">
        <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
          <div><dt className="text-xs font-semibold text-slate-500">분석한 날</dt><dd className="mt-0.5 tabular-nums text-slate-900">{h.data_as_of}</dd></div>
          <div><dt className="text-xs font-semibold text-slate-500">종목 선정 기준일</dt><dd className="mt-0.5 tabular-nums text-slate-900">{h.selection_as_of}</dd></div>
          <div><dt className="text-xs font-semibold text-slate-500">백테스트 기간</dt><dd className="mt-0.5 tabular-nums text-slate-900">{h.backtest_period.start} ~ {h.backtest_period.end}</dd></div>
          {typeof fx === "string" && <div className="min-w-0"><dt className="text-xs font-semibold text-slate-500">환율 (분석한 날)</dt><dd className="mt-0.5 break-words text-slate-900">{fx}</dd></div>}
        </dl>
        {rep?.openPanel && <div className="flex flex-wrap gap-2"><Button variant="secondary" onClick={() => rep.openPanel!("calc")}><Sigma className="size-4" />계산 조건 전체</Button><Button variant="secondary" onClick={() => rep.openPanel!("exec")}><ListChecks className="size-4" />실행 기록</Button></div>}
      </SubPart>
    </>
  )
}
