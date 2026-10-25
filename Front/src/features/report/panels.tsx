import { useEffect, useState } from "react"
import { ApiError, errorMessage } from "../../api/client"
import type { ReportDoc, RunStatus } from "../../api/types"
import { fx, ko } from "../../lib/format"
import { Alert, Button, SidePanel, StatusRow } from "../../ui"
import { useService } from "../../app/providers"

export function CalculationPanel({ doc, close }: { doc: ReportDoc; close: () => void }) {
  const p = doc.parameters as Record<string, Record<string, unknown>>
  const bt = p.backtest ?? {}, pf = p.portfolio ?? {}, news = p.news ?? {}, dc = (p.disclosures ?? {}) as Record<string, unknown>, llm = p.llm ?? {}, ex = (p.execution_rule ?? {}) as Record<string, string>, desc = (p.descriptor ?? {}) as Record<string, unknown>
  const req = doc.sections.flatMap((s) => s.blocks).find((b) => b.type === "table" && b.title_ko === "계산 조건")
  return (
    <SidePanel title="계산 조건" close={close}>
      {req && req.type === "table" && <dl className="space-y-4">{req.rows.map((r, i) => <div key={i}><dt className="text-xs font-semibold text-slate-400">{String(r.k)}</dt><dd className="mt-1 text-sm leading-6 text-slate-700">{String(r.v)}</dd></div>)}</dl>}
      {doc.header.backtest_mode && <p className="mt-4 text-xs text-slate-500">백테스트 방식: {doc.header.backtest_mode}</p>}
      <h3 className="mt-6 text-sm font-bold text-slate-800">설정값 원본 (개발자 참고용 · 영문 키)</h3>
      <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-2 text-xs text-slate-600">
        {Object.entries({ ...Object.fromEntries(Object.entries(bt).map(([k, v]) => [`backtest.${k}`, v])), ...Object.fromEntries(Object.entries(pf).filter(([k]) => !["template_names_ko", "risk_aversion", "risk_aversion_mult"].includes(k)).map(([k, v]) => [`portfolio.${k}`, v])), ...Object.fromEntries(Object.entries(news).map(([k, v]) => [`news.${k}`, v])), ...Object.fromEntries(Object.entries(dc).filter(([k]) => !["event_types", "summary_extra_event_types"].includes(k)).map(([k, v]) => [`disclosures.${k}`, v])), ...Object.fromEntries(Object.entries(llm).map(([k, v]) => [`llm.${k}`, v])), "execution_rule": ex.description_ko, "descriptor.file": desc.file, "descriptor.snapshot_date": desc.snapshot_date }).map(([k, v]) => <div key={k} className="flex justify-between gap-3 border-b border-slate-100 py-1"><dt className="font-mono">{k}</dt><dd className="text-right">{Array.isArray(v) ? v.join(", ") : typeof v === "object" && v ? JSON.stringify(v) : String(v ?? "–")}</dd></div>)}
      </dl>
      <p className="mt-4 text-xs text-slate-500">환율 표기는 항상 "{fx(1)}" 형식의 1 USD 당 KRW 입니다.</p>
    </SidePanel>
  )
}

export function ExecutionPanel({ doc, close }: { doc: ReportDoc; close: () => void }) {
  const svc = useService()
  const [live, setLive] = useState<RunStatus | null>(null)
  const [err, setErr] = useState("")
  const load = async () => { try { setLive(await svc.getRun(doc.run_id)); setErr("") } catch (e) { setErr(e instanceof ApiError ? e.message : errorMessage(e)) } }
  useEffect(() => { void load() }, [doc.run_id]) // eslint-disable-line react-hooks/exhaustive-deps
  const numberNotes = doc.warnings ?? []
  return (
    <SidePanel title="실행 기록" close={close}>
      {err && <Alert title="실행 상태를 조회하지 못했습니다" tone="warning">{err}</Alert>}
      {live ? (
        <div className="space-y-3">
          <p className="text-xs text-slate-500">상태 {ko(live.status)} · 시작 {live.started_at ?? "–"} · 종료 {live.finished_at ?? "–"} · 실행 번호 {live.run_id}</p>
          {live.steps.map((s) => <StatusRow key={s.step} label={s.label_ko} status={s.status} detail={s.error_message ?? s.summary ?? null} />)}
        </div>
      ) : (
        <ol className="space-y-2 text-sm">{doc.execution.map((e) => <li key={e.step} className="rounded-lg bg-slate-50 p-3"><p className="font-mono text-xs text-slate-500">{e.step}</p><p className="mt-1 text-slate-700">{e.summary}</p></li>)}</ol>
      )}
      {doc.assessment.comments_ko.length > 0 && (
        <div className="mt-5 rounded-xl border border-slate-200 p-4 text-sm text-slate-700"><div className="mb-1 font-semibold text-slate-900">분석 모델의 자체 평가</div><p className="text-xs text-slate-500">의도 일치 {doc.assessment.intent_fit ?? "–"} · 논리 일관성 {doc.assessment.logic_consistency ?? "–"} (0~1)</p><ul className="mt-2 list-disc pl-5 leading-6">{doc.assessment.comments_ko.map((c, i) => <li key={i}>{c}</li>)}</ul></div>
      )}
      {numberNotes.length > 0 && (
        <div className="mt-5 rounded-xl border border-slate-200 p-4 text-sm"><div className="mb-1 font-semibold text-slate-900">문장 검증 메모 {numberNotes.length}건 (숫자 대조)</div><p className="text-xs text-slate-500">본문 숫자가 결과값 표에서 그대로 찾아지지 않은 경우입니다. 반올림·단위 차이일 수 있습니다.</p><ul className="mt-2 list-disc pl-5 text-xs leading-5 text-slate-600">{numberNotes.slice(0, 30).map((w, i) => <li key={i}>{w}</li>)}</ul></div>
      )}
      <Button variant="secondary" className="mt-4" onClick={load}>실행 상태 다시 조회</Button>
    </SidePanel>
  )
}
