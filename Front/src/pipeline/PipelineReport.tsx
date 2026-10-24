import { useEffect, useState } from "react"
import type { ReportDoc } from "./types"
import { RenderBlock } from "./blocks"

export default function PipelineReport() {
  const [doc, setDoc] = useState<ReportDoc | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    fetch("/pipeline/report.json").then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() }).then(setDoc).catch((e) => setError(String(e)))
  }, [])
  if (error) return <div className="p-10 text-slate-700">리포트를 불러오지 못했습니다. ({error}) <code className="text-xs">module_mockup/scripts/stage15_publish.py</code> 를 실행한 뒤 새로고침하세요.</div>
  if (!doc) return <div className="p-10 text-slate-500">리포트를 불러오는 중입니다…</div>
  const h = doc.header
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 h-screen w-64 shrink-0 border-r border-slate-200 bg-white px-5 py-6">
        <div className="text-xs font-semibold tracking-wide text-brand-700">MyFinSight · 분석 리포트</div>
        <nav className="mt-6 space-y-1 text-sm" aria-label="섹션">
          {doc.nav.map((n, i) => <a key={n.id} href={`#/pipeline/${n.id}`} onClick={(e) => { e.preventDefault(); document.getElementById(`sec-${n.id}`)?.scrollIntoView({ behavior: "smooth" }) }} className="block rounded px-2 py-1.5 text-slate-700 hover:bg-slate-100">{i + 1}. {n.title_ko}</a>)}
        </nav>
        <div className="mt-8 text-xs leading-5 text-slate-500">
          작성일 {h.created_at}<br />종목 선정 기준일 {h.selection_as_of}<br />백테스트 {h.backtest_period.start} ~ {h.backtest_period.end}<br />자료 기준일 {h.data_as_of}
        </div>
        <a href="#/home" className="mt-8 block text-xs text-slate-400 hover:text-slate-600">앱 홈으로</a>
      </aside>
      <main className="min-w-0 flex-1 px-10 py-8">
        <header className="mb-8 max-w-4xl">
          <h1 className="text-2xl font-bold text-slate-900">{h.title_ko}</h1>
          <p className="mt-2 text-[15px] leading-7 text-slate-700">{h.subtitle_ko}</p>
          <p className="mt-2 text-sm text-slate-500">중심 포트폴리오: <b>{h.chosen_label_ko}</b> — {h.chosen_note_ko}</p>
        </header>
        <div className="max-w-5xl space-y-12">
          {doc.sections.map((s, i) => (
            <section key={s.id} id={`sec-${s.id}`} className="scroll-mt-6">
              <h2 className="mb-5 text-xl font-semibold text-slate-900">{i + 1}. {s.title_ko}</h2>
              <div className="space-y-5">{s.blocks.map((b, k) => <RenderBlock key={k} b={b} doc={doc} />)}</div>
            </section>
          ))}
          {doc.assessment.comments_ko.length > 0 && (
            <section className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-700">
              <div className="mb-2 font-semibold text-slate-900">분석 모델의 자체 평가</div>
              <p>의도 일치 {doc.assessment.intent_fit ?? "–"} · 논리 일관성 {doc.assessment.logic_consistency ?? "–"} (0~1)</p>
              <ul className="mt-2 list-disc pl-5 leading-6">{doc.assessment.comments_ko.map((c, i) => <li key={i}>{c}</li>)}</ul>
            </section>
          )}
          <footer className="pb-10 text-xs leading-5 text-slate-400">{h.disclaimer_ko}<br />생성 {doc.generated_at} · 요청 {doc.request_id}</footer>
        </div>
      </main>
    </div>
  )
}
