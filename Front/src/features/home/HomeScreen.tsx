import { useEffect, useState } from "react"
import { ChevronRight, SlidersHorizontal, Sparkles, X } from "lucide-react"
import { useProfile, useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { errorMessage } from "../../api/client"
import { useResource } from "../../state/useResource"
import { loadUi, saveUi } from "../../state/uiStorage"
import { Alert, Badge, Button, Card, EmptyState, ErrorState, Loading } from "../../ui"
import { date, fmt, ko } from "../../lib/format"
import { DetailConditionsDialog, OVERRIDE_LABELS, overrideText, type Overrides } from "./DetailConditions"

export function HomeScreen() {
  const svc = useService()
  const { profile, status, error: profileError, reload } = useProfile()
  const [idea, setIdea] = useState(() => { const u = loadUi(); return u.prefillIdea ?? u.draftIdea ?? "" })
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const [overrides, setOverrides] = useState<Overrides>(() => (loadUi().prefillOverrides as Overrides | null | undefined) ?? {})
  const [detail, setDetail] = useState(false)
  const reports = useResource(() => svc.listReports(), [svc])
  const [ui, setUi] = useState(() => loadUi())
  useEffect(() => { saveUi({ draftIdea: idea }) }, [idea])
  useEffect(() => { const u = loadUi(); if (u.prefillIdea || u.prefillOverrides) setUi(saveUi({ prefillIdea: null, prefillOverrides: null })) }, [])  // 미리 채운 값(새 요청)은 한 번만 쓴다

  if (status === "loading") return <Loading />
  if (status === "error") return <ErrorState title="분석 서버에 연결할 수 없습니다" message={profileError ?? ""} retry={() => void reload()} />
  if (!profile) return <EmptyState title="먼저 내 투자조건을 설정해주세요." description="분석에 사용할 금액, 기간, 투자성향과 제약을 저장합니다." action={<Button onClick={() => navigate({ page: "profile", mode: "setup" })}>투자조건 설정 시작</Button>} />
  const p = profile.profile

  const submit = async () => {
    if (idea.trim().length < 5) { setError("분석할 투자 아이디어를 5자 이상 입력해주세요."); return }
    setBusy(true); setError("")
    try {
      const st = await svc.createRequest({ idea: idea.trim(), mode: "new", overrides })
      saveUi({ draftIdea: "", activeRequestId: st.request_id })
      setIdea("")
      navigate({ page: "clarify", requestId: st.request_id })
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }

  return (
    <div className="space-y-8">
      <div className="mx-auto max-w-4xl pt-10 text-center">
        <Badge><Sparkles className="size-3" />개인화 투자전략</Badge>
        <h1 className="mt-5 text-4xl font-extrabold tracking-tight text-slate-950">투자 아이디어를 포트폴리오로 확인해보세요.</h1>
        <p className="mt-3 text-base text-slate-600">내 투자조건을 반영해 종목을 고르고, 과거 데이터로 성과와 위험을 검증합니다. 부족한 조건은 분석 모델이 한 번에 하나씩 물어봅니다.</p>
        <div className="mt-8 rounded-2xl border border-slate-200 bg-white p-3 text-left shadow-sm">
          <textarea value={idea} onChange={(e) => { setIdea(e.target.value); setError("") }} className="min-h-36 w-full resize-none rounded-xl border-0 p-3 text-base leading-7 outline-none placeholder:text-slate-400" placeholder="예: 미국과 한국의 반도체·메모리 기업에 분산 투자하고 싶어요. 특정 종목에 너무 집중하고 싶지는 않습니다." />
          {Object.keys(overrides).length > 0 && (
            <div className="flex flex-wrap items-center gap-2 px-2 pb-3">
              <span className="text-xs font-semibold text-slate-500">이번 분석에만 적용:</span>
              {Object.entries(overrides).map(([k, v]) => <Badge key={k} tone="blue">{OVERRIDE_LABELS[k] ?? k} {overrideText(k, v)}</Badge>)}
              <button className="text-xs text-slate-400 hover:text-slate-700" onClick={() => setOverrides({})}><X className="inline size-3" /> 모두 지우기</button>
            </div>
          )}
          <div className="flex items-center justify-between border-t border-slate-100 px-2 pt-3">
            <p className="text-xs text-slate-400">분석은 보충 질문과 조건 확인을 거친 뒤 「분석 시작」을 눌러야 시작됩니다.</p>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setDetail(true)}><SlidersHorizontal className="size-4" />상세 조건{Object.keys(overrides).length ? ` (${Object.keys(overrides).length})` : ""}</Button>
              <Button onClick={submit} disabled={busy}>{busy ? "의도 해석 중…" : "투자조건 확인하기"}<ChevronRight className="size-4" /></Button>
            </div>
          </div>
          {error && <p className="px-2 pt-2 text-xs font-medium text-red-600">{error}</p>}
        </div>
      </div>
      {detail && <DetailConditionsDialog profile={profile.profile} initial={overrides} onApply={setOverrides} close={() => setDetail(false)} />}
      {(ui.activeRequestId || ui.activeRunId) && (
        <Alert title="진행 중이던 분석이 있습니다" tone="info">
          <div className="flex gap-2">
            {ui.activeRequestId && <Button variant="secondary" onClick={() => navigate({ page: "clarify", requestId: ui.activeRequestId! })}>조건 확인 이어서</Button>}
            {ui.activeRunId && <Button variant="secondary" onClick={() => navigate({ page: "run", runId: ui.activeRunId! })}>실행 상태 보기</Button>}
            <Button variant="ghost" onClick={() => setUi(saveUi({ activeRequestId: null, activeRunId: null }))}>지우기</Button>
          </div>
        </Alert>
      )}
      <div className="grid grid-cols-[1.2fr_1fr] gap-5">
        <Card className="p-6">
          <div className="flex items-start justify-between">
            <div><h2 className="font-bold text-slate-900">저장된 기본 투자조건</h2><p className="mt-1 text-xs text-slate-500">버전 {profile.current_version} · 이번 분석에서만 바꿀 수 있습니다.</p></div>
            <button onClick={() => navigate({ page: "profile" })} className="text-xs font-semibold text-blue-700">내 투자조건 보기</button>
          </div>
          <div className="mt-5 grid grid-cols-4 gap-3">
            {[["금액", `${p.capital.initial_amount.toLocaleString("ko-KR")} ${p.capital.currency === "KRW" ? "원" : "USD"}`], ["기간", `${p.horizon.target_years}년`], ["성향", p.diagnosis?.final_tendency ?? ko(p.risk.risk_tolerance)], ["손실 감내 수준", fmt(p.risk.max_drawdown_tolerance, "pct1")]].map(([label, value]) => (
              <div key={label} className="rounded-xl bg-slate-50 p-3"><p className="text-[11px] text-slate-400">{label}</p><p className="mt-1 truncate text-sm font-bold text-slate-800">{value}</p></div>
            ))}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Badge tone="slate">{p.constraints.universe.map(ko).join(" · ")}</Badge>
            <Badge tone="slate">종목당 최대 {fmt(p.constraints.max_weight_per_stock, "pct1")}</Badge>
            <Badge tone="slate">{ko(p.strategy_preference.template)} · {ko(p.strategy_preference.baseline_weighting)}</Badge>
            {p.constraints.exclude_tickers.map((t) => <Badge key={t} tone="red">{t} 제외</Badge>)}
          </div>
        </Card>
        <Card className="p-6">
          <div className="flex justify-between"><h2 className="font-bold text-slate-900">최근 분석 리포트</h2><button onClick={() => navigate({ page: "reports" })} className="text-xs font-semibold text-blue-700">전체 보기</button></div>
          <div className="mt-3 space-y-1">
            {reports.status === "error" && <p className="text-xs text-red-600">{reports.error}</p>}
            {(reports.data ?? []).slice(0, 4).map((r) => (
              <button key={r.run_id} onClick={() => navigate({ page: "report", reportId: r.report_id ?? r.run_id })} className="flex w-full items-center justify-between rounded-xl p-3 text-left hover:bg-slate-50">
                <span><span className="block text-sm font-semibold text-slate-800">{r.strategy_name || r.idea}</span><span className="mt-0.5 block text-xs text-slate-400">{date(r.created_at)} · 기준일 {r.as_of}</span></span>
                <ChevronRight className="size-4 text-slate-300" />
              </button>
            ))}
            {reports.status === "ready" && (reports.data ?? []).length === 0 && <p className="p-3 text-sm text-slate-500">아직 완료된 분석이 없습니다.</p>}
          </div>
        </Card>
      </div>
    </div>
  )
}
