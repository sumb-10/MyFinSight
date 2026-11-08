import { useEffect, useMemo, useState } from "react"
import { ChevronDown, Info } from "lucide-react"
import type { NumHoldings, Options, ProfileVersion, Rebalance, Template, Universe, Weighting } from "../../api/types"
import { useService } from "../../app/providers"
import { proposedRulesOf } from "../../api/proposed"
import { useResource } from "../../state/useResource"
import { Button, inputClass } from "../../ui"
import { ko } from "../../lib/format"
import { benchName, listText, money, pctText, rebalanceText, usdFloor, yearsText } from "../profile/format"
import { NumberInput } from "../profile/inputs"
import { NEWS_INFO, TEMPLATE_INFO, templateLabel, WEIGHTING_INFO, weightingLabel } from "../profile/strategyInfo"
import { DetailDialogShell } from "./DetailDialogShell"

/** 홈의 "상세 조건": 이번 요청에만 적용할 조건. 프로필은 바꾸지 않고, 프로필과 다른 값만 overrides(필드 경로 → 값)로 보낸다. */
export type Overrides = Record<string, unknown>

export type Form = {
  initial_amount: number; currency: "KRW" | "USD"; monthly_contribution: number; contribution_day: number; target_years: number
  bt_mode: "recent" | "range"; backtest_years: number; bt_start_year: number; bt_end_year: number
  risk_tolerance: "conservative" | "moderate" | "aggressive"; max_drawdown_pct: number; target_return_pct: number; benchmark: string
  universe: Universe[]; num_target: number; num_min: number; num_max: number; max_stock_pct: number; max_sector_pct: number; template: Template; weighting: Weighting; use_news_tilt: boolean; exclude: string
  exclude_themes: string; exclude_sectors: string; min_market_cap_b: number; min_adv_m: number; min_cash_pct: number; rebalance_count: number; rebalance_unit: string
}

const thisYear = new Date().getFullYear()

export function fromProfile(p: ProfileVersion, ov: Overrides): Form {
  const g = (path: string, def: unknown) => (path in ov ? ov[path] : def)
  const startDate = g("horizon.start_date", null) as string | null
  const bt = Number(g("horizon.backtest_years", p.horizon.backtest_years ?? 3))
  const endYear = startDate ? Number(startDate.slice(0, 4)) : thisYear - 1
  return {
    initial_amount: Number(g("capital.initial_amount", p.capital.initial_amount)), currency: g("capital.currency", p.capital.currency) as "KRW" | "USD",
    monthly_contribution: Number(g("capital.monthly_contribution", p.capital.monthly_contribution)), contribution_day: Number(g("capital.contribution_day", p.capital.contribution_day)),
    target_years: Number(g("horizon.target_years", p.horizon.target_years)),
    bt_mode: startDate ? "range" : "recent", backtest_years: bt, bt_start_year: Math.max(2000, endYear - Math.round(bt) + 1), bt_end_year: endYear,
    risk_tolerance: g("risk.risk_tolerance", p.risk.risk_tolerance) as Form["risk_tolerance"], max_drawdown_pct: Math.round(Number(g("risk.max_drawdown_tolerance", p.risk.max_drawdown_tolerance)) * 100),
    target_return_pct: Math.round(Number(g("risk.target_annual_return", p.risk.target_annual_return)) * 100), benchmark: String(g("risk.benchmark", p.risk.benchmark)),
    universe: (g("constraints.universe", p.constraints.universe) as Universe[]).slice(), ...holdingsFrom(p, ov),
    max_stock_pct: Math.round(Number(g("constraints.max_weight_per_stock", p.constraints.max_weight_per_stock)) * 100), max_sector_pct: Math.round(Number(g("constraints.max_weight_per_sector", p.constraints.max_weight_per_sector)) * 100),
    template: g("strategy_preference.template", p.strategy_preference.template) as Template, weighting: g("strategy_preference.baseline_weighting", p.strategy_preference.baseline_weighting) as Weighting,
    use_news_tilt: Boolean(g("strategy_preference.use_news_tilt", p.strategy_preference.use_news_tilt)), exclude: (g("constraints.exclude_tickers", p.constraints.exclude_tickers) as string[]).join(", "),
    exclude_themes: (g("constraints.exclude_themes", p.constraints.exclude_themes ?? []) as string[]).join(", "), exclude_sectors: (g("constraints.exclude_sectors", p.constraints.exclude_sectors ?? []) as string[]).join(", "),
    min_market_cap_b: Number(g("constraints.min_market_cap_usd", p.constraints.min_market_cap_usd ?? 0)) / 1e9, min_adv_m: Number(g("constraints.min_avg_daily_volume_usd", p.constraints.min_avg_daily_volume_usd ?? 0)) / 1e6,
    min_cash_pct: Math.round(Number(g("constraints.min_cash_ratio", p.constraints.min_cash_ratio ?? 0)) * 100),
    rebalance_count: Number((g("constraints.rebalance", p.constraints.rebalance) as { count: number }).count), rebalance_unit: String((g("constraints.rebalance", p.constraints.rebalance) as { unit: string }).unit),
  }
}

/** 종목 수: 통째로 바꾼 값(constraints.num_holdings, 실행 전 점검 답)이 있으면 그것을, 아니면 목표·최소·최대 경로를 각각 본다. */
function holdingsFrom(p: ProfileVersion, ov: Overrides): { num_target: number; num_min: number; num_max: number } {
  const whole = ov["constraints.num_holdings"] as NumHoldings | undefined
  const base = whole ?? p.constraints.num_holdings
  const g = (path: string, def: number) => Number(path in ov ? ov[path] : def)
  return { num_target: g("constraints.num_holdings.target", base.target), num_min: g("constraints.num_holdings.min", base.min), num_max: g("constraints.num_holdings.max", base.max) }
}

/** 프로필과 다른 값만 덮어쓰기로 만든다. 폼이 정수로 다루는 값(예: 12.5% → 13)처럼 건드리지 않아도 달라 보이는 항목은 빼고, 사용자가 바꾼 값만 남긴다. */
export function toOverrides(f: Form, p: ProfileVersion): Overrides {
  const o = rawOverrides(f, p)
  const untouched = rawOverrides(fromProfile(p, {}), p)
  for (const k of Object.keys(untouched)) if (JSON.stringify(o[k]) === JSON.stringify(untouched[k])) delete o[k]
  return o
}

function rawOverrides(f: Form, p: ProfileVersion): Overrides {
  const o: Overrides = {}
  const put = (path: string, v: unknown, base: unknown) => { if (JSON.stringify(v) !== JSON.stringify(base)) o[path] = v }
  put("capital.initial_amount", f.initial_amount, p.capital.initial_amount)
  put("capital.currency", f.currency, p.capital.currency)
  put("capital.monthly_contribution", f.monthly_contribution, p.capital.monthly_contribution)
  put("capital.contribution_day", f.contribution_day, p.capital.contribution_day)
  put("horizon.target_years", f.target_years, p.horizon.target_years)
  if (f.bt_mode === "range") {
    const years = f.bt_end_year - f.bt_start_year + 1
    o["horizon.backtest_years"] = years
    if (f.bt_end_year < thisYear) o["horizon.start_date"] = `${f.bt_end_year}-12-31`
  } else put("horizon.backtest_years", f.backtest_years, p.horizon.backtest_years ?? 3)
  put("risk.risk_tolerance", f.risk_tolerance, p.risk.risk_tolerance)
  put("risk.max_drawdown_tolerance", f.max_drawdown_pct / 100, p.risk.max_drawdown_tolerance)
  put("risk.target_annual_return", f.target_return_pct / 100, p.risk.target_annual_return)
  put("risk.benchmark", f.benchmark, p.risk.benchmark)
  put("constraints.universe", f.universe, p.constraints.universe)
  const nh = p.constraints.num_holdings
  if (f.num_min !== nh.min || f.num_max !== nh.max) o["constraints.num_holdings"] = { target: f.num_target, min: f.num_min, max: f.num_max }  // 범위까지 바뀌면 통째로 (서버 HARD: 최소 ≤ 목표 ≤ 최대)
  else put("constraints.num_holdings.target", f.num_target, nh.target)
  put("constraints.max_weight_per_stock", f.max_stock_pct / 100, p.constraints.max_weight_per_stock)
  put("constraints.max_weight_per_sector", f.max_sector_pct / 100, p.constraints.max_weight_per_sector)
  put("strategy_preference.template", f.template, p.strategy_preference.template)
  put("strategy_preference.baseline_weighting", f.weighting, p.strategy_preference.baseline_weighting)
  put("strategy_preference.use_news_tilt", f.use_news_tilt, p.strategy_preference.use_news_tilt)
  const ex = f.exclude.split(/[,\s]+/).map((x) => x.trim().toUpperCase()).filter(Boolean)
  put("constraints.exclude_tickers", ex, p.constraints.exclude_tickers)
  const split = (t: string) => t.split(/[,\s]+/).map((x) => x.trim().toLowerCase()).filter(Boolean)
  put("constraints.exclude_themes", split(f.exclude_themes), p.constraints.exclude_themes ?? [])
  put("constraints.exclude_sectors", f.exclude_sectors.split(",").map((x) => x.trim()).filter(Boolean), p.constraints.exclude_sectors ?? [])
  put("constraints.min_market_cap_usd", Math.round(f.min_market_cap_b * 1e9), p.constraints.min_market_cap_usd ?? 0)
  put("constraints.min_avg_daily_volume_usd", Math.round(f.min_adv_m * 1e6), p.constraints.min_avg_daily_volume_usd ?? 0)
  put("constraints.min_cash_ratio", f.min_cash_pct / 100, p.constraints.min_cash_ratio ?? 0)
  put("constraints.rebalance", { count: f.rebalance_count, unit: f.rebalance_unit }, p.constraints.rebalance)
  return o
}

export const overrideText = (k: string, v: unknown): string => {
  if (k === "constraints.num_holdings" && v && typeof v === "object") { const n = v as NumHoldings; return `목표 ${n.target} (${n.min}~${n.max})` }
  if (k === "constraints.rebalance" && v && typeof v === "object") { const r = v as { count: number; unit: string }; return r.count === 0 ? "없음" : `${r.count}×${ko(r.unit)}` }
  if (k === "constraints.min_market_cap_usd") return v ? `${(Number(v) / 1e9).toLocaleString("ko-KR")}B USD` : "제한 없음"
  if (k === "constraints.min_avg_daily_volume_usd") return v ? `${(Number(v) / 1e6).toLocaleString("ko-KR")}M USD` : "제한 없음"
  if (k === "constraints.min_cash_ratio") return `${Math.round(Number(v) * 100)}%`
  if (Array.isArray(v)) return v.map((x) => ko(x)).join("·") || "없음"
  if (typeof v === "boolean") return v ? "예" : "아니오"
  if (typeof v === "number" && ["risk.max_drawdown_tolerance", "risk.target_annual_return", "constraints.max_weight_per_stock", "constraints.max_weight_per_sector"].includes(k)) return `${Math.round(v * 100)}%`
  if (typeof v === "number") return k.includes("years") ? `${v}년` : v.toLocaleString("ko-KR")
  return ko(v)
}

type TabId = "money" | "goal" | "stocks" | "strategy"
type AdvId = "range" | "exclude" | "floor" | "cash"
const TABS: { id: TabId; label: string }[] = [{ id: "money", label: "자금·기간" }, { id: "goal", label: "목표·위험" }, { id: "stocks", label: "종목·배분" }, { id: "strategy", label: "전략" }]

/** overrides 경로 → 화면 이름·탭·접이식 영역. 변경 표시·탭 개수·하단 요약이 모두 이 표와 실제 overrides 로 만들어진다. */
const PLACE: Record<string, { label: string; tab: TabId; adv?: AdvId }> = {
  "capital.initial_amount": { label: "투자금", tab: "money" }, "capital.currency": { label: "통화", tab: "money" }, "capital.monthly_contribution": { label: "매월 추가 투자금", tab: "money" }, "capital.contribution_day": { label: "추가 투자일", tab: "money" },
  "horizon.target_years": { label: "앞으로 투자할 기간", tab: "money" }, "horizon.backtest_years": { label: "과거 성과를 확인할 기간", tab: "money" }, "horizon.start_date": { label: "분석 기준일", tab: "money" },
  "risk.risk_tolerance": { label: "투자성향", tab: "goal" }, "risk.max_drawdown_tolerance": { label: "손실 감내 수준", tab: "goal" }, "risk.target_annual_return": { label: "목표 연수익률", tab: "goal" }, "risk.benchmark": { label: "비교지수", tab: "goal" },
  "constraints.universe": { label: "투자 대상 지수", tab: "stocks" }, "constraints.num_holdings.target": { label: "목표 종목 수", tab: "stocks" }, "constraints.num_holdings": { label: "종목 수", tab: "stocks", adv: "range" },
  "constraints.max_weight_per_stock": { label: "종목당 최대 비중", tab: "stocks" }, "constraints.max_weight_per_sector": { label: "섹터당 최대 비중", tab: "stocks" },
  "constraints.exclude_tickers": { label: "제외 종목", tab: "stocks", adv: "exclude" }, "constraints.exclude_themes": { label: "제외 테마", tab: "stocks", adv: "exclude" }, "constraints.exclude_sectors": { label: "제외 섹터", tab: "stocks", adv: "exclude" },
  "constraints.min_market_cap_usd": { label: "최소 시가총액", tab: "stocks", adv: "floor" }, "constraints.min_avg_daily_volume_usd": { label: "최소 일평균 거래대금", tab: "stocks", adv: "floor" },
  "constraints.min_cash_ratio": { label: "최소 현금 비율", tab: "stocks", adv: "cash" }, "constraints.rebalance": { label: "리밸런싱", tab: "stocks", adv: "cash" },
  "strategy_preference.template": { label: "투자할 기업", tab: "strategy" }, "strategy_preference.baseline_weighting": { label: "투자금 나누는 방식", tab: "strategy" }, "strategy_preference.use_news_tilt": { label: "뉴스·공시 반영", tab: "strategy" },
}
/** 홈 배지·질문 보기의 항목 이름. 상세 조건 창과 같은 이름(PLACE, 용어표 기준)을 쓴다 — 전에는 따로 둔 짧은 이름(허용 낙폭·유니버스 등)이 섞였다. */
export const OVERRIDE_LABELS: Record<string, string> = Object.fromEntries(Object.entries(PLACE).map(([k, p]) => [k, p.label]))
const ORDER = Object.keys(PLACE)
const placeOf = (k: string) => PLACE[k] ?? { label: k, tab: "money" as TabId }
const getPath = (o: unknown, path: string): unknown => path.split(".").reduce<unknown>((x, k) => (x as Record<string, unknown> | undefined)?.[k], o)

/** 하단 요약용 값 글자 (사용자 언어·단위). */
function changeText(k: string, v: unknown, cur: "KRW" | "USD"): string {
  switch (k) {
    case "capital.initial_amount": return money(Number(v), cur)
    case "capital.monthly_contribution": return v ? money(Number(v), cur) : "없음"
    case "capital.currency": return v === "KRW" ? "원 (KRW)" : "달러 (USD)"
    case "capital.contribution_day": return `매월 ${v}일`
    case "horizon.target_years": case "horizon.backtest_years": return yearsText(Number(v))
    case "horizon.start_date": return v ? `${String(v).slice(0, 4)}년 말` : "최근 자료 기준"
    case "risk.max_drawdown_tolerance": case "risk.target_annual_return": case "constraints.max_weight_per_stock": case "constraints.max_weight_per_sector": case "constraints.min_cash_ratio": return pctText(Number(v))
    case "risk.benchmark": return benchName(String(v))
    case "constraints.universe": return (v as string[]).map(ko).join(", ") || "없음"
    case "constraints.num_holdings.target": return `${v}개`
    case "constraints.num_holdings": { const n = v as NumHoldings; return `목표 ${n.target}개 (최소 ${n.min} ~ 최대 ${n.max})` }
    case "constraints.exclude_tickers": case "constraints.exclude_themes": case "constraints.exclude_sectors": return listText(v as string[])
    case "constraints.min_market_cap_usd": case "constraints.min_avg_daily_volume_usd": return usdFloor(Number(v))
    case "constraints.rebalance": return rebalanceText(v as Rebalance)
    case "strategy_preference.template": return templateLabel(String(v))
    case "strategy_preference.baseline_weighting": return weightingLabel(String(v))
    case "strategy_preference.use_news_tilt": return v ? "켜짐" : "꺼짐"
    default: return ko(v)
  }
}

export interface ChangeRow { key: string; label: string; before: string; after: string; tab: TabId }
/** 실제 적용할 overrides 한 건당 한 줄 (개수와 요약이 어긋나지 않게 overrides 에서 바로 만든다). */
export function changeRows(ov: Overrides, f: Form, p: ProfileVersion): ChangeRow[] {
  return Object.keys(ov).sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b)).map((k) => ({ key: k, label: placeOf(k).label, before: changeText(k, getPath(p, k) ?? null, p.capital.currency), after: changeText(k, ov[k], f.currency), tab: placeOf(k).tab }))
}

export interface FormError { id: string; message: string; tab: TabId; adv?: AdvId }
/** 기존 검사 규칙 그대로. 입력칸 가까이 보여 주고, 첫 오류의 탭·영역으로 이동할 수 있게 위치를 함께 준다. */
/** 목표 종목 수가 최소~최대를 벗어났을 때 (최소·최대는 저절로 바꾸지 않는다 — 서버 HARD: 최소 ≤ 목표 ≤ 최대). */
const targetRangeError = (f: Form) => `목표 종목 수는 최소 ${f.num_min} ~ 최대 ${f.num_max}개 사이여야 합니다. 목표를 바꾸거나 아래 「종목 수 범위」에서 최소·최대를 바꿔 주세요`

export function validate(f: Form, { allowZero = false }: { allowZero?: boolean } = {}): FormError[] {
  const e: FormError[] = []
  // allowZero: 제안 규칙 — 초기 투자금 0원 + 매월 추가 투자 (목업에서만, 지금 서버는 0보다 커야 함). 내 투자조건 폼(validateProfile)과 같은 규칙
  if (allowZero && f.initial_amount === 0) { if (!(f.monthly_contribution > 0)) e.push({ id: "initial_amount", message: "처음 투자금을 0원으로 하려면 매월 추가 투자금을 정해 주세요 (목업 규칙)", tab: "money" }) }
  else if (!(f.initial_amount > 0)) e.push({ id: "initial_amount", message: "투자금은 0보다 커야 합니다", tab: "money" })
  if (f.bt_mode === "range" && !(f.bt_start_year <= f.bt_end_year)) e.push({ id: "bt_start_year", message: "백테스트 시작 연도가 끝 연도보다 늦습니다", tab: "money" })
  if (f.bt_mode === "range" && f.bt_end_year - f.bt_start_year + 1 > 20) e.push({ id: "bt_start_year", message: "백테스트는 최대 20년입니다", tab: "money" })
  if (f.bt_mode === "recent" && !(f.backtest_years > 0 && f.backtest_years <= 20)) e.push({ id: "backtest_years", message: "백테스트 기간은 0보다 크고 20년 이하입니다", tab: "money" })
  if (!f.universe.length) e.push({ id: "universe", message: "유니버스를 하나 이상 고르세요", tab: "stocks" })
  if (f.max_sector_pct < f.max_stock_pct) e.push({ id: "max_sector_pct", message: "섹터당 상한은 종목당 상한 이상이어야 합니다", tab: "stocks" })
  if (f.num_min > f.num_max) e.push({ id: "num_min", message: "최소 종목 수가 최대 종목 수보다 큽니다", tab: "stocks", adv: "range" })
  else if (f.num_target < f.num_min || f.num_target > f.num_max) e.push({ id: "num_target", message: targetRangeError(f), tab: "stocks" })
  if (f.max_stock_pct * f.num_min < 100 - f.min_cash_pct) e.push({ id: "max_stock_pct", message: `종목당 상한 × 최소 종목 수가 투자 비율보다 작아 돈을 다 배분할 수 없습니다 (상한을 ${Math.ceil((100 - f.min_cash_pct) / f.num_min)}% 이상으로 올리거나 최소 종목 수를 늘려 주세요)`, tab: "stocks" })
  return e
}

const dom = (id: string) => `dc-${id}`

function ChangedMark({ on }: { on: boolean }) {
  return on ? <span className="ml-1.5 rounded-md bg-blue-50 px-1.5 py-0.5 text-[11px] font-semibold text-blue-700">변경됨</span> : null
}

/** 입력 한 칸: 이름(+변경됨) · 입력 · 설명 또는 오류. id 를 주면 이름표와 연결하고, 없으면 묶음 입력의 제목으로 쓴다. */
function Item({ id, label, changed, help, error, children }: { id?: string; label: string; changed?: boolean; help?: React.ReactNode; error?: string; children: React.ReactNode }) {
  const name = <>{label}<ChangedMark on={!!changed} /></>
  return (
    <div className="min-w-0">
      {id ? <label htmlFor={id} className="mb-1.5 block text-sm font-semibold text-slate-700">{name}</label> : <p className="mb-1.5 text-sm font-semibold text-slate-700">{name}</p>}
      {children}
      {error ? <p id={id ? `${id}-error` : undefined} className="mt-1.5 text-xs font-medium text-red-600">{error}</p> : help && <p className="mt-1.5 text-xs leading-5 text-slate-500">{help}</p>}
    </div>
  )
}

function SectionCard({ title, desc, children }: { title: string; desc?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6">
      <h3 className="text-base font-bold text-slate-950">{title}</h3>
      {desc && <p className="mt-1 text-xs leading-5 text-slate-500">{desc}</p>}
      <div className="mt-4 space-y-4">{children}</div>
    </section>
  )
}

function AdvCard({ title, summary, count, open, onToggle, children }: { title: string; summary: string; count: number; open: boolean; onToggle: () => void; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white">
      <button type="button" aria-expanded={open} onClick={onToggle} className="flex w-full items-center justify-between gap-3 rounded-2xl px-5 py-4 text-left hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500 sm:px-6">
        <span className="min-w-0">
          <span className="block text-sm font-bold text-slate-900">{title}<span className="ml-2 rounded-md border border-slate-200 bg-slate-100 px-1.5 py-0.5 text-[11px] font-semibold text-slate-500">고급</span>{count > 0 && <span className="ml-1.5 rounded-md bg-blue-50 px-1.5 py-0.5 text-[11px] font-semibold text-blue-700">변경 {count}</span>}</span>
          <span className="mt-0.5 block break-words text-xs text-slate-500">{summary}</span>
        </span>
        <ChevronDown className={`size-4 shrink-0 text-slate-500 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && <div className="space-y-4 border-t border-slate-100 px-5 py-4 sm:px-6 sm:pb-6">{children}</div>}
    </section>
  )
}

const twoCols = "grid grid-cols-1 gap-4 sm:grid-cols-2"

export function DetailConditionsDialog({ profile, initial, onApply, close, title = "이번 분석의 상세 조건", applyLabel = "이 조건 적용", intro }: { profile: ProfileVersion; initial: Overrides; onApply: (o: Overrides) => void; close: () => void; title?: string; applyLabel?: string; intro?: string }) {
  const svc = useService()
  const options = useResource(() => svc.options(), [svc])
  const opt: Options | null = options.data
  const allowZero = !!proposedRulesOf(opt)?.allow_zero_initial_amount
  const [f, setF] = useState<Form>(() => fromProfile(profile, initial))
  const [tab, setTab] = useState<TabId>("money")
  const [showChanges, setShowChanges] = useState(false)
  const [tried, setTried] = useState(false)  // 적용을 한 번 누른 뒤부터 오류를 보여 준다
  const [focusId, setFocusId] = useState("")
  const [advOpen, setAdvOpen] = useState<Partial<Record<AdvId, boolean>>>(() => {
    const start = fromProfile(profile, initial)
    const open: Partial<Record<AdvId, boolean>> = {}
    for (const k of Object.keys(toOverrides(start, profile))) { const a = placeOf(k).adv; if (a) open[a] = true }
    for (const e of validate(start)) if (e.adv) open[e.adv] = true
    return open
  })
  const initKey = JSON.stringify(initial)  // initial 이 렌더마다 새 {} 여도 입력 중인 값을 지우지 않게
  useEffect(() => { setF(fromProfile(profile, initial)) }, [profile.version, initKey])  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!focusId) return
    const el = document.getElementById(focusId)
    el?.focus()
    el?.scrollIntoView?.({ block: "center" })  // 입력칸 아래의 오류 문구가 하단 고정 영역에 가리지 않게
    setFocusId("")
  }, [focusId])
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((x) => ({ ...x, [k]: v }))
  const ov = useMemo(() => toOverrides(f, profile), [f, profile])
  const rows = useMemo(() => changeRows(ov, f, profile), [ov, f, profile])
  const errors = tried ? validate(f, { allowZero }) : []
  const errOf = (id: string) => errors.find((e) => e.id === id)?.message
  const targetErr = f.num_min <= f.num_max && (f.num_target < f.num_min || f.num_target > f.num_max) ? targetRangeError(f) : undefined  // 목표 칸 오류는 적용을 누르기 전에도 바로 보여 준다
  const has = (...keys: string[]) => keys.some((k) => k in ov)
  const countAdv = (a: AdvId) => Object.keys(ov).filter((k) => placeOf(k).adv === a).length
  const isOpen = (a: AdvId) => !!advOpen[a] || errors.some((e) => e.adv === a)
  const toggle = (a: AdvId) => setAdvOpen((o) => ({ ...o, [a]: !isOpen(a) }))
  const field = (id: string) => ({ id: dom(id), "aria-invalid": errOf(id) ? true : undefined, "aria-describedby": errOf(id) ? `${dom(id)}-error` : undefined })
  const apply = () => {
    setTried(true)
    const first = validate(f, { allowZero })[0]
    if (first) {
      setShowChanges(false); setTab(first.tab)
      if (first.adv) setAdvOpen((o) => ({ ...o, [first.adv!]: true }))
      setFocusId(dom(first.id))
      return
    }
    onApply(ov); close()
  }
  const reset = () => { setF(fromProfile(profile, {})); setTried(false); setShowChanges(false) }  // 편집 중인 값만 되돌린다 (적용은 적용 버튼에서)
  const moveTab = (e: React.KeyboardEvent, i: number) => {
    const to = e.key === "ArrowRight" ? (i + 1) % TABS.length : e.key === "ArrowLeft" ? (i + TABS.length - 1) % TABS.length : e.key === "Home" ? 0 : e.key === "End" ? TABS.length - 1 : -1
    if (to < 0) return
    e.preventDefault(); setTab(TABS[to].id); setShowChanges(false); setFocusId(`dc-tab-${TABS[to].id}`)
  }
  const nh = profile.constraints.num_holdings
  const thisTemplate = TEMPLATE_INFO[f.template], thisWeighting = WEIGHTING_INFO[f.weighting]
  const excludeN = (t: string) => t.split(/[,\s]+/).filter(Boolean).length
  const excludeSummary = [excludeN(f.exclude) && `종목 ${excludeN(f.exclude)}개`, excludeN(f.exclude_themes) && `테마 ${excludeN(f.exclude_themes)}개`, f.exclude_sectors.split(",").filter((x) => x.trim()).length && `섹터 ${f.exclude_sectors.split(",").filter((x) => x.trim()).length}개`].filter(Boolean).join(" · ") || "제외 조건 없음"

  const header = (
    <>
      {intro !== "" && <p className="mt-1 text-sm leading-6 text-slate-600 [@media(max-height:560px)]:hidden">{intro ?? "프로필의 기본 조건을 이번 요청에서만 바꿉니다. 프로필 자체는 그대로입니다. 바꾼 항목은 조건 확인 화면에 파란색으로 표시됩니다."}</p>}
      <p className="mt-2 flex items-start gap-2 rounded-xl bg-slate-100 px-3 py-2 text-xs font-semibold leading-5 text-slate-800 [@media(max-height:480px)]:mt-0.5 [@media(max-height:480px)]:py-0.5"><Info className="mt-0.5 size-4 shrink-0 text-slate-500" aria-hidden="true" />저장된 기본 투자조건은 바뀌지 않고 이번 요청에만 적용됩니다.</p>
      <div role="tablist" aria-label="상세 조건 분류" className="mt-3 grid grid-cols-4 gap-1 [@media(max-height:480px)]:mt-0.5">
        {TABS.map((t, i) => {
          const on = tab === t.id
          const n = rows.filter((r) => r.tab === t.id).length
          const bad = errors.some((e) => e.tab === t.id)
          return (
            <button key={t.id} id={`dc-tab-${t.id}`} type="button" role="tab" aria-selected={on} aria-controls="dc-panel" tabIndex={on ? 0 : -1} onClick={() => { setTab(t.id); setShowChanges(false) }} onKeyDown={(e) => moveTab(e, i)} className={`flex min-w-0 flex-wrap items-center justify-center gap-x-1.5 gap-y-0.5 border-b-2 px-1 py-2 text-[13px] font-semibold [@media(max-height:480px)]:py-1 transition focus:outline-none focus:ring-2 focus:ring-inset focus:ring-blue-500 sm:text-sm ${on ? "border-blue-700 text-blue-800" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
              {t.label}
              {n > 0 && <span aria-label={`변경 ${n}개`} className="rounded-full bg-blue-50 px-1.5 text-[11px] font-bold text-blue-700">{n}</span>}
              {bad && <span aria-label="오류 있음" className="size-2 rounded-full bg-red-600" />}
            </button>
          )
        })}
      </div>
    </>
  )

  const footer = (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-wrap items-center gap-x-1 gap-y-1">
        {rows.length > 0
          ? <button type="button" aria-expanded={showChanges} onClick={() => setShowChanges((v) => !v)} className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm font-semibold text-blue-800 hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500">변경 {rows.length}개<ChevronDown className={`size-4 transition-transform ${showChanges ? "rotate-180" : ""}`} /></button>
          : <span className="px-2 py-1.5 text-sm text-slate-500">변경 없음</span>}
        <Button variant="ghost" className="min-h-8 px-2 py-1 text-xs" onClick={reset} disabled={rows.length === 0}>기본 투자조건으로 되돌리기</Button>
      </div>
      <div className="flex justify-end gap-2"><Button variant="ghost" onClick={close}>취소</Button><Button onClick={apply}>{applyLabel}</Button></div>
    </div>
  )

  return (
    <DetailDialogShell title={title} close={close} header={header} footer={footer}>
      <div id="dc-panel" role="tabpanel" aria-labelledby={`dc-tab-${tab}`} className="space-y-6 text-sm text-slate-700">
        {showChanges ? (
          <SectionCard title="이번 분석에서 바뀌는 조건" desc="기본값 → 이번 분석 값">
            <ul className="divide-y divide-slate-100">
              {rows.map((r) => <li key={r.key} className="flex flex-col gap-0.5 py-2 first:pt-0 last:pb-0 sm:flex-row sm:gap-4"><span className="shrink-0 font-semibold text-slate-900 sm:w-44">{r.label}</span><span className="min-w-0 break-words"><span className="text-slate-500">{r.before}</span><span className="mx-1.5 text-slate-400">→</span><b className="text-slate-950">{r.after}</b></span></li>)}
            </ul>
          </SectionCard>
        ) : tab === "money" ? (
          <>
            <SectionCard title="투자금">
              <div className={twoCols}>
                <Item id={dom("initial_amount")} label="투자금" changed={has("capital.initial_amount")} error={errOf("initial_amount")} help={money(f.initial_amount, f.currency)}><input {...field("initial_amount")} className={inputClass} inputMode="numeric" value={f.initial_amount.toLocaleString("ko-KR")} onChange={(e) => set("initial_amount", Number(e.target.value.replace(/\D/g, "")))} /></Item>
                <Item id={dom("currency")} label="통화" changed={has("capital.currency")}><select id={dom("currency")} className={inputClass} value={f.currency} onChange={(e) => set("currency", e.target.value as "KRW" | "USD")}><option value="KRW">원 (KRW)</option><option value="USD">달러 (USD)</option></select></Item>
                <Item id={dom("monthly")} label="매월 추가 투자금 (0이면 없음)" changed={has("capital.monthly_contribution")} help={f.monthly_contribution ? `매월 ${money(f.monthly_contribution, f.currency)}` : undefined}><input id={dom("monthly")} className={inputClass} inputMode="numeric" value={f.monthly_contribution.toLocaleString("ko-KR")} onChange={(e) => set("monthly_contribution", Number(e.target.value.replace(/\D/g, "")))} /></Item>
                <Item id={dom("day")} label="추가 투자일 (매월)" changed={has("capital.contribution_day")}><NumberInput id={dom("day")} min={1} max={28} value={f.contribution_day} onChange={(v) => set("contribution_day", v)} /></Item>
              </div>
            </SectionCard>
            <SectionCard title="기간" desc="앞으로 투자할 기간은 미래의 투자 계획이고, 과거 성과를 확인할 기간은 지난 자료로 전략을 검증하는 기간입니다.">
              <div className="sm:w-1/2"><Item id={dom("target_years")} label="앞으로 투자할 기간 (년)" changed={has("horizon.target_years")}><NumberInput id={dom("target_years")} min={1} max={10} step={0.5} value={f.target_years} onChange={(v) => set("target_years", v)} /></Item></div>
              <Item label="과거 성과를 확인할 기간" changed={has("horizon.backtest_years", "horizon.start_date")}>
                <div role="radiogroup" aria-label="과거 성과를 확인할 기간" className={twoCols}>
                  {([["recent", "최근 N년", "기준일에서 거슬러 올라가며 검증합니다."], ["range", "특정 기간", "연도를 골라 그 기간을 검증합니다."]] as const).map(([m, name, desc]) => (
                    <label key={m} className={`flex cursor-pointer items-start gap-2 rounded-xl border p-3 transition focus-within:ring-2 focus-within:ring-blue-500 ${f.bt_mode === m ? "border-blue-400 bg-blue-50" : "border-slate-200 bg-white hover:bg-slate-50"}`}>
                      <input type="radio" name="dc-bt-mode" className="mt-1 accent-blue-700" checked={f.bt_mode === m} onChange={() => set("bt_mode", m)} />
                      <span className="min-w-0"><span className={`block text-sm font-semibold ${f.bt_mode === m ? "text-blue-900" : "text-slate-800"}`}>{name}</span><span className="block text-xs text-slate-500">{desc}</span></span>
                    </label>
                  ))}
                </div>
              </Item>
              {f.bt_mode === "recent"
                ? <div className="sm:w-1/2"><Item id={dom("backtest_years")} label="최근 몇 년을 볼까요? (년)" error={errOf("backtest_years")}><NumberInput {...field("backtest_years")} min={1} max={20} step={0.5} value={f.backtest_years} onChange={(v) => set("backtest_years", v)} /></Item></div>
                : (
                  <>
                    <div className={twoCols}>
                      <Item id={dom("bt_start_year")} label="시작 연도" error={errOf("bt_start_year")}><NumberInput {...field("bt_start_year")} min={2000} max={thisYear} value={f.bt_start_year} onChange={(v) => set("bt_start_year", v)} /></Item>
                      <Item id={dom("bt_end_year")} label="끝 연도"><NumberInput id={dom("bt_end_year")} min={2000} max={thisYear} value={f.bt_end_year} onChange={(v) => set("bt_end_year", v)} /></Item>
                    </div>
                    <p className="text-xs leading-5 text-slate-500">끝 연도 12월 말이 분석 기준일이 되어, 그 전 자료만으로 종목을 고릅니다. 저PER·퀄리티·고배당은 재무 자료가 있는 미국 2009-08, 한국 2004-08 이후만 됩니다.</p>
                  </>
                )}
            </SectionCard>
          </>
        ) : tab === "goal" ? (
          <SectionCard title="위험과 목표" desc="분석이 끝나면 결과가 이 기준을 지켰는지 점검합니다.">
            <div className={twoCols}>
              <Item id={dom("risk")} label="투자성향" changed={has("risk.risk_tolerance")}><select id={dom("risk")} className={inputClass} value={f.risk_tolerance} onChange={(e) => set("risk_tolerance", e.target.value as Form["risk_tolerance"])}>{(opt?.risk_tolerance ?? ["conservative", "moderate", "aggressive"]).map((x) => <option key={x} value={x}>{ko(x)}</option>)}</select></Item>
              <Item id={dom("benchmark")} label="비교지수" changed={has("risk.benchmark")}><select id={dom("benchmark")} className={inputClass} value={f.benchmark} onChange={(e) => set("benchmark", e.target.value)}>{(opt?.benchmarks ?? ["SPY", "QQQ", "069500.KS"]).map((b) => <option key={b} value={b}>{benchName(b)}</option>)}</select></Item>
              <Item id={dom("drawdown")} label="손실 감내 수준 (%)" changed={has("risk.max_drawdown_tolerance")}><NumberInput id={dom("drawdown")} min={5} max={90} value={f.max_drawdown_pct} onChange={(v) => set("max_drawdown_pct", v)} /></Item>
              <Item id={dom("target_return")} label="목표 연수익률 (%)" changed={has("risk.target_annual_return")}><NumberInput id={dom("target_return")} min={0} max={100} value={f.target_return_pct} onChange={(v) => set("target_return_pct", v)} /></Item>
            </div>
          </SectionCard>
        ) : tab === "stocks" ? (
          <>
            <SectionCard title="투자 대상과 종목 수">
              <Item label="투자 대상 지수" changed={has("constraints.universe")} error={errOf("universe")}>
                <div className="flex flex-wrap gap-2">{(opt?.universes ?? ["SP500", "NASDAQ100", "KOSPI200"]).map((u, i) => (
                  <label key={u} className={`flex cursor-pointer items-center gap-2 rounded-xl border px-3 py-2 focus-within:ring-2 focus-within:ring-blue-500 ${f.universe.includes(u) ? "border-blue-400 bg-blue-50 text-blue-900" : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"}`}><input id={i === 0 ? dom("universe") : undefined} type="checkbox" className="accent-blue-700" checked={f.universe.includes(u)} onChange={(e) => set("universe", e.target.checked ? [...f.universe, u] : f.universe.filter((x) => x !== u))} />{ko(u)}</label>
                ))}</div>
              </Item>
              <div className="sm:w-1/2"><Item id={dom("num_target")} label="목표 종목 수" changed={has("constraints.num_holdings.target") || (has("constraints.num_holdings") && f.num_target !== nh.target)} error={targetErr} help={`최소 ${f.num_min} ~ 최대 ${f.num_max}개 사이로 정합니다`}><NumberInput id={dom("num_target")} aria-invalid={targetErr ? true : undefined} aria-describedby={targetErr ? `${dom("num_target")}-error` : undefined} min={2} max={50} value={f.num_target} onChange={(v) => set("num_target", v)} /></Item></div>
            </SectionCard>
            <SectionCard title="비중 상한">
              <div className={twoCols}>
                <Item id={dom("max_stock_pct")} label="종목당 상한 (%)" changed={has("constraints.max_weight_per_stock")} error={errOf("max_stock_pct")}><NumberInput {...field("max_stock_pct")} min={1} max={100} value={f.max_stock_pct} onChange={(v) => set("max_stock_pct", v)} /></Item>
                <Item id={dom("max_sector_pct")} label="섹터당 상한 (%)" changed={has("constraints.max_weight_per_sector")} error={errOf("max_sector_pct")}><NumberInput {...field("max_sector_pct")} min={1} max={100} value={f.max_sector_pct} onChange={(v) => set("max_sector_pct", v)} /></Item>
              </div>
            </SectionCard>
            <AdvCard title="종목 수 범위" summary={`최소 ${f.num_min} ~ 최대 ${f.num_max}`} count={countAdv("range")} open={isOpen("range")} onToggle={() => toggle("range")}>
              <div className={twoCols}>
                <Item id={dom("num_min")} label="최소 종목 수" changed={has("constraints.num_holdings") && f.num_min !== nh.min} error={errOf("num_min")}><NumberInput {...field("num_min")} min={2} max={50} value={f.num_min} onChange={(v) => set("num_min", v)} /></Item>
                <Item id={dom("num_max")} label="최대 종목 수" changed={has("constraints.num_holdings") && f.num_max !== nh.max}><NumberInput id={dom("num_max")} min={2} max={50} value={f.num_max} onChange={(v) => set("num_max", v)} /></Item>
              </div>
            </AdvCard>
            <AdvCard title="제외 조건" summary={excludeSummary} count={countAdv("exclude")} open={isOpen("exclude")} onToggle={() => toggle("exclude")}>
              <Item id={dom("exclude")} label="제외 종목 (티커, 쉼표로 구분)" changed={has("constraints.exclude_tickers")} help="예: TSLA, 005930.KS"><input id={dom("exclude")} className={inputClass} value={f.exclude} onChange={(e) => set("exclude", e.target.value)} /></Item>
              <Item id={dom("exclude_themes")} label="제외 테마 (영문, 쉼표로 구분)" changed={has("constraints.exclude_themes")} help="예: tobacco, gambling, weapons. 비우면 제외 없음"><input id={dom("exclude_themes")} className={inputClass} value={f.exclude_themes} onChange={(e) => set("exclude_themes", e.target.value)} /></Item>
              <Item id={dom("exclude_sectors")} label="제외 섹터 (쉼표로 구분)" changed={has("constraints.exclude_sectors")} help="예: 금융, 에너지"><input id={dom("exclude_sectors")} className={inputClass} value={f.exclude_sectors} onChange={(e) => set("exclude_sectors", e.target.value)} /></Item>
            </AdvCard>
            <AdvCard title="종목 규모 하한" summary={`시가총액 ${usdFloor(Math.round(f.min_market_cap_b * 1e9))} · 거래대금 ${usdFloor(Math.round(f.min_adv_m * 1e6))}`} count={countAdv("floor")} open={isOpen("floor")} onToggle={() => toggle("floor")}>
              <div className={twoCols}>
                <Item id={dom("cap")} label="최소 시가총액 (십억 USD)" changed={has("constraints.min_market_cap_usd")} help="0 이면 제한 없음"><NumberInput id={dom("cap")} min={0} step={0.5} value={f.min_market_cap_b} onChange={(v) => set("min_market_cap_b", v)} /></Item>
                <Item id={dom("adv")} label="최소 일평균 거래대금 (백만 USD)" changed={has("constraints.min_avg_daily_volume_usd")} help="0 이면 제한 없음"><NumberInput id={dom("adv")} min={0} step={1} value={f.min_adv_m} onChange={(v) => set("min_adv_m", v)} /></Item>
              </div>
            </AdvCard>
            <AdvCard title="현금·리밸런싱" summary={`현금 ${f.min_cash_pct}% · ${rebalanceText({ count: f.rebalance_count, unit: f.rebalance_unit as Rebalance["unit"] })}`} count={countAdv("cash")} open={isOpen("cash")} onToggle={() => toggle("cash")}>
              <div className={twoCols}>
                <Item id={dom("cash")} label="최소 현금 비율 (%)" changed={has("constraints.min_cash_ratio")}><NumberInput id={dom("cash")} min={0} max={90} value={f.min_cash_pct} onChange={(v) => set("min_cash_pct", v)} /></Item>
                <Item label="리밸런싱 (0 = 매수 후 보유)" changed={has("constraints.rebalance")}>
                  <div className="grid grid-cols-2 gap-2"><NumberInput aria-label="리밸런싱 간격" min={0} value={f.rebalance_count} onChange={(v) => set("rebalance_count", v)} /><select aria-label="리밸런싱 단위" className={inputClass} value={f.rebalance_unit} onChange={(e) => set("rebalance_unit", e.target.value)}>{(opt?.rebalance_units ?? ["2w", "1m", "1q", "6m", "1y"]).map((u) => <option key={u} value={u}>{ko(u)}</option>)}</select></div>
                </Item>
              </div>
            </AdvCard>
          </>
        ) : (
          <SectionCard title="투자 전략">
            <div className={twoCols}>
              <Item id={dom("template")} label="어떤 기업에 투자할까요?" changed={has("strategy_preference.template")} help={thisTemplate?.desc}><select id={dom("template")} className={inputClass} value={f.template} onChange={(e) => set("template", e.target.value as Template)}>{(opt?.templates ?? ["momentum", "low_per", "quality", "low_volatility", "high_dividend"]).map((x) => <option key={x} value={x}>{TEMPLATE_INFO[x] ? templateLabel(x) : ko(x)}</option>)}</select></Item>
              <Item id={dom("weighting")} label="투자금을 어떻게 나눌까요?" changed={has("strategy_preference.baseline_weighting")} help={thisWeighting?.desc}><select id={dom("weighting")} className={inputClass} value={f.weighting} onChange={(e) => set("weighting", e.target.value as Weighting)}>{(opt?.weightings ?? ["equal_weight", "market_cap", "inverse_volatility", "min_variance"]).map((x) => <option key={x} value={x}>{WEIGHTING_INFO[x] ? weightingLabel(x) : ko(x)}</option>)}</select></Item>
            </div>
            <Item label="뉴스·공시 반영" changed={has("strategy_preference.use_news_tilt")} help={NEWS_INFO.caution}><label className="flex cursor-pointer items-start gap-2"><input type="checkbox" className="mt-1 accent-blue-700" checked={f.use_news_tilt} onChange={(e) => set("use_news_tilt", e.target.checked)} /><span>{NEWS_INFO.title}</span></label></Item>
          </SectionCard>
        )}
      </div>
    </DetailDialogShell>
  )
}
