import { useEffect, useState } from "react"
import type { NumHoldings, Options, ProfileVersion, Template, Universe, Weighting } from "../../api/types"
import { useService } from "../../app/providers"
import { useResource } from "../../state/useResource"
import { Button, Dialog, Field, inputClass } from "../../ui"
import { ko } from "../../lib/format"

/** 홈의 "상세 조건": 이번 요청에만 적용할 조건. 프로필은 바꾸지 않고, 프로필과 다른 값만 overrides(필드 경로 → 값)로 보낸다. */
export type Overrides = Record<string, unknown>

type Form = {
  initial_amount: number; currency: "KRW" | "USD"; monthly_contribution: number; contribution_day: number; target_years: number
  bt_mode: "recent" | "range"; backtest_years: number; bt_start_year: number; bt_end_year: number
  risk_tolerance: "conservative" | "moderate" | "aggressive"; max_drawdown_pct: number; target_return_pct: number; benchmark: string
  universe: Universe[]; num_target: number; num_min: number; num_max: number; max_stock_pct: number; max_sector_pct: number; template: Template; weighting: Weighting; use_news_tilt: boolean; exclude: string
  exclude_themes: string; exclude_sectors: string; min_market_cap_b: number; min_adv_m: number; min_cash_pct: number; rebalance_count: number; rebalance_unit: string
}

const thisYear = new Date().getFullYear()

function fromProfile(p: ProfileVersion, ov: Overrides): Form {
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

/** 프로필과 다른 값만 덮어쓰기로 만든다. */
export function toOverrides(f: Form, p: ProfileVersion): Overrides {
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

export const OVERRIDE_LABELS: Record<string, string> = {
  "capital.initial_amount": "투자금", "capital.currency": "통화", "capital.monthly_contribution": "월 적립", "capital.contribution_day": "적립일", "horizon.target_years": "투자기간",
  "horizon.backtest_years": "백테스트 기간", "horizon.start_date": "백테스트 끝(기준일)", "risk.risk_tolerance": "위험 성향", "risk.max_drawdown_tolerance": "허용 낙폭", "risk.target_annual_return": "목표 수익률",
  "risk.benchmark": "비교지수", "constraints.universe": "유니버스", "constraints.num_holdings.target": "종목 수", "constraints.num_holdings": "종목 수", "constraints.max_weight_per_stock": "종목당 상한", "constraints.max_weight_per_sector": "섹터당 상한",
  "strategy_preference.template": "선정 기준", "strategy_preference.baseline_weighting": "기준 비중", "strategy_preference.use_news_tilt": "뉴스 반영", "constraints.exclude_tickers": "제외 종목",
  "constraints.exclude_themes": "제외 테마", "constraints.exclude_sectors": "제외 섹터", "constraints.min_market_cap_usd": "최소 시가총액", "constraints.min_avg_daily_volume_usd": "최소 거래대금", "constraints.min_cash_ratio": "최소 현금", "constraints.rebalance": "리밸런싱",
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

export function DetailConditionsDialog({ profile, initial, onApply, close, title = "이번 분석의 상세 조건", applyLabel = "이 조건 적용", intro }: { profile: ProfileVersion; initial: Overrides; onApply: (o: Overrides) => void; close: () => void; title?: string; applyLabel?: string; intro?: string }) {
  const svc = useService()
  const options = useResource(() => svc.options(), [svc])
  const opt: Options | null = options.data
  const [f, setF] = useState<Form>(() => fromProfile(profile, initial))
  const [err, setErr] = useState<string>("")
  useEffect(() => { setF(fromProfile(profile, initial)) }, [profile, initial])
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((x) => ({ ...x, [k]: v }))
  const check = (): string => {
    if (!(f.initial_amount > 0)) return "투자금은 0보다 커야 합니다"
    if (f.bt_mode === "range" && !(f.bt_start_year <= f.bt_end_year)) return "백테스트 시작 연도가 끝 연도보다 늦습니다"
    if (f.bt_mode === "range" && f.bt_end_year - f.bt_start_year + 1 > 20) return "백테스트는 최대 20년입니다"
    if (f.bt_mode === "recent" && !(f.backtest_years > 0 && f.backtest_years <= 20)) return "백테스트 기간은 0보다 크고 20년 이하입니다"
    if (!f.universe.length) return "유니버스를 하나 이상 고르세요"
    if (f.max_sector_pct < f.max_stock_pct) return "섹터당 상한은 종목당 상한 이상이어야 합니다"
    if (!(f.num_min <= f.num_target && f.num_target <= f.num_max)) return "종목 수는 최소 ≤ 목표 ≤ 최대 순서여야 합니다"
    if (f.max_stock_pct * f.num_min < 100 - f.min_cash_pct) return `종목당 상한 × 최소 종목 수가 투자 비율보다 작아 돈을 다 배분할 수 없습니다 (상한을 ${Math.ceil((100 - f.min_cash_pct) / f.num_min)}% 이상으로 올리거나 최소 종목 수를 늘려 주세요)`
    return ""
  }
  const apply = () => { const e = check(); setErr(e); if (e) return; onApply(toOverrides(f, profile)); close() }
  const tpl = opt?.labels_ko?.templates ?? {}
  const wt = opt?.labels_ko?.weightings ?? {}
  return (
    <Dialog title={title} close={close}>
      <div className="space-y-5 text-sm text-slate-700">
        <p>{intro ?? "프로필의 기본 조건을 이번 요청에서만 바꿉니다. 프로필 자체는 그대로입니다. 바꾼 항목은 조건 확인 화면에 파란색으로 표시됩니다."}</p>
        <section className="space-y-3">
          <h3 className="text-xs font-bold tracking-wider text-slate-400">자금·기간</h3>
          <div className="grid grid-cols-4 gap-3">
            <Field label="투자금"><input className={inputClass} inputMode="numeric" value={f.initial_amount.toLocaleString("ko-KR")} onChange={(e) => set("initial_amount", Number(e.target.value.replace(/\D/g, "")))} /></Field>
            <Field label="통화"><select className={inputClass} value={f.currency} onChange={(e) => set("currency", e.target.value as "KRW" | "USD")}><option value="KRW">원 (KRW)</option><option value="USD">달러 (USD)</option></select></Field>
            <Field label="월 적립 (0이면 없음)"><input className={inputClass} inputMode="numeric" value={f.monthly_contribution.toLocaleString("ko-KR")} onChange={(e) => set("monthly_contribution", Number(e.target.value.replace(/\D/g, "")))} /></Field>
            <Field label="적립일 (매월)"><input className={inputClass} type="number" min={1} max={28} value={f.contribution_day} onChange={(e) => set("contribution_day", Number(e.target.value))} /></Field>
          </div>
          <div className="grid grid-cols-[120px_1fr] gap-3">
            <Field label="투자기간 (년)"><input className={inputClass} type="number" min={1} max={10} step={0.5} value={f.target_years} onChange={(e) => set("target_years", Number(e.target.value))} /></Field>
            <Field label="백테스트 기간" help="특정 기간을 고르면 그 끝 연도 12월 말이 분석 기준일이 되어, 그 전 자료만으로 종목을 고릅니다. 저PER·퀄리티·고배당은 재무 자료가 있는 미국 2009-08, 한국 2004-08 이후만 됩니다.">
              <div className="flex flex-wrap items-center gap-2">
                <label className="flex items-center gap-1"><input type="radio" checked={f.bt_mode === "recent"} onChange={() => set("bt_mode", "recent")} />최근</label>
                <input className={`${inputClass} w-20`} type="number" min={1} max={20} step={0.5} value={f.backtest_years} disabled={f.bt_mode !== "recent"} onChange={(e) => set("backtest_years", Number(e.target.value))} /><span>년</span>
                <label className="ml-3 flex items-center gap-1"><input type="radio" checked={f.bt_mode === "range"} onChange={() => set("bt_mode", "range")} />특정 기간</label>
                <input className={`${inputClass} w-24`} type="number" min={2000} max={thisYear} value={f.bt_start_year} disabled={f.bt_mode !== "range"} onChange={(e) => set("bt_start_year", Number(e.target.value))} /><span>년 ~</span>
                <input className={`${inputClass} w-24`} type="number" min={2000} max={thisYear} value={f.bt_end_year} disabled={f.bt_mode !== "range"} onChange={(e) => set("bt_end_year", Number(e.target.value))} /><span>년</span>
              </div>
            </Field>
          </div>
        </section>
        <section className="space-y-3">
          <h3 className="text-xs font-bold tracking-wider text-slate-400">위험·비교</h3>
          <div className="grid grid-cols-4 gap-3">
            <Field label="위험 성향"><select className={inputClass} value={f.risk_tolerance} onChange={(e) => set("risk_tolerance", e.target.value as Form["risk_tolerance"])}>{(opt?.risk_tolerance ?? ["conservative", "moderate", "aggressive"]).map((x) => <option key={x} value={x}>{ko(x)}</option>)}</select></Field>
            <Field label="허용 최대 낙폭 (%)"><input className={inputClass} type="number" min={5} max={90} value={f.max_drawdown_pct} onChange={(e) => set("max_drawdown_pct", Number(e.target.value))} /></Field>
            <Field label="목표 연수익률 (%)"><input className={inputClass} type="number" min={0} max={100} value={f.target_return_pct} onChange={(e) => set("target_return_pct", Number(e.target.value))} /></Field>
            <Field label="비교지수"><select className={inputClass} value={f.benchmark} onChange={(e) => set("benchmark", e.target.value)}>{(opt?.benchmarks ?? ["SPY", "QQQ", "069500.KS"]).map((b) => <option key={b} value={b}>{b}</option>)}</select></Field>
          </div>
        </section>
        <section className="space-y-3">
          <h3 className="text-xs font-bold tracking-wider text-slate-400">종목 범위·제약</h3>
          <div className="grid grid-cols-[1fr_210px_120px_120px] gap-3">
            <Field label="유니버스">
              <div className="flex flex-wrap gap-2 pt-1">{(opt?.universes ?? ["SP500", "NASDAQ100", "KOSPI200"]).map((u) => (
                <label key={u} className={`flex items-center gap-1 rounded-lg border px-2 py-1 ${f.universe.includes(u) ? "border-blue-300 bg-blue-50" : "border-slate-200"}`}><input type="checkbox" checked={f.universe.includes(u)} onChange={(e) => set("universe", e.target.checked ? [...f.universe, u] : f.universe.filter((x) => x !== u))} />{ko(u)}</label>
              ))}</div>
            </Field>
            <Field label="종목 수 (목표 · 최소~최대)" help="목표를 바꾸면 최소·최대가 따라 맞춰집니다">
              <div className="flex items-center gap-1">
                <input className={inputClass} type="number" min={2} max={50} value={f.num_target} aria-label="목표 종목 수" onChange={(e) => { const t = Number(e.target.value); setF((x) => ({ ...x, num_target: t, num_min: Math.min(x.num_min, t), num_max: Math.max(x.num_max, t) })) }} />
                <input className={`${inputClass} w-16`} type="number" min={2} max={50} value={f.num_min} aria-label="최소 종목 수" onChange={(e) => set("num_min", Number(e.target.value))} /><span className="text-slate-400">~</span>
                <input className={`${inputClass} w-16`} type="number" min={2} max={50} value={f.num_max} aria-label="최대 종목 수" onChange={(e) => set("num_max", Number(e.target.value))} />
              </div>
            </Field>
            <Field label="종목당 상한 (%)"><input className={inputClass} type="number" min={1} max={100} value={f.max_stock_pct} onChange={(e) => set("max_stock_pct", Number(e.target.value))} /></Field>
            <Field label="섹터당 상한 (%)"><input className={inputClass} type="number" min={1} max={100} value={f.max_sector_pct} onChange={(e) => set("max_sector_pct", Number(e.target.value))} /></Field>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <Field label="제외 종목 (티커, 쉼표로 구분)" help="예: TSLA, 005930.KS"><input className={inputClass} value={f.exclude} onChange={(e) => set("exclude", e.target.value)} /></Field>
            <Field label="제외 테마 (영문, 쉼표로 구분)" help="예: tobacco, gambling, weapons. 비우면 제외 없음"><input className={inputClass} value={f.exclude_themes} onChange={(e) => set("exclude_themes", e.target.value)} /></Field>
            <Field label="제외 섹터 (쉼표로 구분)" help="예: 금융, 에너지"><input className={inputClass} value={f.exclude_sectors} onChange={(e) => set("exclude_sectors", e.target.value)} /></Field>
          </div>
          <div className="grid grid-cols-4 gap-3">
            <Field label="최소 시가총액 (십억 USD)" help="0 이면 제한 없음"><input className={inputClass} type="number" min={0} step={0.5} value={f.min_market_cap_b} onChange={(e) => set("min_market_cap_b", Number(e.target.value))} /></Field>
            <Field label="최소 일평균 거래대금 (백만 USD)" help="0 이면 제한 없음"><input className={inputClass} type="number" min={0} step={1} value={f.min_adv_m} onChange={(e) => set("min_adv_m", Number(e.target.value))} /></Field>
            <Field label="최소 현금 비율 (%)"><input className={inputClass} type="number" min={0} max={90} value={f.min_cash_pct} onChange={(e) => set("min_cash_pct", Number(e.target.value))} /></Field>
            <Field label="리밸런싱 (0 = 매수 후 보유)">
              <div className="flex gap-2"><input className={`${inputClass} w-16`} type="number" min={0} value={f.rebalance_count} onChange={(e) => set("rebalance_count", Number(e.target.value))} /><select className={inputClass} value={f.rebalance_unit} onChange={(e) => set("rebalance_unit", e.target.value)}>{(opt?.rebalance_units ?? ["2w", "1m", "1q", "6m", "1y"]).map((u) => <option key={u} value={u}>{ko(u)}</option>)}</select></div>
            </Field>
          </div>
        </section>
        <section className="space-y-3">
          <h3 className="text-xs font-bold tracking-wider text-slate-400">전략</h3>
          <div className="grid grid-cols-3 gap-3">
            <Field label="선정 기준" help="모멘텀=12개월 수익률, 저PER, 퀄리티=ROE, 저변동성, 고배당"><select className={inputClass} value={f.template} onChange={(e) => set("template", e.target.value as Template)}>{(opt?.templates ?? ["momentum", "low_per", "quality", "low_volatility", "high_dividend"]).map((x) => <option key={x} value={x}>{tpl[x] ?? ko(x)}</option>)}</select></Field>
            <Field label="기준 비중"><select className={inputClass} value={f.weighting} onChange={(e) => set("weighting", e.target.value as Weighting)}>{(opt?.weightings ?? ["equal_weight", "market_cap", "inverse_volatility", "min_variance"]).map((x) => <option key={x} value={x}>{wt[x] ?? ko(x)}</option>)}</select></Field>
            <Field label="뉴스 반영 (Black-Litterman)"><label className="flex items-center gap-2 pt-2"><input type="checkbox" checked={f.use_news_tilt} onChange={(e) => set("use_news_tilt", e.target.checked)} />기준일 직전 2주 뉴스로 비중 조정</label></Field>
          </div>
        </section>
        {err && <p className="text-sm font-medium text-red-600">{err}</p>}
        <div className="flex items-center justify-between">
          <Button variant="ghost" onClick={() => { onApply({}); close() }}>프로필 기본값으로 되돌리기</Button>
          <div className="flex gap-2"><Button variant="ghost" onClick={close}>취소</Button><Button onClick={apply}>{applyLabel}</Button></div>
        </div>
      </div>
    </Dialog>
  )
}
