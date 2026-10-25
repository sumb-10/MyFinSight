import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Activity, GitCompareArrows, ListChecks, PencilLine, RefreshCw, Sigma } from "lucide-react"
import { useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { errorMessage } from "../../api/client"
import type { EvidenceRecord, ReportDoc } from "../../api/types"
import { useResource } from "../../state/useResource"
import { Alert, Badge, Button, EmptyState, Loading, Menu, PageHeader, Disclosure } from "../../ui"
import { citationNumbers } from "../../lib/citations"
import { groupBlocks, normalizeDoc } from "../../lib/reportNormalize"
import { CitationContext, RenderBlock } from "./blocks/blocks"
import { StartPaperDialog } from "../paper/StartPaperDialog"
import { RevisionPanel } from "./RevisionPanel"
import { Dashboard } from "./Dashboard"
import { SectionNav } from "./SectionNav"
import { SectionShell } from "./SectionShell"
import { SourceDrawer } from "./SourceDrawer"
import { SourcePanel } from "./SourcePanel"
import { CalculationPanel, ExecutionPanel } from "./panels"
import { type DrawerFilter, ReportContext, type ReportCtx } from "./context"

/** 리포트 화면 v2 (라운드 4): 요약 대시보드 + 접이식 7부분, 근거는 드로어·패널로. 주소 ?sec=&company=&rb= 를 읽고 쓴다. */
export function ReportDetail({ reportId, sec, company, rb }: { reportId: string; sec?: string; company?: string; rb?: number }) {
  const svc = useService()
  const res = useResource(() => svc.getReport(reportId), [svc, reportId])
  const doc = useMemo(() => (res.data ? normalizeDoc(res.data) : null), [res.data])
  const [source, setSource] = useState<EvidenceRecord | { id: string } | null>(null)
  const [drawer, setDrawer] = useState<DrawerFilter | null>(null)
  const [panel, setPanel] = useState<"calc" | "exec" | null>(null)
  const [active, setActive] = useState<string>("")
  const [busy, setBusy] = useState("")
  const [actErr, setActErr] = useState("")
  const [startPaper, setStartPaper] = useState(false)
  const [revise, setRevise] = useState(false)
  const [openSecs, setOpenSecs] = useState<Record<string, boolean>>({})
  const [selectedRb, setSelectedRb] = useState<number | null>(rb ?? null)
  const [openCompany, setOpenCompany] = useState<string | null>(company ?? null)
  const cmp = useResource(() => svc.getReportComparison(reportId), [svc, reportId])
  const evidenceById = useMemo(() => new Map((doc?.evidence ?? []).map((e) => [e.id, e])), [doc])
  const numbers = useMemo(() => (doc ? citationNumbers(doc) : new Map<string, number>()), [doc])
  const numberOf = useCallback((id: string) => String(numbers.get(id) ?? id), [numbers])
  const openEvidence = useCallback((id: string) => { setSource(evidenceById.get(id) ?? { id }) }, [evidenceById])
  const cite = useMemo(() => ({ onCite: openEvidence, label: numberOf }), [openEvidence, numberOf])
  const jumped = useRef(false)

  const jump = useCallback((id: string) => {
    setOpenSecs((o) => ({ ...o, [id]: true }))
    window.setTimeout(() => document.getElementById(`sec-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 30)
    navigate({ page: "report", reportId, sec: id, company: openCompany ?? undefined, rb: selectedRb ?? undefined })
  }, [reportId, openCompany, selectedRb])

  useEffect(() => {  // 주소의 섹션으로 처음 한 번 이동
    if (!doc || jumped.current || !sec) return
    jumped.current = true
    window.setTimeout(() => document.getElementById(`sec-${sec}`)?.scrollIntoView({ block: "start" }), 80)
  }, [doc, sec])
  useEffect(() => {
    if (!doc) return
    const ids = ["summary", ...doc.sections.map((s) => s.id)]
    const els = ids.map((id) => document.getElementById(`sec-${id}`)).filter(Boolean) as HTMLElement[]
    if (typeof IntersectionObserver === "undefined") return
    const io = new IntersectionObserver((entries) => { const top = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0]; if (top) setActive(top.target.id.replace("sec-", "")) }, { rootMargin: "-20% 0px -70% 0px" })
    els.forEach((el) => io.observe(el))
    return () => io.disconnect()
  }, [doc])

  // 시점·기업 선택은 주소만 바꾸고 화면은 그 자리에 둔다 (맨 위로 튀던 문제, P1-4)
  const ctx = useMemo<ReportCtx | null>(() => doc ? ({ reportId, doc, numberOf, openEvidence, openDrawer: (f) => setDrawer(f), jump, selectedRb, setSelectedRb: (s) => { setSelectedRb(s); navigate({ page: "report", reportId, sec: "construction", company: openCompany ?? undefined, rb: s ?? undefined }, { scroll: false }) }, openCompany, setOpenCompany: (t) => { setOpenCompany(t); navigate({ page: "report", reportId, sec: "companies", company: t ?? undefined, rb: selectedRb ?? undefined }, { scroll: false }) } }) : null, [doc, reportId, numberOf, openEvidence, jump, selectedRb, openCompany])

  if (res.status === "loading" && !doc) return <Loading label="리포트를 불러오는 중…" />
  if (res.status === "error" && !doc) {
    const code = res.errorCode
    return <EmptyState title={code === "REPORT_NOT_READY" ? "리포트가 아직 만들어지지 않았습니다" : code === "REPORT_BLOCKED" ? "이 실행은 리포트를 만들지 않았습니다" : "이 결과를 열 수 없습니다"} description={res.error ?? ""}
      action={<div className="flex gap-2"><Button variant="secondary" onClick={() => navigate({ page: "run", runId: reportId })}>실행 상태 보기</Button><Button onClick={() => navigate({ page: "reports" })}>목록으로</Button><Button variant="ghost" onClick={res.reload}>다시 시도</Button></div>} />
  }
  if (!doc || !ctx) return null
  const h = doc.header
  const isOpen = (id: string) => openSecs[id] ?? true
  const allOpen = doc.sections.every((s) => isOpen(s.id))
  const toggleAll = () => setOpenSecs(Object.fromEntries(doc.sections.map((s) => [s.id, !allOpen])))
  const rerun = async () => {
    setBusy("rerun")
    setActErr("")
    try { const st = await svc.rerun(doc.run_id); navigate({ page: "clarify", requestId: st.request_id }) } catch (e) { setActErr(errorMessage(e)) } finally { setBusy("") }
  }
  const menu = [
    { label: "조건 확인 후 다시 분석", icon: RefreshCw, onClick: rerun, disabled: busy === "rerun" },
    ...(cmp.data ? [{ label: "원안과 비교", icon: GitCompareArrows, onClick: () => navigate({ page: "comparison", comparisonId: cmp.data!.comparison_id }) }] : []),
    { label: "계산 조건", icon: Sigma, onClick: () => setPanel("calc") }, { label: "실행 기록", icon: ListChecks, onClick: () => setPanel("exec") },
  ]
  return (
    <ReportContext.Provider value={ctx}>
      <CitationContext.Provider value={cite}>
        <div className="flex gap-8">
          <SectionNav doc={doc} active={active} onJump={jump} allOpen={allOpen} onToggleAll={toggleAll} onCalc={() => setPanel("calc")} onExec={() => setPanel("exec")} onSources={() => setDrawer({ ids: null, title: "출처 전체" })} />
          <div className="min-w-0 flex-1 space-y-10">
            <PageHeader eyebrow={`분석 리포트 · 실행 번호 ${doc.run_id}`} title={h.title_ko} description={h.title_detail_ko ? `${h.subtitle_ko} · ${h.title_detail_ko}` : h.subtitle_ko}
              actions={<><span title={doc.tracking.eligible ? undefined : (doc.tracking.reason_ko ?? "이 리포트로는 모의투자를 시작할 수 없습니다")}><Button onClick={() => setStartPaper(true)} disabled={!doc.tracking.eligible}><Activity className="size-4" />모의투자 시작</Button></span><Button variant="secondary" onClick={() => setRevise(true)}><PencilLine className="size-4" />조건 수정 요청</Button><Menu items={menu} /></>} />
            {actErr && <Alert title="처리하지 못했습니다" tone="error">{actErr}</Alert>}
            {startPaper && <StartPaperDialog reportId={doc.run_id} close={() => setStartPaper(false)} />}
            {revise && <RevisionPanel reportId={doc.run_id} close={() => setRevise(false)} />}
            <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600"><Badge tone="blue">중심 포트폴리오: {h.chosen_label_ko}</Badge><span>{h.chosen_note_ko}</span>{(doc.notices?.length ?? 0) > 0 && <button type="button" onClick={() => jump("assumptions")}><Badge tone="amber">확인할 점 {doc.notices!.length}건</Badge></button>}{doc.presented_from_version === 1 && <Badge tone="slate">예전 형식 리포트 (자동 변환)</Badge>}</div>
            {doc.summary && <div id="sec-summary" className="scroll-mt-6"><Dashboard summary={doc.summary} doc={doc} onRerun={rerun} onRevise={() => setRevise(true)} onPaper={() => setStartPaper(true)} onJump={jump} busy={busy} paperReason={doc.tracking.eligible ? null : (doc.tracking.reason_ko ?? "이 리포트로는 모의투자를 시작할 수 없습니다")} /></div>}
            {doc.sections.map((s, i) => (
              <SectionShell key={s.id} id={s.id} index={i + 1} title={s.title_ko} open={isOpen(s.id)} onToggle={() => setOpenSecs((o) => ({ ...o, [s.id]: !isOpen(s.id) }))}>
                {groupBlocks(s.blocks).map((g, k) => g.group_ko
                  ? <Disclosure key={k} title={g.group_ko} summary={`${g.blocks.length}개 항목`} defaultOpen={!!g.open}><div className="space-y-5">{g.blocks.map((b, j) => <RenderBlock key={j} b={b} doc={doc as ReportDoc} />)}</div></Disclosure>
                  : g.blocks.map((b, j) => <RenderBlock key={`${k}-${j}`} b={b} doc={doc as ReportDoc} />))}
              </SectionShell>
            ))}
            <footer className="pb-10 text-xs leading-5 text-slate-400">{h.disclaimer_ko}<br />생성 {doc.generated_at} · 요청 {doc.request_id} · 실행 {doc.run_id}{doc.evidence_summary ? ` · 근거 색인 ${doc.evidence_summary.total}건 (본문 인용 ${doc.evidence_summary.cited}건)` : ""}</footer>
          </div>
        </div>
        {drawer && <SourceDrawer filter={drawer} close={() => setDrawer(null)} onOpen={(e) => { setDrawer(null); setSource(e) }} />}
        {source && <SourcePanel item={source} close={() => setSource(null)} />}
        {panel === "calc" && <CalculationPanel doc={doc} close={() => setPanel(null)} />}
        {panel === "exec" && <ExecutionPanel doc={doc} close={() => setPanel(null)} />}
      </CitationContext.Provider>
    </ReportContext.Provider>
  )
}
