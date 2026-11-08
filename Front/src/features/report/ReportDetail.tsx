import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Activity, ArrowLeft, BookOpenText, GitCompareArrows, ListChecks, Pencil, PencilLine, RefreshCw, Sigma, Trash2 } from "lucide-react"
import { useService } from "../../app/providers"
import { navigate as routerNavigate } from "../../app/router"
import { errorMessage } from "../../api/client"
import type { EvidenceRecord, ReportDoc } from "../../api/types"
import { useResource } from "../../state/useResource"
import { Alert, Badge, Button, EmptyState, Loading, Menu } from "../../ui"
import { citationNumbers } from "../../lib/citations"
import { hideCodeIds, normalizeDoc } from "../../lib/reportNormalize"
import { markReportSeen } from "../../lib/seen"
import { CitationContext } from "./blocks/blocks"
import { StartPaperDialog } from "../paper/StartPaperDialog"
import { RevisionPanel } from "./RevisionPanel"
import { Dashboard } from "./Dashboard"
import { RequestHistory } from "./RequestHistory"
import { HISTORY_TITLE, ReportTabs, sectionTitle } from "./SectionNav"
import { SectionShell } from "./SectionShell"
import { SectionBody } from "./sections"
import { SourceDrawer } from "./SourceDrawer"
import { SourcePanel } from "./SourcePanel"
import { CalculationPanel, ExecutionPanel } from "./panels"
import { type DrawerFilter, ReportContext, type ReportCtx } from "./context"
import { useFluidShell } from "./useFluidShell"
import { proposedNameOf, proposedOf } from "../../api/proposed"
import { GlossaryPanel, HelpTip } from "./terms"
import { DeleteReportDialog, RenameReportDialog, useRenameTick } from "./ReportName"
import { findReportRow, reportName } from "../../lib/reportName"
import { groupOf, groupsFor, SECTION_SEQUENCE } from "./navGroups"
import { plainSummary } from "./summaryText"

// 읽는 순서는 상단 탭 묶음(navGroups) 순서: 종목 선정(판단 → 포트폴리오 → 종목 근거) → 과거 성과 → 시장·뉴스 → 요청·주의·자료.
// 서버가 주는 내용은 그대로이고 순서만 바꾼다 (모르는 섹션은 뒤로).
const SECTION_ORDER = SECTION_SEQUENCE.filter((s) => s !== "history")
const rank = (id: string) => { const i = SECTION_ORDER.indexOf(id); return i < 0 ? SECTION_ORDER.length : i }
function reorder(doc: ReportDoc): ReportDoc {
  const by = <T extends { id: string }>(xs: T[]) => xs.map((x, i) => [x, i] as const).sort((a, b) => rank(a[0].id) - rank(b[0].id) || a[1] - b[1]).map(([x]) => x)
  return { ...doc, sections: by(doc.sections), nav: by(doc.nav) }
}

/** readOnly: 튜토리얼처럼 둘러보기만 하는 화면. 모의투자 시작·조건 수정·다시 분석·이름 바꾸기·삭제를 막고, 주소(해시)도 바꾸지 않는다. */
type MenuItem = { label: string; onClick: () => void; disabled?: boolean; icon?: React.ElementType; danger?: boolean }
/** extraMenu: 더보기 메뉴 끝에 붙일 항목 (예시 리포트의 「리포트 삭제」 = 목록에서 숨기기) */
type Props = { reportId: string; sec?: string; company?: string; rb?: number; readOnly?: boolean; extraMenu?: MenuItem[]; title?: string }

const TAB_OFFSET = 110  // 상단 고정 탭(49px) 아래 이 선을 지난 마지막 섹션을 「지금 보는 섹션」으로 친다 (섹션은 scroll-mt-16 = 64px 에 멈춘다)
const STOP = 64  // scroll-mt-16

/** 리포트 화면: 상단 고정 탭 + 「투자 결과 요약」 4개 카드 + 「자세한 분석 보기」 접이식 섹션들 (모두 접힌 채 시작), 근거는 드로어·패널로. 주소 ?sec=&company=&rb= 를 읽고 쓴다.
 *  App 이 리포트가 바뀌어도 같은 컴포넌트를 다시 쓰므로, 리포트마다 새로 만들어 앞 리포트의 펼침·선택이 남지 않게 한다. */
export function ReportDetail(props: Props) {
  return <ReportView key={props.reportId} {...props} />
}

function ReportView({ reportId, sec, company, rb, readOnly = false, extraMenu = [], title }: Props) {
  const svc = useService()
  const navigate: typeof routerNavigate = readOnly ? () => {} : routerNavigate
  const res = useResource(() => svc.getReport(reportId), [svc, reportId])
  useFluidShell()
  useEffect(() => {  // 리포트 화면에서만 앱 틀의 본문 최대 폭을 넓힌다 (index.css 의 html.report-wide). 모의투자 화면은 그대로
    document.documentElement.classList.add("report-wide")
    return () => document.documentElement.classList.remove("report-wide")
  }, [])
  const doc = useMemo(() => (res.data ? reorder(plainSummary(hideCodeIds(normalizeDoc(res.data)))) : null), [res.data])  // 화면 문장의 지표 ID 괄호와 요약의 내부 약어(BL 1 등)는 지운다
  useEffect(() => {  // 열어 본 리포트는 사이드바 「새 리포트」 배지에서 뺀다 (이 브라우저의 확인 기록)
    if (!res.data) return
    for (const k of new Set([reportId, res.data.run_id, (res.data as { report_id?: string }).report_id].filter(Boolean) as string[])) markReportSeen(svc.mode, k)
  }, [svc, reportId, res.data])
  const [source, setSource] = useState<EvidenceRecord | { id: string } | null>(null)
  const [drawer, setDrawer] = useState<DrawerFilter | null>(null)
  const [panel, setPanel] = useState<"calc" | "exec" | null>(null)
  const [terms, setTerms] = useState(false)
  const [active, setActive] = useState<string>("summary")
  const lockActive = useRef(0)  // 탭을 눌러 이동하는 동안에는 스크롤 위치로 활성 탭을 바꾸지 않는다
  const [busy, setBusy] = useState("")
  const [actErr, setActErr] = useState("")
  const [startPaper, setStartPaper] = useState(false)
  const [revise, setRevise] = useState(false)
  const [openSecs, setOpenSecs] = useState<Record<string, boolean>>({})
  const [selectedRb, setSelectedRb] = useState<number | null>(rb ?? null)
  const [openCompany, setOpenCompany] = useState<string | null>(company ?? null)
  const cmp = useResource(() => svc.getReportComparison(reportId), [svc, reportId])
  const renamed = useRenameTick()
  const name = useResource(() => (svc.getReportName ? svc.getReportName(reportId) : Promise.resolve(null)), [svc, reportId, renamed]).data
  const rows = useResource(() => svc.listReports(), [svc, renamed])  // 목록 행: 바꾼 이름(제안 기능)과 삭제 창의 이름(lib/reportName)
  const row = findReportRow(rows.data, reportId)
  const [rename, setRename] = useState(false)
  const [removing, setRemoving] = useState(false)
  const evidenceById = useMemo(() => new Map((doc?.evidence ?? []).map((e) => [e.id, e])), [doc])
  const numbers = useMemo(() => (doc ? citationNumbers(doc) : new Map<string, number>()), [doc])
  const numberOf = useCallback((id: string) => String(numbers.get(id) ?? id), [numbers])
  const openEvidence = useCallback((id: string) => { setSource(evidenceById.get(id) ?? { id }) }, [evidenceById])
  const cite = useMemo(() => ({ onCite: openEvidence, label: numberOf }), [openEvidence, numberOf])
  const jumped = useRef(false)

  // 섹션을 펼치고 그 자리(또는 섹션 안 anchor 요소)로 스크롤. 펼친 다음 렌더에서 내용이 생기므로 조금 기다린다.
  const jump = useCallback((id: string, anchor?: string) => {
    if (id !== "summary") setOpenSecs((o) => ({ ...o, [id]: true }))
    setActive(groupOf(id))
    lockActive.current = Date.now() + 900
    const target = () => (anchor && document.getElementById(anchor)) || document.getElementById(`sec-${id}`)
    window.setTimeout(() => target()?.scrollIntoView({ behavior: "smooth", block: "start" }), 80)
    window.setTimeout(() => {  // 이동 중 위쪽 내용 높이가 바뀌어 조금 어긋났으면 맞춘다 (사용자가 멀리 스크롤했으면 건드리지 않는다)
      const el = target(), d = el ? el.getBoundingClientRect().top - STOP : 0
      if (el && Math.abs(d) > 8 && Math.abs(d) < 400) el.scrollIntoView({ block: "start" })
    }, 1100)
    navigate({ page: "report", reportId, sec: id, company: openCompany ?? undefined, rb: selectedRb ?? undefined })
  }, [reportId, openCompany, selectedRb])

  useEffect(() => {  // 같은 리포트에서 주소만 바뀐 경우 (링크·뒤로 가기): 가리키는 기업·시점·섹션을 펼친다
    if (company && company !== openCompany) { setOpenCompany(company); setOpenSecs((o) => ({ ...o, companies: true })) }
  }, [company])  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (rb !== undefined && rb !== selectedRb) { setSelectedRb(rb); setOpenSecs((o) => ({ ...o, construction: true })) }
  }, [rb])  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (sec) setOpenSecs((o) => (o[sec] ? o : { ...o, [sec]: true })) }, [sec])
  useEffect(() => {  // 주소가 가리키는 곳으로 처음 한 번 이동: 기업 카드 > 리밸런싱 타임라인 > 섹션
    if (!doc || jumped.current || (!sec && !company && rb === undefined)) return
    jumped.current = true
    const target = () => typeof document === "undefined" ? null : (company && document.getElementById(`acc-${company}`)) || (rb !== undefined && document.getElementById("rb-timeline")) || (sec ? document.getElementById(`sec-${sec}`) : null)
    window.setTimeout(() => target()?.scrollIntoView({ block: "start" }), 120)
    window.setTimeout(() => {  // 위쪽 카드·차트가 자리를 잡으며 높이가 바뀌면 한 번 더 맞춘다 (고정 탭 아래 멈춤 위치에서 벗어난 경우만)
      const el = target()
      if (el && Math.abs(el.getBoundingClientRect().top - STOP) > 8) el.scrollIntoView({ block: "start" })
    }, 700)
  }, [doc, sec, company, rb])
  useEffect(() => {  // 지금 보는 섹션: 상단 탭 바로 아래를 지난 마지막 섹션. 페이지 끝에 닿으면 화면에 보이는 마지막 섹션
    if (!doc) return
    let raf = 0
    const calc = () => {
      raf = 0
      if (Date.now() < lockActive.current) return
      const els = Array.from(document.querySelectorAll<HTMLElement>('[id^="sec-"]'))
      if (!els.length) return
      let cur = els[0].id
      for (const el of els) if (el.getBoundingClientRect().top <= TAB_OFFSET) cur = el.id
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) for (const el of els) if (el.getBoundingClientRect().top < window.innerHeight - 80) cur = el.id
      setActive(groupOf(cur.replace("sec-", "")))  // 활성 표시는 묶음 단위
    }
    const on = () => { if (!raf) raf = window.requestAnimationFrame(calc) }
    window.addEventListener("scroll", on, { passive: true }); window.addEventListener("resize", on)
    on()
    return () => { window.removeEventListener("scroll", on); window.removeEventListener("resize", on); if (raf) window.cancelAnimationFrame(raf) }
  }, [doc])

  // 시점·기업 선택은 주소만 바꾸고 화면은 그 자리에 둔다 (맨 위로 튀던 문제, P1-4)
  const ctx = useMemo<ReportCtx | null>(() => doc ? ({ reportId, doc, numberOf, openEvidence, openDrawer: (f) => setDrawer(f), jump, openPanel: setPanel, selectedRb, setSelectedRb: (s) => { setSelectedRb(s); navigate({ page: "report", reportId, sec: "construction", company: openCompany ?? undefined, rb: s ?? undefined }, { scroll: false }) }, openCompany, setOpenCompany: (t) => { setOpenCompany(t); navigate({ page: "report", reportId, sec: "companies", company: t ?? undefined, rb: selectedRb ?? undefined }, { scroll: false }) } }) : null, [doc, reportId, numberOf, openEvidence, jump, selectedRb, openCompany])

  if (res.status === "loading" && !doc) return <Loading label="리포트를 불러오는 중…" />
  if (res.status === "error" && !doc) {
    const code = res.errorCode
    return <EmptyState title={code === "REPORT_NOT_READY" ? "리포트가 아직 만들어지지 않았습니다" : code === "REPORT_BLOCKED" ? "이 실행은 리포트를 만들지 않았습니다" : "이 결과를 열 수 없습니다"} description={res.error ?? ""}
      action={<div className="flex gap-2"><Button variant="secondary" onClick={() => navigate({ page: "run", runId: reportId })}>실행 상태 보기</Button><Button onClick={() => navigate({ page: "reports" })}>목록으로</Button><Button variant="ghost" onClick={res.reload}>다시 시도</Button></div>} />
  }
  if (!doc || !ctx) return null
  const h = doc.header
  const opensFirst = (id: string) => id === sec || (id === "companies" && !!company) || (id === "construction" && rb !== undefined)  // 상세 섹션은 접힌 채 시작, 주소가 가리키는 부분만 펼친다
  const isOpen = (id: string) => openSecs[id] ?? opensFirst(id)
  const allIds = [...doc.sections.map((s) => s.id), "history"]
  const allOpen = allIds.every(isOpen)
  const toggleAll = () => setOpenSecs(Object.fromEntries(allIds.map((id) => [id, !allOpen])))
  const parts = doc.sections.map((s) => ({ id: s.id, title: sectionTitle(s.id, s.title_ko), sub: s.title_ko, body: <SectionBody s={s} doc={doc} /> as React.ReactNode }))
  const at = parts.findIndex((x) => x.id === "assumptions")
  parts.splice(at < 0 ? parts.length : at, 0, { id: "history", title: HISTORY_TITLE, sub: "투자 아이디어와 요청 내역", body: <RequestHistory requestId={doc.request_id} log={proposedOf(doc)?.request_log ?? null} /> })
  const rerun = async () => {
    setBusy("rerun")
    setActErr("")
    try { const st = await svc.rerun(doc.run_id); navigate({ page: "clarify", requestId: st.request_id }) } catch (e) { setActErr(errorMessage(e)) } finally { setBusy("") }
  }
  const menu = [
    { label: "조건 확인 후 다시 분석", icon: RefreshCw, onClick: rerun, disabled: readOnly || busy === "rerun" },
    ...(cmp.data ? [{ label: "원안과 비교", icon: GitCompareArrows, onClick: () => navigate({ page: "comparison", comparisonId: cmp.data!.comparison_id }) }] : []),
    { label: "계산 조건", icon: Sigma, onClick: () => setPanel("calc") }, { label: "실행 기록", icon: ListChecks, onClick: () => setPanel("exec") },
    { label: `출처 전체 (${doc.evidence_summary?.total ?? doc.evidence.length})`, icon: BookOpenText, onClick: () => setDrawer({ ids: null, title: "출처 전체" }) },
    // 이름 바꾸기·삭제(제안 기능)는 서비스에 메서드가 있을 때만 — 지금은 목업뿐
    ...(name && svc.renameReport && !readOnly ? [{ label: "이름 바꾸기", icon: Pencil, onClick: () => setRename(true) }] : []),
    ...(svc.deleteReport && !readOnly ? [{ label: "리포트 삭제", icon: Trash2, onClick: () => setRemoving(true), danger: true }] : []),
    ...extraMenu,
  ]
  // 헤더에는 백테스트 기간만 두고, 나머지 날짜는 (?) 도움말 안에서 본다
  const otherDates: [string, string][] = [["작성일", h.created_at], ["분석 기준일", h.data_as_of], ["종목 선정 기준일", h.selection_as_of]]
  const groups = groupsFor(doc)
  const jumpGroup = (gid: string) => { const g = groups.find((x) => x.id === gid); jump(g?.sections[0] ?? gid) }
  const groupStart = new Map(groups.map((g) => [g.sections.find((s) => s !== "summary"), g] as const))
  return (
    <ReportContext.Provider value={ctx}>
      <CitationContext.Provider value={cite}>
        <div className="report-body min-w-0 space-y-8">
            <button type="button" onClick={() => navigate({ page: "reports" })} className="flex items-center gap-1 text-xs font-semibold text-slate-600 hover:underline lg:hidden"><ArrowLeft className="size-4" />분석 리포트 목록</button>
            <header className="mb-5! space-y-4">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                  <p className="mb-2 text-xs font-bold tracking-widest text-blue-700">분석 리포트</p>
                  {/* 제목 = 리포트의 짧은 제목(header.title_ko, 바꾼 이름이 있으면 그것), 회색 글 = 요청과 처리 이유 요약(summary_ko, 없는 옛 리포트는 요청 해석 subtitle_ko) */}
                  <div className="flex items-start gap-1">
                    <h1 className="break-words text-3xl font-bold tracking-tight text-slate-950">{title || (row && proposedNameOf(row)) || name?.display_ko || h.title_ko}</h1>
                    {name && svc.renameReport && <button type="button" aria-label="리포트 이름 바꾸기" title="리포트 이름 바꾸기" onClick={() => setRename(true)} className="mt-1 shrink-0 rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"><Pencil className="size-5" /></button>}
                  </div>
                  {(h.summary_ko || h.subtitle_ko) && <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">{h.summary_ko || h.subtitle_ko}</p>}
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-2 lg:pt-6">
                  <span data-tour="paper-start" title={readOnly ? "둘러보기 중에는 실행되지 않습니다" : doc.tracking.eligible ? undefined : (doc.tracking.reason_ko ?? "이 리포트로는 모의투자를 시작할 수 없습니다")}><Button onClick={() => setStartPaper(true)} disabled={readOnly || !doc.tracking.eligible}><Activity className="size-4" />모의투자 시작</Button></span>
                  <Button variant="secondary" onClick={() => setRevise(true)} disabled={readOnly}><PencilLine className="size-4" />조건 수정 요청</Button>
                  <Menu items={menu} />
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-slate-600">
                <dl aria-label="리포트 날짜" className="contents"><div className="flex gap-1 whitespace-nowrap"><dt>백테스트 기간</dt><dd className="tabular-nums text-slate-800">{h.backtest_period.start} ~ {h.backtest_period.end}</dd></div></dl>
                <HelpTip label="날짜 구분">
                  <dl aria-label="다른 기준 날짜" className="mb-2 space-y-0.5">{otherDates.map(([k, v]) => <div key={k} className="flex justify-between gap-3"><dt>{k}</dt><dd className="tabular-nums font-semibold">{v}</dd></div>)}</dl>
                  작성일은 리포트를 만든 날입니다. 분석 기준일은 분석에 쓴 가격·뉴스 자료의 기준 날짜로, 투자 금액 카드의 현재 구성도 이 날 기준입니다. 종목 선정 기준일은 투자할 종목 목록을 고른 날짜이고, 과거 성과 계산(백테스트)용 종목은 백테스트 시작일 자료로 다시 골랐습니다. 백테스트 기간은 과거 자료로 성과를 계산한 기간입니다.
                </HelpTip>
                {doc.presented_from_version === 1 && <Badge tone="slate">예전 형식 리포트 (자동 변환)</Badge>}
              </div>
            </header>
            <ReportTabs doc={doc} active={active} onJump={jumpGroup} onGlossary={() => setTerms(true)} />
            {actErr && <Alert title="처리하지 못했습니다" tone="error">{actErr}</Alert>}
            {startPaper && <StartPaperDialog reportId={doc.run_id} close={() => setStartPaper(false)} />}
            {revise && <RevisionPanel reportId={doc.run_id} close={() => setRevise(false)} />}
            {rename && <RenameReportDialog reportId={reportId} close={() => setRename(false)} />}
            {removing && <DeleteReportDialog reportId={reportId} name={row ? reportName(row) : (name?.display_ko ?? h.title_ko)} close={() => setRemoving(false)} onDeleted={() => navigate({ page: "reports" })} />}
            {doc.summary && <div id="sec-summary" className="scroll-mt-16"><Dashboard summary={doc.summary} doc={doc} onJump={jump} paperReason={doc.tracking.eligible ? null : (doc.tracking.reason_ko ?? "이 리포트로는 모의투자를 시작할 수 없습니다")} /></div>}
            <section aria-labelledby="h-details" data-tour="details" className="space-y-4">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div><h2 id="h-details" className="text-xl font-bold text-slate-950">자세한 분석 보기</h2><p className="mt-1 text-sm text-slate-600">궁금한 부분을 펼쳐 보세요. 판단 근거, 계산 과정, 원문과 출처가 모두 여기에 있습니다.</p></div>
                <button type="button" onClick={toggleAll} className="shrink-0 rounded-lg px-2 py-1 text-sm font-semibold text-blue-700 hover:underline focus:outline-none focus:ring-2 focus:ring-blue-500">{allOpen ? "모두 접기" : "모두 펼치기"}</button>
              </div>
              {parts.map((x, i) => {
                const g = groupStart.get(x.id)  // 묶음의 첫 섹션 앞에 묶음 소제목 (상단 탭과 같은 이름)
                return (
                  <Fragment key={x.id}>
                    {g && <h3 id={`grp-${g.id}`} className="pt-2 text-sm font-bold tracking-wide text-slate-600">{g.heading}</h3>}
                    <SectionShell id={x.id} index={i + 1} title={x.title} sub={x.sub} open={isOpen(x.id)} onToggle={() => setOpenSecs((o) => ({ ...o, [x.id]: !isOpen(x.id) }))}>{x.body}</SectionShell>
                  </Fragment>
                )
              })}
            </section>
            <footer className="pb-10 text-xs leading-5 text-slate-500">{h.disclaimer_ko}<br />생성 {doc.generated_at} · 요청 {doc.request_id} · 실행 {doc.run_id}{doc.evidence_summary ? ` · 근거 색인 ${doc.evidence_summary.total}건 (본문 인용 ${doc.evidence_summary.cited}건)` : ""}</footer>
        </div>
        {drawer && <SourceDrawer filter={drawer} close={() => setDrawer(null)} onOpen={(e) => { setDrawer(null); setSource(e) }} />}
        {source && <SourcePanel item={source} close={() => setSource(null)} />}
        {panel === "calc" && <CalculationPanel doc={doc} close={() => setPanel(null)} />}
        {panel === "exec" && <ExecutionPanel doc={doc} close={() => setPanel(null)} />}
        {terms && <GlossaryPanel doc={doc} close={() => setTerms(false)} onFull={doc.sections.some((x) => x.id === "references") ? () => { setTerms(false); jump("references") } : undefined} />}
      </CitationContext.Provider>
    </ReportContext.Provider>
  )
}
