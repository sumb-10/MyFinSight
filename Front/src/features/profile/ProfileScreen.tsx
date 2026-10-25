import { useEffect, useMemo, useState } from "react"
import { Check } from "lucide-react"
import { useProfile, useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { ApiError, errorMessage } from "../../api/client"
import type { Options, ProfileFields, ProfileView, Tendency } from "../../api/types"
import { useResource } from "../../state/useResource"
import { clearLegacy, loadLegacyProfile } from "../../state/uiStorage"
import { Alert, Badge, Button, Card, Chip, ErrorState, Field, inputClass, Loading, PageHeader } from "../../ui"
import { fmt, ko, krw } from "../../lib/format"
import { QUESTIONS, TENDENCIES, TENDENCY_HELP, computeTendency, toRiskTolerance } from "./diagnosis"

type Form = ProfileFields

const DEFAULT_FORM: Form = {
  profile: { user_id: "default", age_band: "30s", investment_experience: "beginner", financial_knowledge: "basic", investable_ratio_of_assets: 0.3 },
  capital: { initial_amount: 10_000_000, currency: "KRW", trading_currency: "USD", monthly_contribution: 0, contribution_day: 25 },
  horizon: { target_years: 5, purpose: "wealth_growth", backtest_years: 3 },
  risk: { risk_tolerance: "moderate", max_drawdown_tolerance: 0.2, loss_reaction: "hold", target_annual_return: 0.08, benchmark: "SPY" },
  constraints: { universe: ["SP500", "NASDAQ100"], asset_types: ["stock"], num_holdings: { target: 10, min: 8, max: 12 }, max_weight_per_stock: 0.15, max_weight_per_sector: 0.4, min_cash_ratio: 0, exclude_tickers: [], exclude_sectors: [], exclude_themes: [], must_include_tickers: [], rebalance: { count: 1, unit: "1q" }, allow_leverage: false, allow_short: false, min_market_cap_usd: 0, min_avg_daily_volume_usd: 0 },
  strategy_preference: { template: "momentum", baseline_weighting: "equal_weight", use_news_tilt: true },
  diagnosis: { answers: {}, computed_tendency: "위험중립형", final_tendency: "위험중립형", memo: "" },
  risk_type_computed: "moderate",
  risk_type_overridden: false,
}

function fromView(v: ProfileView): Form {
  const p = v.profile
  return { profile: p.profile, capital: p.capital, horizon: p.horizon, risk: p.risk, constraints: p.constraints, strategy_preference: p.strategy_preference, diagnosis: p.diagnosis ?? DEFAULT_FORM.diagnosis, risk_type_computed: p.risk_type_computed, risk_type_overridden: p.risk_type_overridden }
}

/** 예전 fixture 앱 프로필(원화 금액·개월·5단계 성향·%)을 새 폼으로 */
function fromLegacy(l: Record<string, unknown>): Partial<Form> {
  const t = (l.finalTendency as Tendency) ?? "위험중립형"
  return {
    capital: { ...DEFAULT_FORM.capital, initial_amount: Number(l.amountKrw) || DEFAULT_FORM.capital.initial_amount },
    horizon: { ...DEFAULT_FORM.horizon, target_years: Math.max(1, Math.round((Number(l.horizonMonths) || 60) / 12)) },
    risk: { ...DEFAULT_FORM.risk, risk_tolerance: toRiskTolerance(t), max_drawdown_tolerance: (Number(l.lossTolerancePct) || 20) / 100, loss_reaction: "hold" },
    constraints: { ...DEFAULT_FORM.constraints, max_weight_per_stock: Math.min(1, Math.max(0.05, (Number(l.globalCapPct) || 15) / 100)), exclude_tickers: Array.isArray(l.excludedTickers) ? (l.excludedTickers as string[]) : [] },
    diagnosis: { answers: {}, computed_tendency: (l.computedTendency as Tendency) ?? t, final_tendency: t, memo: String(l.memo ?? "") },
    risk_type_overridden: Boolean(l.tendencyOverridden),
  }
}

export function ProfileScreen({ mode }: { mode: "setup" | "edit" | "view" }) {
  const { profile, status, reload, set, error } = useProfile()
  if (status === "loading") return <Loading />
  if (status === "error") return <ErrorState title="분석 서버에 연결할 수 없습니다" message={`${error ?? ""} 서버가 켜지면 저장된 투자조건을 다시 불러옵니다. 지금은 처음 설정을 시작하지 않습니다.`} retry={() => void reload()} />
  if (mode === "view" && profile) return <ProfileSummary view={profile} />
  return <ProfileWizard initial={profile ? fromView(profile) : null} setup={!profile} onSaved={(v) => { set(v); void reload(); navigate({ page: profile ? "profile" : "home" }) }} />
}

function ProfileSummary({ view }: { view: ProfileView }) {
  const p = view.profile
  const rows: [string, string][] = [
    ["투자금", `${p.capital.initial_amount.toLocaleString("ko-KR")} ${p.capital.currency === "KRW" ? "원" : "USD"}`],
    ["월 적립", p.capital.monthly_contribution ? `${p.capital.monthly_contribution.toLocaleString("ko-KR")} (매월 ${p.capital.contribution_day}일)` : "없음"],
    ["투자기간 · 목적", `${p.horizon.target_years}년 · ${ko(p.horizon.purpose)}`], ["백테스트 기간", `${p.horizon.backtest_years}년`],
    ["투자성향", `${p.diagnosis?.final_tendency ?? ko(p.risk.risk_tolerance)} (${ko(p.risk.risk_tolerance)})${p.risk_type_overridden ? " · 진단과 다르게 선택" : ""}`],
    ["손실 감내 수준", fmt(p.risk.max_drawdown_tolerance, "pct1")], ["목표 연수익률 · 비교지수", `${fmt(p.risk.target_annual_return, "pct1")} · ${p.risk.benchmark}`],
    ["투자 유니버스", p.constraints.universe.map(ko).join(", ")], ["종목 수", `목표 ${p.constraints.num_holdings.target} (최소 ${p.constraints.num_holdings.min} ~ 최대 ${p.constraints.num_holdings.max})`],
    ["종목당 · 섹터당 상한", `${fmt(p.constraints.max_weight_per_stock, "pct1")} · ${fmt(p.constraints.max_weight_per_sector, "pct1")}`],
    ["최소 현금 비율", fmt(p.constraints.min_cash_ratio, "pct1")], ["리밸런싱", p.constraints.rebalance.count === 0 ? "없음 (매수 후 보유)" : `${p.constraints.rebalance.count}×${ko(p.constraints.rebalance.unit)}마다`],
    ["제외 종목 · 섹터", [...p.constraints.exclude_tickers, ...p.constraints.exclude_sectors].join(", ") || "없음"],
    ["제외 테마", (p.constraints.exclude_themes ?? []).join(", ") || "없음"],
    ["시가총액 · 거래대금 하한", `${p.constraints.min_market_cap_usd ? `${(p.constraints.min_market_cap_usd / 1e9).toLocaleString("ko-KR")}B USD 이상` : "제한 없음"} · ${p.constraints.min_avg_daily_volume_usd ? `일 ${(p.constraints.min_avg_daily_volume_usd / 1e6).toLocaleString("ko-KR")}M USD 이상` : "제한 없음"}`],
    ["자산 종류", (p.constraints.asset_types ?? ["stock"]).map(ko).join(", ")],
    ["선정 기준 · 기준 비중 · 뉴스 반영", `${ko(p.strategy_preference.template)} · ${ko(p.strategy_preference.baseline_weighting)} · ${p.strategy_preference.use_news_tilt ? "켜짐" : "꺼짐"}`],
  ]
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="내 투자조건" title="저장된 기본 투자조건" description={`버전 ${view.current_version} · 저장 ${p.created_at.slice(0, 16).replace("T", " ")}. 수정하면 새 버전이 추가되고 과거 리포트는 바뀌지 않습니다.`}
        actions={<><Button variant="secondary" onClick={() => navigate({ page: "home" })}>새 분석 시작</Button><Button onClick={() => navigate({ page: "profile", mode: "edit" })}>수정</Button></>} />
      <Card className="p-6">
        <dl className="grid grid-cols-2 gap-x-8 gap-y-4 text-sm">
          {rows.map(([k, v]) => <div key={k}><dt className="text-xs font-semibold text-slate-400">{k}</dt><dd className="mt-1 font-semibold text-slate-800">{v}</dd></div>)}
        </dl>
        {p.diagnosis?.memo && <p className="mt-5 rounded-xl bg-slate-50 p-4 text-sm text-slate-600">메모: {p.diagnosis.memo}</p>}
      </Card>
      <Card className="p-6">
        <h2 className="font-bold text-slate-900">버전 이력</h2>
        <ul className="mt-3 space-y-1 text-sm text-slate-600">{view.versions.slice().reverse().map((v) => <li key={v.version}>v{v.version} · {v.created_at.slice(0, 16).replace("T", " ")}{v.note ? ` · ${v.note}` : ""}</li>)}</ul>
      </Card>
    </div>
  )
}

const STEPS = ["기본 조건", "투자성향", "종목 범위·제약", "전략 선호"]
const FIELD_KO: Record<string, string> = { "capital.initial_amount": "투자 금액", "capital.monthly_contribution": "월 적립금", "horizon.target_years": "투자기간", "horizon.backtest_years": "백테스트 기간", "constraints.num_holdings": "종목 수", "constraints.max_weight_per_stock": "종목당 상한", "constraints.max_weight_per_sector": "섹터당 상한", "constraints.universe": "투자 유니버스", "constraints.exclude_tickers": "제외 종목", diagnosis: "투자성향 진단", tendency: "투자성향" }

function ProfileWizard({ initial, setup, onSaved }: { initial: Form | null; setup: boolean; onSaved: (v: ProfileView) => void }) {
  const svc = useService()
  const options = useResource(() => svc.options(), [svc])
  const legacy = useMemo(() => (initial ? null : loadLegacyProfile()), [initial])
  const [form, setForm] = useState<Form>(() => (initial ? structuredClone(initial) : { ...structuredClone(DEFAULT_FORM), ...(legacy ? fromLegacy(legacy) : {}) }))
  const [step, setStep] = useState(0)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState("")
  const [overrideOk, setOverrideOk] = useState(initial?.risk_type_overridden ?? false)
  const [excludeText, setExcludeText] = useState(form.constraints.exclude_tickers.join(", "))
  const [includeText, setIncludeText] = useState(form.constraints.must_include_tickers.join(", "))
  const [themesText, setThemesText] = useState((form.constraints.exclude_themes ?? []).join(", "))
  const [sectorsText, setSectorsText] = useState((form.constraints.exclude_sectors ?? []).join(", "))
  const computed = useMemo(() => (Object.keys(form.diagnosis?.answers ?? {}).length ? computeTendency(form.diagnosis!.answers) : form.diagnosis?.computed_tendency ?? "위험중립형"), [form.diagnosis])

  useEffect(() => { setForm((f) => ({ ...f, diagnosis: { ...(f.diagnosis ?? DEFAULT_FORM.diagnosis!), computed_tendency: computed }, risk_type_computed: toRiskTolerance(computed) })) }, [computed])

  const upd = (patch: (f: Form) => void) => setForm((f) => { const n = structuredClone(f); patch(n); return n })
  const err = (k: string) => errors[k]

  const localCheck = (): Record<string, string> => {
    const e: Record<string, string> = {}
    const c = form.constraints
    if (!(form.capital.initial_amount > 0)) e["capital.initial_amount"] = "투자금은 0보다 커야 합니다"
    if (!(form.horizon.target_years >= 1 && form.horizon.target_years <= 10)) e["horizon.target_years"] = "투자기간은 1~10년입니다"
    if (!(form.horizon.backtest_years > 0 && form.horizon.backtest_years <= 20)) e["horizon.backtest_years"] = "백테스트 기간은 0보다 크고 20년 이하입니다"
    if (!(c.num_holdings.min <= c.num_holdings.target && c.num_holdings.target <= c.num_holdings.max)) e["constraints.num_holdings"] = "최소 ≤ 목표 ≤ 최대 순서여야 합니다"
    if (c.max_weight_per_stock * c.num_holdings.min < 1 - c.min_cash_ratio - 1e-9) e["constraints.max_weight_per_stock"] = "종목당 상한 × 최소 종목 수가 투자 비율보다 작아 비중을 채울 수 없습니다"
    if (c.max_weight_per_sector < c.max_weight_per_stock) e["constraints.max_weight_per_sector"] = "섹터당 상한은 종목당 상한 이상이어야 합니다"
    if (!c.universe.length) e["constraints.universe"] = "유니버스를 하나 이상 고르세요"
    const clash = c.must_include_tickers.filter((t) => c.exclude_tickers.includes(t))
    if (clash.length) e["constraints.exclude_tickers"] = `같은 종목이 필수 포함과 제외에 함께 있습니다: ${clash.join(", ")}`
    return e
  }

  const next = () => {
    const e = localCheck()
    const stepKeys = [["capital.", "horizon."], ["risk."], ["constraints."], ["strategy_preference."]][step]
    const mine = Object.fromEntries(Object.entries(e).filter(([k]) => stepKeys.some((p) => k.startsWith(p))))
    if (step === 1 && form.diagnosis && Object.keys(form.diagnosis.answers).length < QUESTIONS.length) mine["diagnosis"] = "필수 질문에 모두 답해 주세요"
    if (step === 1 && form.diagnosis && form.diagnosis.final_tendency !== computed && !overrideOk) mine["tendency"] = "진단 결과와 다른 성향을 선택하려면 차이를 확인해 주세요"
    setErrors(mine)
    if (Object.keys(mine).length) return
    setStep((s) => Math.min(STEPS.length - 1, s + 1))
  }

  const submit = async () => {
    const e = localCheck()
    setErrors(e)
    if (Object.keys(e).length) return
    setSaving(true); setSaveError("")
    try {
      const body: ProfileFields = { ...form, risk_type_overridden: form.diagnosis ? form.diagnosis.final_tendency !== computed : false, note: setup ? "첫 등록" : "수정" }
      const v = await svc.saveProfile(body)
      if (legacy) clearLegacy()
      onSaved(v)
    } catch (ex) {
      if (ex instanceof ApiError && ex.fields) { setErrors(ex.fields); setSaveError("입력값에 오류가 있어 저장하지 못했습니다. 표시된 항목을 확인해 주세요.") }
      else setSaveError(`저장하지 못했습니다: ${errorMessage(ex)} 입력값은 유지됩니다.`)
    } finally { setSaving(false) }
  }

  const opt: Options | null = options.data
  const bench = opt?.benchmarks ?? ["SPY", "QQQ", "069500.KS"]
  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader eyebrow={setup ? "처음 설정" : "투자조건 수정"} title={setup ? "기본 투자조건을 알려주세요." : "저장된 투자조건을 수정합니다."} description="금액과 기간, 투자성향, 종목 범위와 제약, 전략 선호를 차례로 설정합니다. 분석 요청 때 아이디어에 맞춰 일부를 바꿀 수 있습니다." />
      {legacy && setup && <div className="mt-6"><Alert title="이전 브라우저 저장 조건을 불러왔습니다" tone="info">예전 앱에 저장돼 있던 투자조건으로 미리 채웠습니다. 확인 후 저장하면 서버에 기록됩니다.</Alert></div>}
      <div className="my-8 grid grid-cols-4 gap-3">
        {STEPS.map((label, i) => {
          const keys = [["capital.", "horizon.", "profile."], ["risk.", "diagnosis", "tendency"], ["constraints."], ["strategy_preference."]][i]
          const n = Object.keys(errors).filter((k) => keys.some((p) => k.startsWith(p))).length
          return (
            <button key={label} type="button" onClick={() => (i < step || n > 0) && setStep(i)} className={`rounded-xl border p-3 text-left ${step === i ? "border-blue-300 bg-blue-50" : n > 0 ? "border-red-300 bg-red-50" : "border-slate-200 bg-white"}`}>
              <p className="text-xs font-bold text-slate-400">0{i + 1}</p><p className="mt-1 text-sm font-semibold text-slate-800">{label}{n > 0 && <span className="ml-2 rounded-full bg-red-600 px-1.5 text-[10px] font-bold text-white">{n}</span>}</p>
            </button>
          )
        })}
      </div>
      <Card className="p-7">
        {step === 0 && (
          <div className="space-y-6">
            <div><h2 className="text-lg font-bold text-slate-950">기본 투자조건</h2><p className="mt-1 text-sm text-slate-500">금액·기간·목적은 분석의 계산 조건으로 쓰입니다. 계산은 USD 로 하고 원화는 기준일 환율로 환산합니다.</p></div>
            <div className="grid grid-cols-[1fr_140px] gap-3">
              <Field label="투자 금액" error={err("capital.initial_amount")}>
                <input className={inputClass} inputMode="numeric" value={form.capital.initial_amount.toLocaleString("ko-KR")} onChange={(e) => { const v = Number(e.target.value.replace(/\D/g, "")); upd((f) => { f.capital.initial_amount = v }) }} />
              </Field>
              <Field label="통화"><select className={inputClass} value={form.capital.currency} onChange={(e) => upd((f) => { f.capital.currency = e.target.value as "KRW" | "USD" })}><option value="KRW">원 (KRW)</option><option value="USD">달러 (USD)</option></select></Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="월 적립금 (없으면 0)" error={err("capital.monthly_contribution")}>
                <input className={inputClass} inputMode="numeric" value={form.capital.monthly_contribution.toLocaleString("ko-KR")} onChange={(e) => { const v = Number(e.target.value.replace(/\D/g, "")); upd((f) => { f.capital.monthly_contribution = v }) }} />
              </Field>
              <Field label="적립일 (매월)"><input className={inputClass} type="number" min={1} max={28} value={form.capital.contribution_day} onChange={(e) => upd((f) => { f.capital.contribution_day = Number(e.target.value) })} /></Field>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <Field label="투자기간 (년)" error={err("horizon.target_years")} help="1~10년"><input className={inputClass} type="number" min={1} max={10} step={0.5} value={form.horizon.target_years} onChange={(e) => upd((f) => { f.horizon.target_years = Number(e.target.value) })} /></Field>
              <Field label="투자 목적"><select className={inputClass} value={form.horizon.purpose} onChange={(e) => upd((f) => { f.horizon.purpose = e.target.value as Form["horizon"]["purpose"] })}>{(opt?.purpose ?? ["wealth_growth", "income", "capital_preservation", "retirement"]).map((p) => <option key={p} value={p}>{ko(p)}</option>)}</select></Field>
              <Field label="백테스트 기간 (년)" error={err("horizon.backtest_years")} help="과거 성과를 볼 기간. 기본 3년"><input className={inputClass} type="number" min={1} max={20} step={0.5} value={form.horizon.backtest_years} onChange={(e) => upd((f) => { f.horizon.backtest_years = Number(e.target.value) })} /></Field>
            </div>
            <div className="grid grid-cols-4 gap-3">
              <Field label="연령대"><select className={inputClass} value={form.profile.age_band} onChange={(e) => upd((f) => { f.profile.age_band = e.target.value as Form["profile"]["age_band"] })}>{(opt?.age_band ?? ["20s", "30s", "40s", "50s", "60s+"]).map((p) => <option key={p} value={p}>{ko(p)}</option>)}</select></Field>
              <Field label="투자 경험" help={form.profile.investment_experience === "none" ? "경험이 없으면 낙폭 맞춤안 목표를 10% 더 보수적으로 잡습니다 (허용 낙폭 판정은 입력값 그대로)" : undefined}><select className={inputClass} value={form.profile.investment_experience} onChange={(e) => upd((f) => { f.profile.investment_experience = e.target.value as Form["profile"]["investment_experience"] })}>{(opt?.investment_experience ?? ["none", "beginner", "intermediate", "advanced"]).map((p) => <option key={p} value={p}>{ko(p)}</option>)}</select></Field>
              <Field label="금융 지식"><select className={inputClass} value={form.profile.financial_knowledge} onChange={(e) => upd((f) => { f.profile.financial_knowledge = e.target.value as Form["profile"]["financial_knowledge"] })}>{(opt?.financial_knowledge ?? ["basic", "intermediate", "expert"]).map((p) => <option key={p} value={p}>{ko(p)}</option>)}</select></Field>
              <Field label="투자 가능 자산 비율" help={fmt(form.profile.investable_ratio_of_assets, "pct1")}><input className={inputClass} type="range" min={0} max={1} step={0.05} value={form.profile.investable_ratio_of_assets} onChange={(e) => upd((f) => { f.profile.investable_ratio_of_assets = Number(e.target.value) })} /></Field>
            </div>
          </div>
        )}
        {step === 1 && form.diagnosis && (
          <div className="space-y-6">
            <div><h2 className="text-lg font-bold text-slate-950">투자성향 평가</h2><p className="mt-1 text-sm text-slate-500">간이 진단입니다. 금융회사의 적합성 평가를 대신하지 않습니다. 결과는 분석의 위험 기준(허용 최대낙폭·변동성 선호·뷰 신뢰도)에 쓰입니다.</p></div>
            {QUESTIONS.map((q) => (
              <fieldset key={q.id}>
                <legend className="text-sm font-semibold text-slate-800">{q.question}</legend>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  {q.options.map((o) => (
                    <Chip key={o.label} active={form.diagnosis!.answers[q.id] === o.score} onClick={() => upd((f) => {
                      f.diagnosis!.answers[q.id] = o.score
                      if ("loss" in o) f.risk.max_drawdown_tolerance = o.loss
                      if ("reaction" in o) f.risk.loss_reaction = o.reaction
                      const t = computeTendency(f.diagnosis!.answers)
                      f.diagnosis!.final_tendency = t
                      f.risk.risk_tolerance = toRiskTolerance(t)
                    })}>{o.label}</Chip>
                  ))}
                </div>
              </fieldset>
            ))}
            {err("diagnosis") && <p className="text-xs font-medium text-red-600">{err("diagnosis")}</p>}
            <p className="text-xs text-slate-500">손실 시 대응을 「대부분 매도」로 고르면 낙폭 맞춤안(현금을 섞어 과거 낙폭을 목표 안에 맞춘 구성)의 목표를 20% 더 보수적으로 잡습니다. 허용 낙폭 판정과 표시는 입력한 값 그대로입니다. 지금 선택: 손실 시 {ko(form.risk.loss_reaction)}.</p>
            <div className="rounded-xl bg-slate-50 p-4">
              <p className="text-xs font-bold text-slate-400">진단 결과</p>
              <p className="mt-1 font-bold text-slate-900">{computed} <span className="text-sm font-medium text-slate-500">({ko(toRiskTolerance(computed))})</span></p>
              <p className="mt-1 text-xs text-slate-500">{TENDENCY_HELP[computed]}</p>
            </div>
            <Field label="최종 투자성향 (진단과 다르게 선택할 수 있습니다)" error={err("tendency")}>
              <div className="grid grid-cols-5 gap-2">
                {TENDENCIES.map((t) => <Chip key={t} active={form.diagnosis!.final_tendency === t} onClick={() => { upd((f) => { f.diagnosis!.final_tendency = t; f.risk.risk_tolerance = toRiskTolerance(t) }); setOverrideOk(false) }}>{t}</Chip>)}
              </div>
            </Field>
            {form.diagnosis.final_tendency !== computed && (
              <Alert title="진단 결과와 다른 성향을 선택했습니다" tone="warning">
                진단은 {computed}, 선택은 {form.diagnosis.final_tendency}입니다. {TENDENCY_HELP[form.diagnosis.final_tendency]}
                <label className="mt-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={overrideOk} onChange={(e) => setOverrideOk(e.target.checked)} />차이를 확인했습니다</label>
              </Alert>
            )}
            <div className="grid grid-cols-3 gap-3">
              <Field label="손실 감내 수준 (최대낙폭)" error={err("risk.max_drawdown_tolerance")} help={fmt(form.risk.max_drawdown_tolerance, "pct1")}><input className={inputClass} type="range" min={0.05} max={0.6} step={0.01} value={form.risk.max_drawdown_tolerance} onChange={(e) => upd((f) => { f.risk.max_drawdown_tolerance = Number(e.target.value) })} /></Field>
              <Field label="목표 연수익률" help={fmt(form.risk.target_annual_return, "pct1")}><input className={inputClass} type="range" min={0} max={0.3} step={0.01} value={form.risk.target_annual_return} onChange={(e) => upd((f) => { f.risk.target_annual_return = Number(e.target.value) })} /></Field>
              <Field label="비교지수"><select className={inputClass} value={form.risk.benchmark} onChange={(e) => upd((f) => { f.risk.benchmark = e.target.value })}>{bench.map((b) => <option key={b} value={b}>{b}</option>)}</select></Field>
            </div>
          </div>
        )}
        {step === 2 && (
          <div className="space-y-6">
            <div><h2 className="text-lg font-bold text-slate-950">종목 범위와 제약</h2><p className="mt-1 text-sm text-slate-500">제약은 분석에서 반드시 지키는 조건(하드 제약)입니다. 완화하지 않고 그대로 검증합니다.</p></div>
            <Field label="투자 유니버스" error={err("constraints.universe")}>
              <div className="flex gap-2">{(opt?.universes ?? ["SP500", "NASDAQ100", "KOSPI200"]).map((u) => <Chip key={u} active={form.constraints.universe.includes(u)} onClick={() => upd((f) => { f.constraints.universe = f.constraints.universe.includes(u) ? f.constraints.universe.filter((x) => x !== u) : [...f.constraints.universe, u] })}>{ko(u)}</Chip>)}</div>
            </Field>
            <Field label="종목 수 (최소 / 목표 / 최대)" error={err("constraints.num_holdings")}>
              <div className="grid grid-cols-3 gap-3">
                {(["min", "target", "max"] as const).map((k) => <input key={k} className={inputClass} type="number" min={1} value={form.constraints.num_holdings[k]} onChange={(e) => upd((f) => { f.constraints.num_holdings[k] = Number(e.target.value) })} />)}
              </div>
            </Field>
            <div className="grid grid-cols-3 gap-3">
              <Field label="종목당 상한" error={err("constraints.max_weight_per_stock")} help={fmt(form.constraints.max_weight_per_stock, "pct1")}><input className={inputClass} type="range" min={0.05} max={1} step={0.01} value={form.constraints.max_weight_per_stock} onChange={(e) => upd((f) => { f.constraints.max_weight_per_stock = Number(e.target.value) })} /></Field>
              <Field label="섹터당 상한" error={err("constraints.max_weight_per_sector")} help={fmt(form.constraints.max_weight_per_sector, "pct1")}><input className={inputClass} type="range" min={0.1} max={1} step={0.05} value={form.constraints.max_weight_per_sector} onChange={(e) => upd((f) => { f.constraints.max_weight_per_sector = Number(e.target.value) })} /></Field>
              <Field label="최소 현금 비율" help={fmt(form.constraints.min_cash_ratio, "pct1")}><input className={inputClass} type="range" min={0} max={0.5} step={0.05} value={form.constraints.min_cash_ratio} onChange={(e) => upd((f) => { f.constraints.min_cash_ratio = Number(e.target.value) })} /></Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="제외 종목 (티커, 쉼표로 구분)" error={err("constraints.exclude_tickers")} help="예: TSLA, 005930.KS">
                <input className={inputClass} value={excludeText} onChange={(e) => { setExcludeText(e.target.value); upd((f) => { f.constraints.exclude_tickers = e.target.value.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean) }) }} />
              </Field>
              <Field label="필수 포함 종목 (티커, 쉼표로 구분)">
                <input className={inputClass} value={includeText} onChange={(e) => { setIncludeText(e.target.value); upd((f) => { f.constraints.must_include_tickers = e.target.value.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean) }) }} />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="제외 테마 (영문, 쉼표로 구분)" help="예: tobacco, gambling, weapons. 비우면 제외 없음. 분석 모델이 이 테마에 해당하는 산업·키워드를 걸러 냅니다">
                <input className={inputClass} value={themesText} onChange={(e) => { setThemesText(e.target.value); upd((f) => { f.constraints.exclude_themes = e.target.value.split(",").map((s) => s.trim().toLowerCase()).filter(Boolean) }) }} />
              </Field>
              <Field label="제외 섹터 (쉼표로 구분)" help="GICS 섹터 이름. 예: 금융, 에너지">
                <input className={inputClass} value={sectorsText} onChange={(e) => { setSectorsText(e.target.value); upd((f) => { f.constraints.exclude_sectors = e.target.value.split(",").map((s) => s.trim()).filter(Boolean) }) }} />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="최소 시가총액 (십억 USD, 0 = 제한 없음)" help={form.constraints.min_market_cap_usd ? `${(form.constraints.min_market_cap_usd / 1e9).toLocaleString("ko-KR")}B USD 이상인 종목만 후보` : "제한 없음"}>
                <input className={inputClass} type="number" min={0} step={0.5} value={(form.constraints.min_market_cap_usd ?? 0) / 1e9} onChange={(e) => upd((f) => { f.constraints.min_market_cap_usd = Math.round(Number(e.target.value) * 1e9) })} />
              </Field>
              <Field label="최소 일평균 거래대금 (백만 USD, 0 = 제한 없음)" help={form.constraints.min_avg_daily_volume_usd ? `일 ${(form.constraints.min_avg_daily_volume_usd / 1e6).toLocaleString("ko-KR")}M USD 이상` : "제한 없음"}>
                <input className={inputClass} type="number" min={0} step={1} value={(form.constraints.min_avg_daily_volume_usd ?? 0) / 1e6} onChange={(e) => upd((f) => { f.constraints.min_avg_daily_volume_usd = Math.round(Number(e.target.value) * 1e6) })} />
              </Field>
            </div>
            <Field label="리밸런싱 (간격 × 단위, 0 이면 매수 후 보유)">
              <div className="grid grid-cols-[120px_1fr] gap-3">
                <input className={inputClass} type="number" min={0} value={form.constraints.rebalance.count} onChange={(e) => upd((f) => { f.constraints.rebalance.count = Number(e.target.value) })} />
                <select className={inputClass} value={form.constraints.rebalance.unit} onChange={(e) => upd((f) => { f.constraints.rebalance.unit = e.target.value as Form["constraints"]["rebalance"]["unit"] })}>{(opt?.rebalance_units ?? ["2w", "1m", "1q", "6m", "1y"]).map((u) => <option key={u} value={u}>{ko(u)}</option>)}</select>
              </div>
            </Field>
            <Alert title="지원 범위" tone="info">주식만 후보가 됩니다(ETF 후보 선정은 아직 지원하지 않음). 레버리지·공매도는 지원하지 않습니다.</Alert>
          </div>
        )}
        {step === 3 && (
          <div className="space-y-6">
            <div><h2 className="text-lg font-bold text-slate-950">전략 선호</h2><p className="mt-1 text-sm text-slate-500">종목을 고르는 정량 기준과 비중 방식입니다. 분석 요청 때 아이디어에 맞춰 바꿀 수 있고, 분석 모델이 확인 질문을 할 수 있습니다.</p></div>
            <Field label="선정 기준 (템플릿)">
              <div className="grid grid-cols-5 gap-2">{(opt?.templates ?? ["momentum", "low_volatility", "low_per", "quality", "high_dividend"]).map((t) => <Chip key={t} active={form.strategy_preference.template === t} onClick={() => upd((f) => { f.strategy_preference.template = t })}>{ko(t)}</Chip>)}</div>
            </Field>
            <Field label="기준 비중 방식">
              <div className="grid grid-cols-4 gap-2">{(opt?.weightings ?? ["equal_weight", "market_cap", "inverse_volatility", "min_variance"]).map((w) => <Chip key={w} active={form.strategy_preference.baseline_weighting === w} onClick={() => upd((f) => { f.strategy_preference.baseline_weighting = w })}>{ko(w)}</Chip>)}</div>
            </Field>
            <label className="flex items-center gap-3 rounded-xl border border-slate-200 p-4 text-sm">
              <input type="checkbox" checked={form.strategy_preference.use_news_tilt} onChange={(e) => upd((f) => { f.strategy_preference.use_news_tilt = e.target.checked })} />
              <span><span className="font-semibold text-slate-800">뉴스 근거 뷰 반영</span><span className="block text-xs text-slate-500">구성일 직전 2주 뉴스 헤드라인으로 만든 투자 의견을 Black-Litterman 으로 기준 비중에 조금(종목당 상한의 1/3 이내) 반영합니다. 뉴스가 부족한 날은 기준 비중을 그대로 씁니다.</span></span>
            </label>
            <Field label="메모 (선택)"><textarea className={`${inputClass} min-h-20`} value={form.diagnosis?.memo ?? ""} onChange={(e) => upd((f) => { if (f.diagnosis) f.diagnosis.memo = e.target.value })} placeholder="선호나 참고 사항. 검증되는 수치 제약으로는 쓰이지 않습니다." /></Field>
            <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-700">
              <p className="font-semibold text-slate-800">저장 요약</p>
              <p className="mt-1">{form.capital.currency === "KRW" ? krw(form.capital.initial_amount) : fmt(form.capital.initial_amount, "usd")} · {form.horizon.target_years}년 · {form.diagnosis?.final_tendency} · 손실 감내 {fmt(form.risk.max_drawdown_tolerance, "pct1")} · {form.constraints.universe.map(ko).join("/")} · {ko(form.strategy_preference.template)}/{ko(form.strategy_preference.baseline_weighting)}</p>
            </div>
            {saveError && <Alert title="저장 실패" tone="error">{saveError}</Alert>}
            {Object.keys(errors).length > 0 && <Alert title="확인이 필요한 항목 (빨간 단계 탭을 눌러 고칠 수 있습니다)" tone="warning"><ul className="list-disc pl-5">{Object.entries(errors).map(([k, v]) => <li key={k}>{v.includes(":") ? v : `${FIELD_KO[k] ?? k}: ${v}`}</li>)}</ul></Alert>}
          </div>
        )}
        <div className="mt-8 flex items-center justify-between border-t border-slate-100 pt-5">
          <div className="flex gap-2">{!setup && <Button variant="ghost" onClick={() => navigate({ page: "profile" })}>취소</Button>}{step > 0 && <Button variant="secondary" onClick={() => setStep((s) => s - 1)}>이전</Button>}</div>
          <div className="flex items-center gap-3">
            {Object.keys(errors).length > 0 && step < 3 && <Badge tone="red">{Object.values(errors)[0]}</Badge>}
            {step < STEPS.length - 1 ? <Button onClick={next}>다음</Button> : <Button onClick={submit} disabled={saving}><Check className="size-4" />{saving ? "저장 중…" : "저장"}</Button>}
          </div>
        </div>
      </Card>
    </div>
  )
}
