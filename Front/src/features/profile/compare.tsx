import { useEffect, useState } from "react"
import { useService } from "../../app/providers"
import { errorMessage } from "../../api/client"
import type { ProfileFields, ProfileVersion, ProfileView } from "../../api/types"
import { Alert, Disclosure, inputClass } from "../../ui"
import { ko } from "../../lib/format"
import { tendencyLabel } from "../../lib/tendency"
import { MockTag } from "../report/proposedView"
import { ASSET_KO, benchName, listText, money, monthlyText, pctText, rebalanceText, usdFloor, yearsText } from "./format"
import { whenText } from "./history"
import { useStockNames } from "./stocks"
import { TEMPLATE_INFO, WEIGHTING_INFO } from "./strategyInfo"

// 투자조건 버전 비교 (제안 기능): 서비스에 getProfileVersion(과거 버전 값 전체)이 있을 때만 — 지금은 목업뿐.
// 값 표시는 저장된 투자조건 화면과 같은 글(format.ts)을 쓴다.

export interface ProfileRow { group: string; key: string; label: string; value: string }

/** 투자조건 한 버전을 비교용 행으로. name = 티커를 「회사명 (티커)」로 바꾸는 함수 (없으면 티커 그대로). */
export function profileRows(p: ProfileFields, name: (t: string) => string = (t) => t): ProfileRow[] {
  const c = p.constraints, sp = p.strategy_preference
  const r = (group: string, key: string, label: string, value: string): ProfileRow => ({ group, key, label, value })
  return [
    r("기본 조건", "capital.initial_amount", "처음 투자할 금액", money(p.capital.initial_amount, p.capital.currency)),
    r("기본 조건", "capital.monthly", "매월 추가 투자금", monthlyText(p.capital)),
    r("기본 조건", "horizon.target_years", "앞으로 투자할 기간", yearsText(p.horizon.target_years)),
    r("기본 조건", "horizon.backtest_years", "과거 성과를 확인할 기간", yearsText(p.horizon.backtest_years)),
    r("기본 조건", "horizon.purpose", "투자 목적", ko(p.horizon.purpose)),
    r("기본 조건", "profile", "나에 대한 참고 정보", `${ko(p.profile.age_band)} · 투자 경험 ${ko(p.profile.investment_experience)} · 금융 지식 ${ko(p.profile.financial_knowledge)} · 자산 중 ${pctText(p.profile.investable_ratio_of_assets)}`),
    r("투자성향", "tendency", "투자성향", tendencyLabel({ final: p.diagnosis?.final_tendency, code: p.risk.risk_tolerance })),
    r("투자성향", "risk.max_drawdown_tolerance", "손실 감내 수준", pctText(p.risk.max_drawdown_tolerance)),
    r("투자성향", "risk.loss_reaction", "손실 시 대응", ko(p.risk.loss_reaction)),
    r("투자성향", "risk.target_annual_return", "목표 연수익률", pctText(p.risk.target_annual_return)),
    r("투자성향", "risk.benchmark", "비교지수", benchName(p.risk.benchmark)),
    r("종목 범위·제약", "constraints.universe", "투자 대상 지수", c.universe.map(ko).join(", ")),
    r("종목 범위·제약", "constraints.num_holdings", "종목 수", `목표 ${c.num_holdings.target}개 (최소 ${c.num_holdings.min} ~ 최대 ${c.num_holdings.max})`),
    r("종목 범위·제약", "constraints.max_weight", "비중 상한", `종목당 최대 ${pctText(c.max_weight_per_stock)} · 섹터당 최대 ${pctText(c.max_weight_per_sector)}`),
    r("종목 범위·제약", "constraints.min_cash_ratio", "최소 현금 비율", pctText(c.min_cash_ratio)),
    r("종목 범위·제약", "constraints.rebalance", "리밸런싱", rebalanceText(c.rebalance)),
    r("종목 범위·제약", "constraints.asset_types", "자산 종류", (c.asset_types ?? ["stock"]).map((a) => ASSET_KO[a] ?? a).join(", ")),
    r("종목 범위·제약", "constraints.exclude_tickers", "제외 종목", listText(c.exclude_tickers.map(name))),
    r("종목 범위·제약", "constraints.must_include_tickers", "반드시 포함할 종목", listText(c.must_include_tickers.map(name))),
    r("종목 범위·제약", "constraints.exclude_sectors", "제외 섹터", listText(c.exclude_sectors)),
    r("종목 범위·제약", "constraints.exclude_themes", "제외 테마", listText(c.exclude_themes)),
    r("종목 범위·제약", "constraints.min_market_cap_usd", "최소 시가총액", usdFloor(c.min_market_cap_usd)),
    r("종목 범위·제약", "constraints.min_avg_daily_volume_usd", "최소 일평균 거래대금", usdFloor(c.min_avg_daily_volume_usd)),
    r("투자 전략", "strategy.template", "어떤 기업을 고를까", TEMPLATE_INFO[sp.template]?.name ?? sp.template),
    r("투자 전략", "strategy.weighting", "투자금을 나누는 방식", WEIGHTING_INFO[sp.baseline_weighting]?.name ?? sp.baseline_weighting),
    r("투자 전략", "strategy.news", "뉴스·공시 반영", sp.use_news_tilt ? "반영" : "반영 안 함"),
    r("투자 전략", "memo", "메모", p.diagnosis?.memo || "없음"),
  ]
}

export interface RowDiff { group: string; key: string; label: string; before: string; after: string; changed: boolean }
export function diffProfiles(a: ProfileFields, b: ProfileFields, name?: (t: string) => string): RowDiff[] {
  const ra = profileRows(a, name)
  return profileRows(b, name).map((x) => { const before = ra.find((y) => y.key === x.key)?.value ?? "–"; return { group: x.group, key: x.key, label: x.label, before, after: x.value, changed: before !== x.value } })
}

/** 두 버전 비교: 기본은 바로 앞 버전 → 고른 버전. 바뀐 항목은 강조, 바뀌지 않은 항목은 접어서 따로. */
export function VersionCompare({ view, to, setTo }: { view: ProfileView; to: number; setTo: (v: number) => void }) {
  const svc = useService()
  const asc = [...view.versions].sort((a, b) => a.version - b.version)
  const prevOf = (v: number) => asc.filter((x) => x.version < v).pop()?.version ?? v
  const [from, setFrom] = useState(prevOf(to))
  const [pair, setPair] = useState<[ProfileVersion, ProfileVersion] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { setFrom(prevOf(to)) }, [to])  // eslint-disable-line react-hooks/exhaustive-deps -- 비교 대상을 바꾸면 기본은 그 앞 버전
  useEffect(() => {
    if (!svc.getProfileVersion) return
    setErr(null)
    void Promise.all([svc.getProfileVersion(from), svc.getProfileVersion(to)]).then((x) => setPair(x as [ProfileVersion, ProfileVersion]), (e) => setErr(errorMessage(e)))
  }, [svc, from, to])
  const all = pair ? [...pair[0].constraints.exclude_tickers, ...pair[0].constraints.must_include_tickers, ...pair[1].constraints.exclude_tickers, ...pair[1].constraints.must_include_tickers] : []
  const name = useStockNames(all) ?? undefined
  const rows = pair ? diffProfiles(pair[0], pair[1], name) : []
  const changed = rows.filter((r) => r.changed), same = rows.filter((r) => !r.changed)
  const opt = (v: ProfileVersion | (typeof asc)[number]) => `버전 ${v.version} · ${whenText(v.created_at)}${v.note ? ` · ${v.note}` : ""}`
  return (
    <section aria-label="버전 비교" className="space-y-4 rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex items-center gap-1 text-sm font-semibold text-slate-900">버전 비교<MockTag /></div>
      <div className="grid grid-cols-1 items-end gap-3 sm:grid-cols-[1fr_auto_1fr]">
        <label className="block text-xs font-semibold text-slate-500">이전<select className={`${inputClass} mt-1`} value={from} onChange={(e) => setFrom(Number(e.target.value))}>{asc.filter((v) => v.version !== to).map((v) => <option key={v.version} value={v.version}>{opt(v)}</option>)}</select></label>
        <span className="hidden pb-3 text-slate-400 sm:block" aria-hidden="true">→</span>
        <label className="block text-xs font-semibold text-slate-500">이후<select className={`${inputClass} mt-1`} value={to} onChange={(e) => setTo(Number(e.target.value))}>{asc.map((v) => <option key={v.version} value={v.version}>{opt(v)}{v.version === view.current_version ? " (현재)" : ""}</option>)}</select></label>
      </div>
      {err && <Alert tone="error" title="버전 값을 불러오지 못했습니다">{err}</Alert>}
      {pair && from === to && <p className="text-sm text-slate-600">같은 버전을 골랐습니다. 다른 버전을 골라 주세요.</p>}
      {pair && from !== to && (
        <>
          <p className="text-sm text-slate-700">버전 {from} → 버전 {to}: <b>바뀐 항목 {changed.length}개</b> · 그대로인 항목 {same.length}개{from > to && <span className="text-slate-500"> (최근 버전에서 예전 버전으로 거꾸로 비교 중)</span>}</p>
          {changed.length ? (
            <ul aria-label="바뀐 항목" className="divide-y divide-amber-100 overflow-hidden rounded-xl border border-amber-200 bg-amber-50/60">
              {changed.map((r) => (
                <li key={r.key} className="flex flex-col gap-1 px-4 py-2.5 sm:flex-row sm:items-baseline sm:gap-4">
                  <span className="shrink-0 text-sm font-semibold text-slate-900 sm:w-44">{r.label}<span className="block text-[11px] font-normal text-slate-500">{r.group}</span></span>
                  <span className="min-w-0 break-words text-sm"><span className="text-slate-500 line-through decoration-slate-300">{r.before}</span><span className="mx-1.5 text-slate-400">→</span><b className="text-slate-950">{r.after}</b></span>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-slate-600">두 버전의 값이 모두 같습니다.</p>}
          {same.length > 0 && (
            <Disclosure size="sm" title={`바뀌지 않은 항목 ${same.length}개`}>
              <dl className="grid grid-cols-1 gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
                {same.map((r) => <div key={r.key} className="min-w-0"><dt className="text-xs text-slate-500">{r.label}</dt><dd className="break-words text-slate-700">{r.after}</dd></div>)}
              </dl>
            </Disclosure>
          )}
        </>
      )}
    </section>
  )
}
