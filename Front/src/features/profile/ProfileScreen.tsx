import { useEffect, useMemo, useState } from "react"
import { Check, LogOut, MessagesSquare } from "lucide-react"
import { useProfile, useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { ApiError, errorMessage } from "../../api/client"
import type { Options, ProfileFields, ProfileView, Tendency } from "../../api/types"
import { useResource } from "../../state/useResource"
import { clearLegacy, loadLegacyProfile, loadUi, saveUi } from "../../state/uiStorage"
import { Alert, Badge, Button, Chip, ErrorState, Field, inputClass, Loading } from "../../ui"
import { ko } from "../../lib/format"
import { QUESTIONS, TENDENCIES, TENDENCY_HELP, computeTendency, toRiskTolerance } from "./diagnosis"
import { InfoField, InfoTip, NumberInput, PercentSlider, SectorPicker, TagInput } from "./inputs"
import { StrategyFields } from "./StrategyFields"
import { strategySummary } from "./strategyInfo"
import { ASSET_KO, UNIVERSE_HELP, benchName, listText, money, monthlyText, pctText, rebalanceText, usdFloor, yearsText } from "./format"
import { Part, PartDisclosure } from "./parts"
import { VersionHistory } from "./history"
import { tendencyLabel } from "../../lib/tendency"
import { proposedRulesOf } from "../../api/proposed"
import { MockTag } from "../report/proposedView"
import { StockPicker, useStockNames } from "./stocks"
import { StrategyRecommendation, asPref, useRecommendation } from "./StrategyRecommend"
import { DEFAULT_FORM } from "./defaults"
import { validateProfile } from "./validate"

type Form = ProfileFields

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
  const c = p.constraints
  const sp = strategySummary(p.strategy_preference)
  const name = useStockNames([...c.exclude_tickers, ...c.must_include_tickers])  // 제안 기능: 회사명 (목업에서만)
  const tickers = (xs: string[]) => (name ? <>{listText(xs.map(name))}{xs.length > 0 && <MockTag />}</> : listText(xs))
  const parts: { title: string; rows: [string, React.ReactNode][] }[] = [
    { title: "기본 조건", rows: [
      ["처음 투자할 금액", money(p.capital.initial_amount, p.capital.currency)], ["매월 추가 투자금", monthlyText(p.capital)],
      ["앞으로 투자할 기간", yearsText(p.horizon.target_years)], ["과거 성과를 확인할 기간", yearsText(p.horizon.backtest_years)],
      ["투자 목적", ko(p.horizon.purpose)],
      ["나에 대한 참고 정보", `${ko(p.profile.age_band)} · 투자 경험 ${ko(p.profile.investment_experience)} · 금융 지식 ${ko(p.profile.financial_knowledge)} · 자산 중 ${pctText(p.profile.investable_ratio_of_assets)}`],
    ] },
    { title: "투자성향", rows: [
      ["투자성향", `${tendencyLabel({ final: p.diagnosis?.final_tendency, code: p.risk.risk_tolerance })}${p.risk_type_overridden ? " · 진단과 다르게 선택" : ""}`],
      ["손실 감내 수준", pctText(p.risk.max_drawdown_tolerance)], ["목표 연수익률", pctText(p.risk.target_annual_return)], ["비교지수", benchName(p.risk.benchmark)],
    ] },
    { title: "종목 범위·제약", rows: [
      ["투자 대상 지수", c.universe.map(ko).join(", ")], ["종목 수", `목표 ${c.num_holdings.target}개 (최소 ${c.num_holdings.min} ~ 최대 ${c.num_holdings.max})`],
      ["비중 상한", `종목당 최대 ${pctText(c.max_weight_per_stock)} · 섹터당 최대 ${pctText(c.max_weight_per_sector)}`], ["최소 현금 비율", pctText(c.min_cash_ratio)],
      ["리밸런싱", rebalanceText(c.rebalance)], ["자산 종류", (c.asset_types ?? ["stock"]).map((a) => ASSET_KO[a] ?? a).join(", ")],
      ["제외 종목", tickers(c.exclude_tickers)], ["반드시 포함할 종목", tickers(c.must_include_tickers)],
      ["제외 섹터", listText(c.exclude_sectors)], ["제외 테마", listText(c.exclude_themes)],
      ["최소 시가총액", usdFloor(c.min_market_cap_usd)], ["최소 일평균 거래대금", usdFloor(c.min_avg_daily_volume_usd)],
    ] },
    { title: "투자 전략", rows: [
      ["투자 전략", sp],
      ...(p.diagnosis?.memo ? [["메모", p.diagnosis.memo] as [string, React.ReactNode]] : []),
    ] },
  ]
  return (
    <div className="mx-auto max-w-4xl space-y-8">
      {/* 공통 PageHeader 는 제목·버튼을 늘 한 줄에 두어 좁은 화면에서 제목이 글자 단위로 꺾인다. 이 화면만 좁으면 버튼을 아래로 내린다. */}
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between sm:gap-8">
        <div className="min-w-0 max-w-3xl">
          <p className="mb-2 text-xs font-bold tracking-widest text-blue-700">내 투자조건</p>
          <h1 className="text-3xl font-bold tracking-tight text-slate-950">저장된 기본 투자조건</h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">버전 {view.current_version} · 저장 {p.created_at.slice(0, 16).replace("T", " ")}. 수정하면 새 버전이 추가되고 과거 리포트는 바뀌지 않습니다.</p>
        </div>
        <div className="flex shrink-0 gap-2"><Button variant="secondary" onClick={() => navigate({ page: "home" })}>새 분석 시작</Button><Button onClick={() => navigate({ page: "profile", mode: "edit" })}>수정</Button></div>
      </header>
      {parts.map((part) => (
        <Part key={part.title} title={part.title}>
          <dl className="grid grid-cols-1 gap-x-8 gap-y-4 text-sm sm:grid-cols-2">
            {part.rows.map(([k, v]) => <div key={k} className="min-w-0"><dt className="text-xs font-semibold text-slate-500">{k}</dt><dd className="mt-1 break-words font-semibold text-slate-900">{v}</dd></div>)}
          </dl>
        </Part>
      ))}
      <VersionHistory view={view} />
    </div>
  )
}

const STEPS = ["기본 조건", "투자성향", "종목 범위·제약", "투자 전략"]
const STEP_KEYS = [["capital.", "horizon.", "profile."], ["risk.", "diagnosis", "tendency"], ["constraints."], ["strategy_preference."]]
const FIELD_KO: Record<string, string> = { "capital.initial_amount": "투자 금액", "capital.monthly_contribution": "매월 추가 투자금", "horizon.target_years": "투자기간", "horizon.backtest_years": "백테스트 기간", "constraints.num_holdings": "종목 수", "constraints.max_weight_per_stock": "종목당 상한", "constraints.max_weight_per_sector": "섹터당 상한", "constraints.universe": "투자 대상 지수", "constraints.exclude_tickers": "제외 종목", diagnosis: "투자성향 진단", tendency: "투자성향" }
const ADVANCED_KEYS = ["constraints.max_weight_per_stock", "constraints.max_weight_per_sector", "constraints.min_cash_ratio", "constraints.rebalance", "constraints.min_market_cap_usd", "constraints.min_avg_daily_volume_usd"]
const LIST_KEYS = ["constraints.exclude_tickers", "constraints.must_include_tickers", "constraints.exclude_sectors", "constraints.exclude_themes"]
const hasKey = (errors: Record<string, string>, keys: string[]) => Object.keys(errors).some((k) => keys.some((p) => k.startsWith(p)))


const TICKER_INFO = <>회사 이름이 아니라 <b>종목 코드(티커)</b>로 입력합니다. 미국: TSLA(테슬라), AAPL(애플) · 한국: 6자리 종목코드 005930(삼성전자) 또는 005930.KS. 회사 이름으로 찾는 기능은 아직 없습니다.</>

function ProfileWizard({ initial, setup, onSaved }: { initial: Form | null; setup: boolean; onSaved: (v: ProfileView) => void }) {
  const svc = useService()
  const options = useResource(() => svc.options(), [svc])
  const chatDraft = useMemo(() => (initial ? null : loadUi().profileDraft ?? null), [initial])  // 대화형 설정에서 넘어온 초안 (처음 설정만)
  const legacy = useMemo(() => (initial || chatDraft ? null : loadLegacyProfile()), [initial, chatDraft])
  const [form, setForm] = useState<Form>(() => (initial ? structuredClone(initial) : chatDraft ? structuredClone(chatDraft) : { ...structuredClone(DEFAULT_FORM), ...(legacy ? fromLegacy(legacy) : {}) }))
  const [step, setStep] = useState(0)
  const chatDone = useMemo(() => !!chatDraft && loadUi().profileChat?.state === "review", [chatDraft])  // 대화를 끝까지 하고 넘어왔는지
  const resumable = useMemo(() => !!loadUi().profileChat, [])  // 폼으로 넘어오기 전의 대화가 있으면 「대화로 이어서 하기」
  const [reached, setReached] = useState(initial || chatDone ? STEPS.length - 1 : 0)  // 지금까지 들어가 본 가장 먼 단계 (수정·대화를 끝낸 초안이면 모든 단계 완료, 대화 중간에 넘어왔으면 처음부터)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState("")
  const [overrideOk, setOverrideOk] = useState(initial?.risk_type_overridden ?? chatDraft?.risk_type_overridden ?? false)
  const c0 = form.constraints
  const [openMore, setOpenMore] = useState(false)
  const [openLists, setOpenLists] = useState(c0.exclude_tickers.length + c0.must_include_tickers.length + c0.exclude_sectors.length + (c0.exclude_themes ?? []).length > 0)
  const [openAdvanced, setOpenAdvanced] = useState(false)
  const allowZero = !!proposedRulesOf(options.data)?.allow_zero_initial_amount  // 제안 규칙: 초기 투자금 0원 + 매월 추가 투자 (목업에서만, 지금 서버는 0보다 커야 함)
  const rec = useRecommendation(form.diagnosis?.final_tendency)
  const computed = useMemo(() => (Object.keys(form.diagnosis?.answers ?? {}).length ? computeTendency(form.diagnosis!.answers) : form.diagnosis?.computed_tendency ?? "위험중립형"), [form.diagnosis])

  useEffect(() => { setForm((f) => ({ ...f, diagnosis: { ...(f.diagnosis ?? DEFAULT_FORM.diagnosis!), computed_tendency: computed }, risk_type_computed: toRiskTolerance(computed) })) }, [computed])

  const upd = (patch: (f: Form) => void) => setForm((f) => { const n = structuredClone(f); patch(n); return n })
  const err = (k: string) => errors[k]

  const localCheck = (): Record<string, string> => validateProfile(form, { allowZero })

  /** i 단계를 넘어가기 위한 검사 (기존 「다음」 규칙 그대로). */
  const stepErrors = (i: number): Record<string, string> => {
    const e = localCheck()
    const mine = Object.fromEntries(Object.entries(e).filter(([k]) => STEP_KEYS[i].some((p) => k.startsWith(p))))
    if (i === 1 && form.diagnosis && Object.keys(form.diagnosis.answers).length < QUESTIONS.length) mine["diagnosis"] = "필수 질문에 모두 답해 주세요"
    if (i === 1 && form.diagnosis && form.diagnosis.final_tendency !== computed && !overrideOk) mine["tendency"] = "진단 결과와 다른 성향을 선택하려면 차이를 확인해 주세요"
    return mine
  }

  /** 들어가 본 단계는 바로 이동. 그보다 뒤 단계는 앞 단계를 차례로 검사해 막히는 단계에서 멈춘다. */
  const goTo = (target: number) => {
    if (target <= reached) { setStep(target); return }
    for (let i = 0; i < target; i++) {
      const mine = stepErrors(i)
      if (Object.keys(mine).length) { setErrors(mine); setStep(i); setReached((r) => Math.max(r, i)); return }
    }
    setErrors({})
    setStep(target)
    setReached(target)
  }
  /** 「다음」은 지금 단계를 검사하고 넘어간다 (수정 화면에서도 기존 규칙 그대로). */
  const next = () => {
    const mine = stepErrors(step)
    setErrors(mine)
    if (Object.keys(mine).length) return
    setStep(step + 1)
    setReached((r) => Math.max(r, step + 1))
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
      if (chatDraft || loadUi().profileChat) saveUi({ profileDraft: null, profileChat: null })
      onSaved(v)
    } catch (ex) {
      if (ex instanceof ApiError && ex.fields) { setErrors(ex.fields); setSaveError("입력값에 오류가 있어 저장하지 못했습니다. 표시된 항목을 확인해 주세요.") }
      else setSaveError(`저장하지 못했습니다: ${errorMessage(ex)} 입력값은 유지됩니다.`)
    } finally { setSaving(false) }
  }

  const opt: Options | null = options.data
  const bench = opt?.benchmarks ?? ["SPY", "QQQ", "069500.KS"]
  const cur = form.capital.currency
  const c = form.constraints
  const sp = strategySummary(form.strategy_preference)
  const listCount = c.exclude_tickers.length + c.must_include_tickers.length + c.exclude_sectors.length + (c.exclude_themes ?? []).length
  const upperTicker = (s: string) => s.trim().toUpperCase()
  return (
    <div className="mx-auto max-w-4xl">
      {/* 저장된 투자조건 화면과 같은 머리: 좁으면 버튼을 제목 아래로. 입력을 그만두는 「저장하지 않고 나가기」는 (수정·처음 설정 공통; 수정은 저장된 투자조건, 처음 설정은 리포트 목록으로: 프로필이 없으면 홈 등은 처음 설정으로 되돌아오므로) 단계 이동(아래 이전·다음)과 떨어진 위쪽 오른쪽에 둔다. */}
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between sm:gap-8">
        <div className="min-w-0 max-w-3xl">
          <p className="mb-2 text-xs font-bold tracking-widest text-blue-700">{setup ? "처음 설정" : "투자조건 수정"}</p>
          <h1 className="text-3xl font-bold tracking-tight text-slate-950">{setup ? "기본 투자조건을 알려주세요." : "저장된 투자조건을 수정합니다."}</h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">금액과 기간, 투자성향, 종목 범위, 투자 전략을 설정합니다. 분석을 요청할 때 아이디어에 맞춰 일부를 바꿀 수 있습니다.</p>
        </div>
        <div className="flex shrink-0 gap-2">
          {setup && svc.startProfileChat && <Button variant="secondary" onClick={() => navigate({ page: "profile", mode: "chat" })}><MessagesSquare className="size-4" aria-hidden />{resumable ? "대화로 이어서 하기" : "대화로 설정하기"}<MockTag /></Button>}
          <Button variant="neutral" onClick={() => navigate(setup ? { page: "reports" } : { page: "profile" })}><LogOut className="size-4" aria-hidden />저장하지 않고 나가기</Button>
        </div>
      </header>
      {legacy && setup && <div className="mt-6"><Alert title="이전 브라우저 저장 조건을 불러왔습니다" tone="info">예전 앱에 저장돼 있던 투자조건으로 미리 채웠습니다. 확인 후 저장하면 서버에 기록됩니다.</Alert></div>}
      {chatDraft && setup && <div className="mt-6"><Alert title="대화에서 답한 내용으로 채웠습니다" tone="info">나머지 항목을 확인하고 마지막 단계에서 저장하세요.</Alert></div>}
      <nav aria-label="설정 단계" className="my-8">
        <ol className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {STEPS.map((label, i) => {
            const n = Object.keys(errors).filter((k) => STEP_KEYS[i].some((p) => k.startsWith(p))).length
            const now = step === i
            const done = !now && n === 0 && (i < reached || (!setup && i <= reached))
            const state = now ? "현재 단계" : n > 0 ? `확인 필요 ${n}건` : done ? "완료" : i <= reached ? "작성 중" : "아직 시작 전"
            return (
              <li key={label}>
                <button type="button" onClick={() => goTo(i)} aria-current={now ? "step" : undefined} aria-label={`${i + 1}단계 ${label} (${state})`}
                  className={`w-full rounded-xl border p-3 text-left transition focus:outline-none focus:ring-2 focus:ring-blue-500 ${now ? "border-blue-400 bg-blue-50 ring-1 ring-blue-200" : n > 0 ? "border-red-300 bg-red-50 hover:bg-red-100" : done ? "border-slate-200 bg-white hover:border-blue-200 hover:bg-blue-50/40" : "border-dashed border-slate-200 bg-white text-slate-400 hover:bg-slate-50"}`}>
                  <span className="flex items-center justify-between">
                    <span className={`text-xs font-bold ${now ? "text-blue-700" : "text-slate-400"}`}>0{i + 1}</span>
                    {n > 0 ? <span className="rounded-full bg-red-600 px-1.5 text-[10px] font-bold text-white">{n}</span> : done ? <Check className="size-4 text-emerald-600" aria-hidden="true" /> : null}
                  </span>
                  <span className={`mt-1 block text-sm font-semibold ${now || done || n > 0 ? "text-slate-800" : "text-slate-500"}`}>{label}</span>
                  <span className={`mt-0.5 block text-[11px] ${now ? "text-blue-700" : n > 0 ? "text-red-600" : "text-slate-400"}`}>{state}</span>
                </button>
              </li>
            )
          })}
        </ol>
      </nav>
      <div>
        {step === 0 && (
          <div className="space-y-8">
            <h2 className="text-lg font-bold text-slate-950">기본 조건</h2>
            <Part title="투자금과 목적" tag="필수" info="분석의 계산 조건으로 쓰입니다. 계산은 USD 로 하고, 원화는 분석 기준일 환율로 환산합니다.">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_140px]">
                <InfoField label="처음 투자할 금액" error={err("capital.initial_amount")} help={allowZero && form.capital.initial_amount === 0 ? <>0원 · 처음 투자금 없이 매월 추가 투자금으로 시작합니다<MockTag /></> : money(form.capital.initial_amount, cur)} info={allowZero ? "0원으로 두면 처음 투자금 없이 매월 추가 투자금으로만 투자합니다. 이때는 매월 추가 투자금을 꼭 정해야 합니다. (목업 화면에서만 가능 — 지금 서버는 0보다 큰 금액만 받습니다)" : "0원은 입력할 수 없습니다. 처음 투자금 없이 매월 적립만 하는 방식은 아직 지원하지 않습니다."}>
                  <input className={inputClass} inputMode="numeric" value={form.capital.initial_amount.toLocaleString("ko-KR")} onChange={(e) => { const v = Number(e.target.value.replace(/\D/g, "")); upd((f) => { f.capital.initial_amount = v }) }} />
                </InfoField>
                <Field label="통화"><select className={inputClass} value={form.capital.currency} onChange={(e) => upd((f) => { f.capital.currency = e.target.value as "KRW" | "USD" })}><option value="KRW">원 (KRW)</option><option value="USD">달러 (USD)</option></select></Field>
              </div>
              <div className="sm:w-1/2">
                <Field label="투자 목적"><select className={inputClass} value={form.horizon.purpose} onChange={(e) => upd((f) => { f.horizon.purpose = e.target.value as Form["horizon"]["purpose"] })}>{(opt?.purpose ?? ["wealth_growth", "income", "capital_preservation", "retirement"]).map((p) => <option key={p} value={p}>{ko(p)}</option>)}</select></Field>
              </div>
            </Part>
            <Part title="기간" tag="필수">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <InfoField label="앞으로 투자할 기간 (년)" error={err("horizon.target_years")} help={`앞으로 ${yearsText(form.horizon.target_years)} 동안 투자하는 것을 기준으로 분석합니다. (1~10년)`} info="분석 결과가 이 기간 단위로 목표 수익률에 닿았는지 점검할 때도 씁니다."><NumberInput min={1} max={10} step={0.5} value={form.horizon.target_years} onChange={(v) => upd((f) => { f.horizon.target_years = v })} /></InfoField>
                <InfoField label="과거 성과를 확인할 기간 (년)" error={err("horizon.backtest_years")} help={`과거 ${yearsText(form.horizon.backtest_years)}의 데이터로 전략을 검증합니다. (1~20년 · 기본 3년)`} info="이 전략을 과거 실제 주가로 운용했다면 어땠을지 계산하는 기간(백테스트 기간)입니다. 앞으로 투자할 기간과는 별개입니다."><NumberInput min={1} max={20} step={0.5} value={form.horizon.backtest_years} onChange={(v) => upd((f) => { f.horizon.backtest_years = v })} /></InfoField>
              </div>
              {!err("horizon.target_years") && !err("horizon.backtest_years") && form.horizon.backtest_years > 0 && form.horizon.backtest_years < form.horizon.target_years && (
                <p className="rounded-xl bg-slate-100 px-3 py-2 text-xs font-medium text-slate-700">투자기간 {yearsText(form.horizon.target_years)} 중 과거 검증은 {yearsText(form.horizon.backtest_years)}으로 설정되어 있습니다</p>
              )}
            </Part>
            <Part title="매월 추가 투자" tag="선택" info={<>모의투자를 진행할 때 매월 추가로 투자할 금액을 설정합니다. 과거 성과 계산(백테스트)에서도 같은 금액을 매월 적립일에 추가로 투자한 것으로 계산하며, 모의투자를 시작할 때 이 금액이 기본으로 채워지고 그때 바꿀 수 있습니다. 투자 비중을 다시 맞추는 <b>리밸런싱</b>과는 관계없는 금액입니다. 없으면 0으로 두세요.</>}>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Field label="매월 추가 투자금" error={err("capital.monthly_contribution")} help={form.capital.monthly_contribution ? `매월 ${money(form.capital.monthly_contribution, cur)}` : "0 = 추가 투자 없음"}>
                  <input className={inputClass} inputMode="numeric" value={form.capital.monthly_contribution.toLocaleString("ko-KR")} onChange={(e) => { const v = Number(e.target.value.replace(/\D/g, "")); upd((f) => { f.capital.monthly_contribution = v }) }} />
                </Field>
                <Field label="추가 투자일 (매월)" help="1~28일"><NumberInput className={inputClass} min={1} max={28} value={form.capital.contribution_day} onChange={(v) => upd((f) => { f.capital.contribution_day = v })} /></Field>
              </div>
              {allowZero && form.capital.initial_amount === 0 && <ZeroStartSchedule capital={form.capital} years={form.horizon.target_years} />}
            </Part>
            <PartDisclosure title="나에 대한 참고 정보" tag="선택" summary={<span className="hidden sm:inline">{ko(form.profile.age_band)} · 경험 {ko(form.profile.investment_experience)} · 지식 {ko(form.profile.financial_knowledge)} · 자산 중 {pctText(form.profile.investable_ratio_of_assets)}</span>} open={openMore || hasKey(errors, ["profile."])} onToggle={setOpenMore}>
              <p className="mb-4 flex items-center gap-1 text-xs text-slate-500">기본값 그대로 두어도 분석할 수 있습니다.<InfoTip label="나에 대한 참고 정보">분석 모델이 설명과 해석을 맞출 때 참고하는 정보입니다. 이 가운데 투자 경험만 계산에 쓰입니다 (「없음」이면 낙폭 맞춤안 목표를 10% 더 보수적으로 잡습니다).</InfoTip></p>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <Field label="연령대"><select className={inputClass} value={form.profile.age_band} onChange={(e) => upd((f) => { f.profile.age_band = e.target.value as Form["profile"]["age_band"] })}>{(opt?.age_band ?? ["20s", "30s", "40s", "50s", "60s+"]).map((p) => <option key={p} value={p}>{ko(p)}</option>)}</select></Field>
                <Field label="투자 경험" help={form.profile.investment_experience === "none" ? "경험이 없으면 낙폭 맞춤안 목표를 10% 더 보수적으로 잡습니다 (허용 낙폭 판정은 입력값 그대로)" : undefined}><select className={inputClass} value={form.profile.investment_experience} onChange={(e) => upd((f) => { f.profile.investment_experience = e.target.value as Form["profile"]["investment_experience"] })}>{(opt?.investment_experience ?? ["none", "beginner", "intermediate", "advanced"]).map((p) => <option key={p} value={p}>{ko(p)}</option>)}</select></Field>
                <Field label="금융 지식"><select className={inputClass} value={form.profile.financial_knowledge} onChange={(e) => upd((f) => { f.profile.financial_knowledge = e.target.value as Form["profile"]["financial_knowledge"] })}>{(opt?.financial_knowledge ?? ["basic", "intermediate", "expert"]).map((p) => <option key={p} value={p}>{ko(p)}</option>)}</select></Field>
              </div>
              <div className="mt-4"><PercentSlider label="전체 자산 중 이 투자에 쓰는 비율" value={form.profile.investable_ratio_of_assets} min={0} max={1} step={0.05} onChange={(v) => upd((f) => { f.profile.investable_ratio_of_assets = v })} error={err("profile.investable_ratio_of_assets")} /></div>
            </PartDisclosure>
          </div>
        )}
        {step === 1 && form.diagnosis && (
          <div className="space-y-8">
            <div><h2 className="text-lg font-bold text-slate-950">투자성향 평가</h2><p className="mt-1 text-sm text-slate-500">간이 진단입니다. 금융회사의 적합성 평가를 대신하지 않습니다.</p></div>
            <Part title="성향 진단 질문" tag="필수" info="결과는 분석의 위험 기준(허용 최대낙폭·변동성 선호·뉴스 반영 강도)에 쓰입니다. 손실 시 대응을 「대부분 매도」로 고르면 낙폭 맞춤안(현금을 섞어 과거 낙폭을 목표 안에 맞춘 구성)의 목표를 20% 더 보수적으로 잡습니다. 허용 낙폭 판정과 표시는 입력한 값 그대로입니다.">
            {QUESTIONS.map((q) => (
              <fieldset key={q.id}>
                <legend className="text-sm font-semibold text-slate-800">{q.question}</legend>
                <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
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
            <div className="rounded-xl bg-slate-50 p-4">
              <p className="text-xs font-bold text-slate-400">진단 결과</p>
              <p className="mt-1 font-bold text-slate-900">{computed} <span className="text-sm font-medium text-slate-500">({ko(toRiskTolerance(computed))})</span></p>
              <p className="mt-1 text-xs text-slate-500">{TENDENCY_HELP[computed]}</p>
            </div>
            <Field label="최종 투자성향 (진단과 다르게 선택할 수 있습니다)" error={err("tendency")}>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                {TENDENCIES.map((t) => <Chip key={t} active={form.diagnosis!.final_tendency === t} onClick={() => { upd((f) => { f.diagnosis!.final_tendency = t; f.risk.risk_tolerance = toRiskTolerance(t) }); setOverrideOk(false) }}>{t}</Chip>)}
              </div>
            </Field>
            {form.diagnosis.final_tendency !== computed && (
              <Alert title="진단 결과와 다른 성향을 선택했습니다" tone="warning">
                진단은 {computed}, 선택은 {form.diagnosis.final_tendency}입니다. {TENDENCY_HELP[form.diagnosis.final_tendency]}
                <label className="mt-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={overrideOk} onChange={(e) => setOverrideOk(e.target.checked)} />차이를 확인했습니다</label>
              </Alert>
            )}
            </Part>
            <Part title="손실 기준과 목표" tag="필수" info="분석이 끝나면 결과가 이 기준을 지켰는지 점검해 리포트에 보여 줍니다. 목표 수익률을 보장하는 값은 아닙니다.">
              <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
                <PercentSlider label="손실 감내 수준 (최대 하락 폭)" value={form.risk.max_drawdown_tolerance} min={0.05} max={0.6} step={0.01} onChange={(v) => upd((f) => { f.risk.max_drawdown_tolerance = v })} error={err("risk.max_drawdown_tolerance")} info="투자금이 가장 높았던 때보다 이만큼까지 떨어지는 것은 견딜 수 있다는 기준입니다. 첫 번째 질문의 답으로 채워지며, 직접 바꿀 수 있습니다." />
                <PercentSlider label="목표 연수익률" value={form.risk.target_annual_return} min={0} max={0.3} step={0.01} onChange={(v) => upd((f) => { f.risk.target_annual_return = v })} error={err("risk.target_annual_return")} info="1년에 평균 이 정도 수익을 기대한다는 기준입니다." />
              </div>
              <div className="sm:w-1/2">
                <InfoField label="비교지수" error={err("risk.benchmark")} info="내 포트폴리오의 성과를 견주어 볼 시장 지수입니다. 투자금을 나누는 방식과는 관계없습니다."><select className={inputClass} value={form.risk.benchmark} onChange={(e) => upd((f) => { f.risk.benchmark = e.target.value })}>{bench.map((b) => <option key={b} value={b}>{benchName(b)}</option>)}</select></InfoField>
              </div>
            </Part>
          </div>
        )}
        {step === 2 && (
          <div className="space-y-8">
            <div><h2 className="text-lg font-bold text-slate-950">종목 범위와 제약</h2><p className="mt-1 text-sm text-slate-500">여기서 정한 제약은 분석에서 반드시 지키는 조건(하드 제약)입니다. 완화하지 않고 그대로 검증합니다.</p></div>
            <Part title="어떤 시장에서, 몇 종목을 고를까요?" tag="필수">
              <Field label="투자 대상 지수 (여러 개 선택 가능)" error={err("constraints.universe")}>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">{(opt?.universes ?? ["SP500", "NASDAQ100", "KOSPI200"]).map((u) => (
                  <Chip key={u} active={c.universe.includes(u)} onClick={() => upd((f) => { f.constraints.universe = f.constraints.universe.includes(u) ? f.constraints.universe.filter((x) => x !== u) : [...f.constraints.universe, u] })}>
                    <span className="flex items-center justify-between gap-2 font-semibold">{ko(u)}{c.universe.includes(u) && <Check className="size-4 text-blue-700" aria-hidden="true" />}</span>
                    {UNIVERSE_HELP[u] && <span className="mt-0.5 block text-xs text-slate-500">{UNIVERSE_HELP[u]}</span>}
                  </Chip>
                ))}</div>
              </Field>
              <div>
                <p className="mb-2 flex items-center gap-1 text-sm font-semibold text-slate-700">종목 수<InfoTip label="종목 수">목표만큼 고르되, 조건에 맞는 후보가 부족하면 최소~최대 범위 안에서 조정합니다.</InfoTip></p>
                <div className="grid grid-cols-3 gap-3">
                  {([["min", "최소"], ["target", "목표"], ["max", "최대"]] as const).map(([k, l]) => (
                    <label key={k} className="block"><span className="mb-1 block text-xs text-slate-500">{l}</span><NumberInput className={inputClass} min={1} value={c.num_holdings[k]} onChange={(v) => upd((f) => { f.constraints.num_holdings[k] = v })} /></label>
                  ))}
                </div>
                {err("constraints.num_holdings") && <p className="mt-1.5 text-xs font-medium text-red-600">{err("constraints.num_holdings")}</p>}
              </div>
            </Part>
            <PartDisclosure title="빼거나 꼭 넣을 종목·분야" tag="선택" summary={listCount ? `${listCount}개 설정됨` : "설정 없음"} open={openLists || hasKey(errors, LIST_KEYS)} onToggle={setOpenLists}>
              <div className="space-y-5">
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  {svc.searchStocks ? (  // 제안 기능: 회사 이름으로 찾기 (목업에서만)
                    <>
                      <StockPicker label="제외할 종목" values={c.exclude_tickers} error={err("constraints.exclude_tickers")} other={{ label: "반드시 포함할 종목", values: c.must_include_tickers }} onChange={(v) => upd((f) => { f.constraints.exclude_tickers = v })} />
                      <StockPicker label="반드시 포함할 종목" values={c.must_include_tickers} error={err("constraints.must_include_tickers")} other={{ label: "제외할 종목", values: c.exclude_tickers }} onChange={(v) => upd((f) => { f.constraints.must_include_tickers = v })} />
                    </>
                  ) : (
                    <>
                      <TagInput label="제외할 종목" values={c.exclude_tickers} normalize={upperTicker} placeholder="예: TSLA, 005930 · Enter로 추가" info={TICKER_INFO} error={err("constraints.exclude_tickers")} onChange={(v) => upd((f) => { f.constraints.exclude_tickers = v })} />
                      <TagInput label="반드시 포함할 종목" values={c.must_include_tickers} normalize={upperTicker} placeholder="예: AAPL · Enter로 추가" info={TICKER_INFO} error={err("constraints.must_include_tickers")} onChange={(v) => upd((f) => { f.constraints.must_include_tickers = v })} />
                    </>
                  )}
                </div>
                <SectorPicker values={c.exclude_sectors} onChange={(v) => upd((f) => { f.constraints.exclude_sectors = v })} />
                <TagInput label="제외할 테마" values={c.exclude_themes ?? []} normalize={(s) => s.trim().toLowerCase()} placeholder="예: 담배, 도박 · Enter로 추가" error={err("constraints.exclude_themes")} onChange={(v) => upd((f) => { f.constraints.exclude_themes = v })}
                  info="섹터보다 좁은 분야를 뺄 때 씁니다. 적은 표현을 분석 모델(AI)이 산업 분류·키워드 규칙으로 바꿔 해당 기업을 후보에서 뺍니다. 정해진 목록은 없으며, 실제로 빠진 기업은 리포트에서 확인할 수 있습니다." />
              </div>
            </PartDisclosure>
            <PartDisclosure title="세부 제약 조건" tag="고급" summary={<span className="hidden sm:inline">종목당 {pctText(c.max_weight_per_stock)} · 섹터당 {pctText(c.max_weight_per_sector)} · {c.rebalance.count === 0 ? "리밸런싱 없음" : `${c.rebalance.count}×${ko(c.rebalance.unit)}마다 리밸런싱`}</span>} open={openAdvanced || hasKey(errors, ADVANCED_KEYS)} onToggle={setOpenAdvanced}>
              <div className="space-y-6">
                <p className="text-xs text-slate-500">대부분 기본값 그대로 두어도 됩니다.</p>
                <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
                  <PercentSlider label="종목당 상한" value={c.max_weight_per_stock} min={0.05} max={1} step={0.01} onChange={(v) => upd((f) => { f.constraints.max_weight_per_stock = v })} error={err("constraints.max_weight_per_stock")} info="한 종목에 넣을 수 있는 최대 비율" />
                  <PercentSlider label="섹터당 상한" value={c.max_weight_per_sector} min={0.1} max={1} step={0.05} onChange={(v) => upd((f) => { f.constraints.max_weight_per_sector = v })} error={err("constraints.max_weight_per_sector")} info="같은 업종(섹터)에 넣을 수 있는 최대 비율" />
                  <PercentSlider label="최소 현금 비율" value={c.min_cash_ratio} min={0} max={0.5} step={0.05} onChange={(v) => upd((f) => { f.constraints.min_cash_ratio = v })} error={err("constraints.min_cash_ratio")} info="주식에 넣지 않고 현금으로 남길 최소 비율" />
                </div>
                <div>
                  <p className="mb-2 flex items-center gap-1 text-sm font-semibold text-slate-700">리밸런싱 주기 (간격 × 단위)<InfoTip label="리밸런싱 주기">정해진 주기마다 그 시점까지의 자료로 투자 비중을 다시 계산해 맞춥니다. 0이면 처음 산 뒤 그대로 보유합니다. 매월 추가 투자금과는 별개입니다.</InfoTip></p>
                  <div className="grid grid-cols-[120px_1fr] gap-3">
                    <NumberInput className={inputClass} min={0} aria-label="리밸런싱 간격" value={c.rebalance.count} onChange={(v) => upd((f) => { f.constraints.rebalance.count = v })} />
                    <select className={inputClass} aria-label="리밸런싱 단위" value={c.rebalance.unit} onChange={(e) => upd((f) => { f.constraints.rebalance.unit = e.target.value as Form["constraints"]["rebalance"]["unit"] })}>{(opt?.rebalance_units ?? ["2w", "1m", "1q", "6m", "1y"]).map((u) => <option key={u} value={u}>{ko(u)}</option>)}</select>
                  </div>
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <InfoField label="최소 시가총액 (십억 USD, 0 = 제한 없음)" help={c.min_market_cap_usd ? `${(c.min_market_cap_usd / 1e9).toLocaleString("ko-KR")}B USD 이상인 종목만 후보` : "제한 없음"} info="기업 가치(시가총액)가 이 금액보다 작은 기업을 후보에서 뺍니다. 너무 작은 기업을 빼고 싶을 때 씁니다.">
                    <NumberInput className={inputClass} min={0} step={0.5} value={(c.min_market_cap_usd ?? 0) / 1e9} onChange={(v) => upd((f) => { f.constraints.min_market_cap_usd = Math.round(v * 1e9) })} />
                  </InfoField>
                  <InfoField label="최소 일평균 거래대금 (백만 USD, 0 = 제한 없음)" help={c.min_avg_daily_volume_usd ? `하루 평균 ${(c.min_avg_daily_volume_usd / 1e6).toLocaleString("ko-KR")}M USD 이상 거래되는 종목만 후보` : "제한 없음"} info="하루 평균 거래 금액이 이보다 작은 종목을 후보에서 뺍니다. 거래가 드물어 사고팔기 어려운 종목을 빼고 싶을 때 씁니다.">
                    <NumberInput className={inputClass} min={0} step={1} value={(c.min_avg_daily_volume_usd ?? 0) / 1e6} onChange={(v) => upd((f) => { f.constraints.min_avg_daily_volume_usd = Math.round(v * 1e6) })} />
                  </InfoField>
                </div>
              </div>
            </PartDisclosure>
            <Alert title="지원 범위" tone="info">주식만 후보가 됩니다(ETF 후보 선정은 아직 지원하지 않음). 레버리지·공매도는 지원하지 않습니다.</Alert>
          </div>
        )}
        {step === 3 && (
          <div className="space-y-8">
            <div>
              <h2 className="flex items-center gap-1 text-lg font-bold text-slate-950">투자 전략 설정<InfoTip label="투자 전략 설정">분석을 요청할 때 아이디어에 맞춰 바꿀 수 있고, 분석 모델이 확인 질문을 할 수 있습니다.</InfoTip></h2>
              <p className="mt-1 text-sm text-slate-500">투자할 기업을 고르고 투자금을 나누는 방식을 정합니다.</p>
            </div>
            {rec && <StrategyRecommendation rec={rec} value={form.strategy_preference} onPick={(p) => upd((f) => { Object.assign(f.strategy_preference, p) })} />}
            <StrategyFields value={form.strategy_preference} templates={opt?.templates} weightings={opt?.weightings} recommended={rec ? asPref(rec.recommended) : null} onChange={(p) => upd((f) => { Object.assign(f.strategy_preference, p) })} />
            <Part title="메모" tag="선택"><textarea aria-label="메모" className={`${inputClass} min-h-20`} value={form.diagnosis?.memo ?? ""} onChange={(e) => upd((f) => { if (f.diagnosis) f.diagnosis.memo = e.target.value })} placeholder="선호나 참고 사항. 검증되는 수치 제약으로는 쓰이지 않습니다." /></Part>
            <Part title="저장 요약">
              <p className="text-sm text-slate-700">{money(form.capital.initial_amount, cur)} · {yearsText(form.horizon.target_years)} · {form.diagnosis?.final_tendency} · 손실 감내 {pctText(form.risk.max_drawdown_tolerance)} · {c.universe.map(ko).join("/")}</p>
              <p className="text-sm font-semibold text-slate-900">{sp}</p>
            </Part>
            {saveError && <Alert title="저장 실패" tone="error">{saveError}</Alert>}
            {Object.keys(errors).length > 0 && <Alert title="확인이 필요한 항목 (빨간 단계 카드를 눌러 고칠 수 있습니다)" tone="warning"><ul className="list-disc pl-5">{Object.entries(errors).map(([k, v]) => <li key={k}>{v.includes(":") ? v : `${FIELD_KO[k] ?? k}: ${v}`}</li>)}</ul></Alert>}
          </div>
        )}
        <div className="mt-8 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-300 bg-white px-5 py-4 shadow-sm sm:px-6">
          {/* 단계 이동: 왼쪽 이전 · 오른쪽 다음(저장). 첫 단계에는 이전이 없다 */}
          <div>{step > 0 && <Button variant="neutral" onClick={() => setStep((s) => s - 1)}>이전</Button>}</div>
          <div className="flex items-center gap-3">
            {Object.keys(errors).length > 0 && step < 3 && <Badge tone="red">{Object.values(errors)[0]}</Badge>}
            {step < STEPS.length - 1 ? <Button onClick={next}>다음</Button> : <Button onClick={submit} disabled={saving}><Check className="size-4" />{saving ? "저장 중…" : "저장"}</Button>}
          </div>
        </div>
      </div>
    </div>
  )
}

/** 초기 투자금 0원 시작의 예상 투자 일정 (제안 기능, 목업에서만). 넣는 원금만 계산하고 수익은 예측하지 않는다. */
function ZeroStartSchedule({ capital, years, today = new Date() }: { capital: ProfileFields["capital"]; years: number; today?: Date }) {
  const m = capital.monthly_contribution, cur = capital.currency, day = capital.contribution_day
  if (!(m > 0)) return null
  const first = new Date(today.getFullYear(), today.getMonth() + (today.getDate() >= day ? 1 : 0), day)
  const dates = [0, 1, 2].map((i) => new Date(first.getFullYear(), first.getMonth() + i, day))
  const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
  return (
    <div role="note" aria-label="예상 투자 일정" className="space-y-3 rounded-xl border border-blue-200 bg-blue-50/60 p-4 text-sm text-slate-700">
      <p className="flex items-center font-semibold text-slate-900">예상 투자 일정<MockTag /></p>
      <p className="text-xs leading-5">처음 투자금 없이 시작합니다. 매월 {day}일에 {money(m, cur)}씩 넣어 그때 정해진 비중으로 삽니다. 첫 투자 전까지는 투자한 금액이 없습니다.</p>
      <ol className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        {dates.map((d, i) => <li key={i} className="rounded-lg bg-white px-3 py-2 text-xs"><span className="block font-semibold text-slate-900">{i + 1}회차 · {ymd(d)}</span><span className="text-slate-500">넣은 원금 누적 {money(m * (i + 1), cur)}</span></li>)}
      </ol>
      <p className="text-xs leading-5 text-slate-600">1년 뒤 넣은 원금 <b>{money(m * 12, cur)}</b> · 투자기간 {yearsText(years)} 동안 넣는 원금 <b>{money(Math.round(m * 12 * years), cur)}</b> (수익을 뺀 원금만 계산한 값입니다)</p>
      <p className="text-[11px] leading-5 text-slate-500">과거 성과 계산(백테스트)과 모의투자도 첫 적립일부터 매월 넣은 것으로 계산하고, 수익률은 넣은 원금 대비로 봅니다. 날짜는 오늘 기준 예시이며 휴장일이면 다음 거래일에 투자합니다.</p>
    </div>
  )
}
