import { useState } from "react"
import { BookOpenText, ListChecks, Sigma } from "lucide-react"
import type { Block, CompaniesBlock, EvidenceRefBlock, ReportDoc, Section, TableBlock, WeightsCompareBlock } from "../../api/types"
import { fmt, ko } from "../../lib/format"
import { groupBlocks } from "../../lib/reportNormalize"
import { Button, Disclosure, Pagination } from "../../ui"
import { AlertList, allKpis, ConditionRules, keyAlerts, KpiRow, MoreLink, NewsEffect, StatusPill } from "./Dashboard"
import { CitedText, Paragraphs, RenderBlock } from "./blocks/blocks"
import { useReport } from "./context"
import { DEFAULT_VOL_PREF, RISK_TOLERANCE_RANGE, VOL_PREF_LABEL } from "../../lib/tendency"
import { HelpTip, Term } from "./terms"
import { compareRowOf, MockTag, proposed, reasonsOf, strategyInfoOf } from "./proposedView"
import { analysisRisk, benchName, idByLabel, isShortWindow, shortWindowNote } from "./wording"

// 「자세한 분석 보기」의 섹션 본문. 섹션마다 위에 핵심 요약(서버 summary·블록에서 고른 값)을 두고, 서버 블록은 순서대로 그리되
// 긴 문단·큰 비교표는 접어서 둔다. 어떤 블록도 버리지 않는다 — 분류하지 못한 블록은 원래 순서대로 끝에 그린다.

const PROSE: Record<string, string> = {
  verdict: "판단 근거 전문", construction: "비중 결정 설명", companies: "선정 과정 설명", market: "시장 분석 원문",
  performance: "성과 해석", assumptions: "분석의 전제", references: "자세한 설명",
}

/** 한 섹션에 문단 묶음이 둘 이상이면 내용(서버 src: 14a 해석 · 14b 서술 · 14c 시장 분석)에 맞는 다른 이름을 쓴다. 같은 이름이 반복되지 않게. */
const PROSE_BY_SRC: Record<string, Record<string, string>> = {
  market: { "14b": "아이디어 해석", "14c": "시장·뉴스 분석 원문" },
  construction: { "14b": "비중 결정 설명", "14a": "뉴스 반영 해석" },
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

/** 섹션 안 소제목 묶음. */
export function SubPart({ id, title, desc, children }: { id?: string; title: string; desc?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div id={id} className="scroll-mt-16 space-y-3 border-t border-slate-200 pt-5 first:border-t-0 first:pt-0">
      <div><h3 className="text-base font-bold text-slate-950">{title}</h3>{desc && <p className="mt-0.5 text-xs leading-5 text-slate-500">{desc}</p>}</div>
      {children}
    </div>
  )
}

function ProseFold({ label, blocks }: { label: string; blocks: Block[] }) {
  return (
    <Disclosure size="sm" title={label} summary={`${paraCount(blocks)}문단`}>
      <div className="space-y-4">{blocks.map((b, i) => b.type === "paragraphs" ? <Paragraphs key={i} items={b.items} tone={b.tone} /> : null)}</div>
    </Disclosure>
  )
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
        if (e.kind === "prose") return <ProseFold key={i} label={nth(i)} blocks={e.blocks} />
        const b = e.b
        if (b.type === "weights_compare") return <Disclosure key={i} title="전략별 비중 비교표" summary={`${b.columns.length}개 전략 · ${b.rows.length}종목`}><RenderBlock b={b} doc={doc} /></Disclosure>
        if (b.type === "cards" && (b.items.length >= 3 || textLen(b) > 600)) return <Disclosure key={i} title={b.title_ko ?? "자세히 보기"} summary={`${b.items.length}개`}><RenderBlock b={b} doc={doc} /></Disclosure>
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
    case "verdict": return <><VerdictWhy doc={doc} /><Blocks blocks={hasPerf ? s.blocks.filter((b) => b.type !== "kpis") : s.blocks} doc={doc} sec={s.id} /></>  // KPI 전체는 「과거 투자 성과」 맨 위에
    case "construction": return <><BuildFlow doc={doc} /><ChosenWeights doc={doc} /><SubPart title="비중과 운용 기록"><Blocks blocks={s.blocks} doc={doc} sec={s.id} /></SubPart></>
    case "market": return <><MarketTopics s={s} doc={doc} /><SubPart title="시장 분석 상세"><Blocks blocks={s.blocks.map((b) => riskRowsKo(b, doc))} doc={doc} sec={s.id} /></SubPart></>
    case "companies": return <Blocks blocks={s.blocks.map((b) => rejectKo(b, doc))} doc={doc} sec={s.id} />
    case "performance": return <PerformanceBody s={s} doc={doc} />
    case "assumptions": return <><Cautions doc={doc} s={s} /><SubPart title="전제와 재검토 조건"><Blocks blocks={s.blocks} doc={doc} sec={s.id} /></SubPart></>
    case "references": return <><ReferencesTop doc={doc} s={s} /><SubPart title="자료 출처·용어·근거 색인"><Blocks blocks={s.blocks} doc={doc} sec={s.id} /></SubPart></>
    default: return <Blocks blocks={s.blocks} doc={doc} sec={s.id} />
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
const REJECT_KO: Record<string, string> = { metric_missing: "선정 지표를 계산할 자료 없음", rank_beyond_n: "선정 지표 순위가 선정 개수 밖", weight_capacity: "비중 한도 안에 담을 수 없음" }
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

/* ───────── 5-1 왜 이런 투자 전략이 선택되었나요? ───────── */

function VerdictWhy({ doc }: { doc: ReportDoc }) {
  const rep = useReport()
  const sm = doc.summary
  if (!sm) return null
  const o = { short: isShortWindow(doc), shortNote: shortWindowNote(doc) }
  const reasons = reasonsOf(doc, o.short)  // 구조화된 판단 이유(제안 계약)가 있으면 그것, 없으면 서버가 " · " 로 이어 붙인 문장을 틀대로 읽는다
  const alerts = keyAlerts(sm)
  return (
    <>
      <SubPart title="핵심 판단 이유" desc={<>결과: {sm.verdict.label_ko}{proposed(doc)?.structured?.reasons?.length ? <MockTag /> : null}</>}>
        {reasons.length ? (
          <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200" aria-label="핵심 판단 이유">
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
      <SubPart title="위험과 미충족 조건">
        {alerts.length ? <AlertList items={alerts} /> : <p className="text-sm text-slate-600">미충족·주의 항목이 없습니다.</p>}
        {rep && <MoreLink label="주의 사항 전체 보기" onClick={() => rep.jump("assumptions")} />}
      </SubPart>
    </>
  )
}

/* ───────── 5-2 투자 종목과 비중은 어떻게 결정됐나요? ───────── */

function BuildFlow({ doc }: { doc: ReportDoc }) {
  const comp = blocksOf(doc, "companies")[0] as CompaniesBlock | undefined
  const wc = blocksOf(doc, "weights_compare", "construction")[0] as WeightsCompareBlock | undefined
  const ne = doc.summary?.news_effect
  const base = wc?.columns.find((c) => c.id === wc.baseline_id)
  const nBl = wc?.columns.filter((c) => c.kind === "black_litterman").length ?? 0
  const steps: { t: string; d: string; off?: boolean }[] = []
  if (comp) steps.push({ t: "투자 종목 선정", d: `분석 기준일 ${comp.items.filter((x) => x.in_selection_now).length}개 · 백테스트 시작일 ${comp.items.filter((x) => x.in_backtest).length}개 · ${comp.metric_ko} 순위` })
  if (base) steps.push({ t: "기준 투자 비중 계산", d: `${base.label_ko}${base.rule_ko ? ` · ${base.rule_ko}` : ""}` })
  if (nBl > 0 || (ne && !ne.disabled)) steps.push({ t: "뉴스·공시 반영", d: nBl ? `뉴스·공시 시나리오 ${nBl}개로 기준 비중 조정` : "뉴스·공시로 기준 비중 조정" })
  else if (ne?.disabled) steps.push({ t: "뉴스·공시 반영 안 함", d: ne.reason_ko ?? "이 분석에서는 뉴스를 반영하지 않았습니다", off: true })
  steps.push({ t: "최종 비중 결정", d: `선택: ${doc.header.chosen_label_ko}` })
  return (
    <SubPart title="비중이 정해진 과정">
      <ol className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-4" aria-label="비중 결정 과정">
        {steps.map((x, i) => (
          <li key={x.t} className={`relative rounded-xl border p-3 ${x.off ? "border-dashed border-slate-300 bg-white text-slate-500" : "border-slate-200 bg-slate-50"}`}>
            <p className="flex items-center gap-2 text-sm font-semibold text-slate-900"><span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-slate-800 text-[11px] font-bold text-white">{i + 1}</span>{x.t}</p>
            <p className="mt-1 break-words text-xs leading-5 text-slate-600">{x.d}</p>
          </li>
        ))}
      </ol>
    </SubPart>
  )
}

/** 기준 비중 vs 선택 전략 비중 (같은 표·같은 시점: 서버 비교표의 백테스트 시작일 값). 선택 전략이 표에 없으면 그리지 않고 어디서 보는지 안내한다. */
function ChosenWeights({ doc }: { doc: ReportDoc }) {
  const wc0 = blocksOf(doc, "weights_compare", "construction")[0] as WeightsCompareBlock | undefined
  const cvb = proposed(doc)?.chosen_vs_baseline
  const chosen = doc.header.chosen_portfolio_id
  // 선택 전략이 서버 비교표에 없을 때(낙폭 맞춤안 등) 제안 계약의 「선택 vs 기준」 값이 있으면 같은 모양의 표로 바꿔 그린다
  const wc: WeightsCompareBlock | undefined = wc0 && wc0.columns.some((c) => c.id === chosen) ? wc0 : cvb ? { type: "weights_compare", title_ko: "", baseline_id: cvb.baseline_id, columns: [{ id: cvb.chosen_id, label_ko: cvb.chosen_label_ko, kind: "", rule_ko: "" }, ...(cvb.baseline_id !== cvb.chosen_id ? [{ id: cvb.baseline_id, label_ko: cvb.baseline_label_ko, kind: "", rule_ko: "" }] : [])], rows: cvb.rows.map((r) => ({ ticker: r.ticker, name: r.name, sector: "", weights: { [cvb.chosen_id]: r.chosen, [cvb.baseline_id]: r.baseline } })), cash: { [cvb.chosen_id]: cvb.cash.chosen, [cvb.baseline_id]: cvb.cash.baseline }, ex_ante: {} } : wc0
  if (!wc) return null
  const col = wc.columns.find((c) => c.id === chosen)
  const base = wc.columns.find((c) => c.id === wc.baseline_id)
  if (!col || !base) return <SubPart title="선택 전략의 비중"><p className="text-sm text-slate-600">선택 전략의 비중은 개요의 종목별 투자 금액과 리밸런싱 기록에 있습니다.</p></SubPart>
  const same = col.id === base.id
  const rows = [...wc.rows].sort((a, b) => (b.weights[col.id] ?? 0) - (a.weights[col.id] ?? 0))
  const max = Math.max(0.01, ...wc.rows.flatMap((r) => [r.weights[col.id] ?? 0, r.weights[base.id] ?? 0]), wc.cash[col.id] ?? 0, wc.cash[base.id] ?? 0)
  const bar = (v: number | undefined, cls: string) => <span className="h-2 overflow-hidden rounded-full bg-slate-100"><span className={`block h-full rounded-full ${cls}`} style={{ width: `${((v ?? 0) / max) * 100}%` }} /></span>
  const line = (key: string, label: React.ReactNode, a: number | undefined, b: number | undefined) => {
    const d = (a ?? 0) - (b ?? 0)
    return (
      <li key={key} className="grid grid-cols-[minmax(0,7rem)_minmax(0,1fr)_auto] items-center gap-x-3 py-1.5 sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)_auto]">
        <span className="min-w-0 truncate text-sm font-medium text-slate-800">{label}</span>
        <span className="grid gap-1">{!same && <span className="grid grid-cols-[1fr_3.5rem] items-center gap-2">{bar(b, "bg-slate-400")}<span className="text-right text-[11px] tabular-nums text-slate-500">{fmt(b, "pct1")}</span></span>}<span className="grid grid-cols-[1fr_3.5rem] items-center gap-2">{bar(a, "bg-blue-600")}<span className="text-right text-xs font-semibold tabular-nums text-slate-900">{fmt(a, "pct1")}</span></span></span>
        {!same && <span className={`w-16 text-right text-xs tabular-nums ${Math.abs(d) >= 0.005 ? "font-semibold text-slate-900" : "text-slate-400"}`}>{Math.abs(d) < 0.0005 ? "변화 없음" : fmt(d, "pp")}</span>}
      </li>
    )
  }
  return (
    <SubPart title={same ? "선택 전략의 종목별 비중" : "기준 비중과 선택 전략 비중"} desc={<>백테스트 시작일 구성 · {same ? `선택 전략 = 기준 비중(${base.label_ko})` : `기준: ${base.label_ko} / 선택: ${col.label_ko}`}{wc !== wc0 && <MockTag />}</>}>
      {!same && <p className="flex flex-wrap gap-4 text-[11px] text-slate-500"><span><i className="mr-1 inline-block h-2 w-4 rounded-full bg-slate-400 align-middle" />기준 비중</span><span><i className="mr-1 inline-block h-2 w-4 rounded-full bg-blue-600 align-middle" />선택 전략 비중</span><span>오른쪽 숫자 = 선택 − 기준</span></p>}
      <ul aria-label="종목별 비중 비교" className="divide-y divide-slate-100">
        {rows.map((r) => line(r.ticker, <span title={r.name}>{r.ticker}<span className="ml-1 hidden text-xs font-normal text-slate-500 sm:inline">{r.name !== r.ticker ? r.name : ""}</span></span>, r.weights[col.id], r.weights[base.id]))}
        {((wc.cash[col.id] ?? 0) >= 0.0005 || (wc.cash[base.id] ?? 0) >= 0.0005) && line("cash", "현금", wc.cash[col.id], wc.cash[base.id])}
      </ul>
    </SubPart>
  )
}

/* ───────── 5-4 시장과 뉴스는 어떻게 분석했나요? ───────── */

function MarketTopics({ s, doc }: { s: Section; doc: ReportDoc }) {
  const rep = useReport()
  const themes = s.blocks.find((b) => b.type === "table" && b.title_ko === "추출한 테마") as TableBlock | undefined
  const ref = s.blocks.find((b) => b.type === "evidence_ref") as EvidenceRefBlock | undefined
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
                <h4 className="mt-0.5 text-sm font-bold text-slate-900">{t.title_ko}</h4>
                <p className="mt-1.5 text-sm leading-6 text-slate-700">{t.summary_ko}</p>
                {t.points_ko.length > 0 && <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-xs leading-5 text-slate-600">{t.points_ko.map((x, i) => <li key={i}>{x}</li>)}</ul>}
                {rep && t.evidence_ids.length > 0 && <button type="button" onClick={() => rep.openDrawer({ ids: t.evidence_ids, title: t.title_ko })} className="mt-auto self-start pt-2 text-xs font-semibold text-blue-700 hover:underline">근거 {t.evidence_ids.length}건 보기</button>}
              </div>
            ))}
          </div>
        </SubPart>
      )}
      {(themes || ref) && (
        <SubPart title="분석 범위">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {themes && (
              <div className="rounded-xl border border-slate-200 p-4">
                <h4 className="text-sm font-bold text-slate-900">투자 테마 {themes.rows.length}개</h4>
                <ul className="mt-2 space-y-2">{themes.rows.map((r, i) => <li key={i} className="text-sm leading-6"><b className="font-semibold text-slate-900">{String(r.label ?? "")}</b>{r.desc ? <span className="block text-xs leading-5 text-slate-600">{String(r.desc)}</span> : null}</li>)}</ul>
              </div>
            )}
            {ref && (
              <div className="rounded-xl border border-slate-200 p-4">
                <h4 className="text-sm font-bold text-slate-900">시장 분석에 인용한 뉴스·공시</h4>
                <p className="mt-1 text-2xl font-bold tabular-nums text-slate-950">{ref.count}건</p>
                <p className="text-xs text-slate-500">{Object.entries(ref.kinds).map(([k, n]) => `${ko(k)} ${n}건`).join(" · ")}</p>
                {rep && <Button variant="secondary" className="mt-3" onClick={() => rep.openDrawer({ ids: ref.ids, title: ref.title_ko })}><BookOpenText className="size-4" />자료 목록 보기</Button>}
              </div>
            )}
          </div>
        </SubPart>
      )}
      {ne && <SubPart title="뉴스 반영 효과"><NewsEffect n={ne} /></SubPart>}
    </>
  )
}

/* ───────── 5-5 과거 투자 성과는 어땠나요? ───────── */

const isCompareTable = (b: Block): b is TableBlock => b.type === "table" && b.columns.some((c) => c.key === "sharpe") && b.columns.some((c) => c.key === "mdd")

function PerformanceBody({ s, doc }: { s: Section; doc: ReportDoc }) {
  const A: Entry[] = [], B: Entry[] = [], C: Entry[] = [], V: Entry[] = [], top: Entry[] = [], prose: Entry[] = [], other: Entry[] = []
  for (const e of entries(s.blocks)) {
    if (e.kind === "group") {
      const hasRule = e.blocks.some((b) => b.type === "table" && b.columns.some((c) => c.key === "rule"))
      if (hasRule || e.title.includes("검증")) V.push(e); else if (/연도|월별/.test(e.title)) A.push(e); else other.push(e)
    } else if (e.kind === "prose") prose.push(e)
    else {
      const b = e.b
      if (b.type === "kpis") continue  // KPI 전체는 아래 「성과 지표 전체」
      if (b.type === "callout") top.push(e)
      else if (b.type === "line") A.push(e)
      else if (b.type === "area") B.push(e)
      else if (isCompareTable(b) || b.type === "bar") C.push(e)
      else other.push(e)
    }
  }
  const draw = (es: Entry[]) => es.map((e, i) => e.kind === "group" ? <Disclosure key={i} title={e.title} summary={`${e.blocks.length}개 항목`} defaultOpen={e.open}><div className="space-y-5">{e.blocks.map((b, j) => <RenderBlock key={j} b={b} doc={doc} />)}</div></Disclosure>
    : e.kind === "prose" ? <ProseFold key={i} label={PROSE.performance} blocks={e.blocks} />
    : isCompareTable(e.b) ? <Disclosure key={i} title="전체 전략 비교표" summary={`${e.b.rows.length}개`}><StrategyTable doc={doc} t={e.b} /></Disclosure>
    : <RenderBlock key={i} b={e.b} doc={doc} />)
  const cmp = C.map((e) => (e.kind === "block" && isCompareTable(e.b) ? e.b : null)).find(Boolean) ?? null
  const sm = doc.summary
  return (
    <>
      <SubPart title="성과 지표 전체">{isShortWindow(doc) && <p className="text-xs leading-5 text-slate-600">{shortWindowNote(doc)} 전체 기간 수익률은 연평균이 아닌 기간 전체의 수익률입니다.</p>}<KpiRow kpis={allKpis(doc)} doc={doc} /></SubPart>
      {top.length > 0 && <div className="space-y-3">{draw(top)}</div>}
      {A.length > 0 && <SubPart title="수익률 추이">{draw(A)}</SubPart>}
      <SubPart title="하락과 변동성"><RiskFacts doc={doc} cmp={cmp} />{draw(B)}</SubPart>
      {(C.length > 0 || cmp) && <SubPart title="전략 비교">{cmp && <CompareMini doc={doc} t={cmp} />}{draw(C)}</SubPart>}
      <SubPart id="perf-validation" title="조건별 검증">{sm && <ConditionRules v={sm.validation} verdict={sm.verdict} bench={benchName(sm)} doc={doc} />}{draw(V)}</SubPart>
      {prose.length > 0 && draw(prose)}
      {other.length > 0 && <SubPart title="그 밖의 성과 분석">{draw(other)}</SubPart>}
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
  return <span className="inline-flex min-w-0 items-start gap-1"><span className="min-w-0 font-medium text-slate-800">{name}</span>{info && <HelpTip label={name}>{info.short} {info.help}</HelpTip>}{mock && <MockTag />}</span>
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
  const next = sm.next_actions_ko.filter((t) => !cardTexts.has(t))  // 아래 「다음에 검토할 수 있는 선택지」와 같은 문장은 한 번만
  const info = sm.validation.info_notes_ko ?? []
  return (
    <SubPart title="중요한 주의 사항">
      {notRecommended && <AlertList items={[{ tone: "slate", tag: "추천 결과", text: sm.verdict.label_ko }]} label="추천 결과" />}
      {alerts.length ? <AlertList items={alerts} /> : <p className="text-sm text-slate-600">미충족·주의 항목이 없습니다.</p>}
      {(sm.verdict.notices_ko?.length ?? 0) > 0 && <div className="rounded-xl border border-slate-200 p-3"><p className="text-xs font-semibold text-slate-600">분석 중 확인한 점 {sm.verdict.n_notices ?? sm.verdict.notices_ko!.length}건</p><ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm leading-6 text-slate-700">{sm.verdict.notices_ko!.map((n, i) => <li key={i}>{n}</li>)}</ul></div>}
      {info.length > 0 && <div className="rounded-xl bg-slate-50 p-3"><p className="text-xs font-semibold text-slate-600">참고</p><ul className="mt-1 list-disc pl-5 text-sm leading-6 text-slate-700">{info.map((t, i) => <li key={i}>{t}</li>)}</ul></div>}
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
      <SubPart title="자료 종류별" desc={`근거 자료 ${total}건${doc.evidence_summary ? ` · 본문 인용 ${doc.evidence_summary.cited}건` : ""}`}>
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
          <div><dt className="text-xs font-semibold text-slate-500">분석 기준일</dt><dd className="mt-0.5 tabular-nums text-slate-900">{h.data_as_of}</dd></div>
          <div><dt className="text-xs font-semibold text-slate-500">종목 선정 기준일</dt><dd className="mt-0.5 tabular-nums text-slate-900">{h.selection_as_of}</dd></div>
          <div><dt className="text-xs font-semibold text-slate-500">백테스트 기간</dt><dd className="mt-0.5 tabular-nums text-slate-900">{h.backtest_period.start} ~ {h.backtest_period.end}</dd></div>
          {typeof fx === "string" && <div className="min-w-0"><dt className="text-xs font-semibold text-slate-500">환율 (분석 기준일)</dt><dd className="mt-0.5 break-words text-slate-900">{fx}</dd></div>}
        </dl>
        {rep?.openPanel && <div className="flex flex-wrap gap-2"><Button variant="secondary" onClick={() => rep.openPanel!("calc")}><Sigma className="size-4" />계산 조건 전체</Button><Button variant="secondary" onClick={() => rep.openPanel!("exec")}><ListChecks className="size-4" />실행 기록</Button></div>}
      </SubPart>
    </>
  )
}
