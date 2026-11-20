import { useState } from "react"
import { ArrowRight, ChevronRight, RotateCcw } from "lucide-react"
import { navigate } from "../../app/router"
import type { DialogState, ProfileView, ReportRow } from "../../api/types"
import { proposedNameOf, type ProposedSectorPick } from "../../api/proposed"
import { date, ko, pct } from "../../lib/format"
import { reportName } from "../../lib/reportName"
import { tendencyLabel } from "../../lib/tendency"
import type { Resource } from "../../state/useResource"
import { money, pctText } from "../profile/format"  // 내 투자조건 화면과 같은 표기 (1,000만원 · 10%)
import { MockTag } from "../report/proposedView"
import { ProcessSteps } from "./ProcessSteps"
import type { SectorTrendsState } from "./sectorTrends"

export type InfoTab = "request" | "process" | "trends" | "profile" | "reports"

/** 둘러보기 단계(data-tour) → 그 대상이 들어 있는 탭. 둘러보기가 그 단계로 가면 탭을 바꿔 대상이 보이게 한다 */
export const TOUR_TAB: Record<string, InfoTab> = { "home-process": "process", "home-trends": "trends", "home-profile": "profile", "home-reports": "reports" }

const LINK = "inline-flex items-center gap-1 text-13 font-semibold text-accent hover:underline"
const returnTone = (v: number) => (v >= 0 ? "text-up" : "text-down")

/** 저장된 기본 투자조건을 화면에 쓰는 글로 (내 투자조건 화면과 같은 표기) */
export function profileRows(profile: ProfileView) {
  const p = profile.profile
  const c = p.capital
  const monthly = c.monthly_contribution > 0 ? `매달 ${money(c.monthly_contribution, c.currency)}` : ""
  const amount = c.initial_amount > 0 ? [money(c.initial_amount, c.currency), monthly].filter(Boolean).join(" · ") : monthly || money(0, c.currency)
  const years = `${p.horizon.target_years}년`
  const rows: [string, string][] = [
    ["금액", amount],
    ["기간", years],
    ["성향", `${tendencyLabel({ final: p.diagnosis?.final_tendency, code: p.risk.risk_tolerance })} · 손실 감내 ${pctText(p.risk.max_drawdown_tolerance)}`],
    ["투자 대상", p.constraints.universe.map(ko).join(" · ")],
    ["종목 고르기", `${ko(p.strategy_preference.template)} · ${ko(p.strategy_preference.baseline_weighting)} · 종목당 최대 ${pctText(p.constraints.max_weight_per_stock)}`],
  ]
  return { amount, years, rows }
}

/**
 * 홈 오른쪽 카드 「내게 맞는 정보」: 이렇게 진행돼요 · 요즘 강한 섹터 · 내 투자조건 · 최근 리포트를 탭으로 본다.
 * 어느 탭을 먼저 열지는 HomeScreen 이 정한다 (리포트가 없으면 「이렇게 진행돼요」). tab 이 null 이면 아직 정하는 중이라 내용을 비워 둔다.
 */
export function HomeInfo({ tab, setTab, trends, market, busy, onPrompt, profile, pick, reports, request }: {
  tab: InfoTab | null; setTab: (t: InfoTab) => void
  trends: SectorTrendsState; market: "US" | "KR"; busy: boolean; onPrompt: (idea: string) => void
  profile: ProfileView; pick: ProposedSectorPick | null; reports: Resource<ReportRow[]>
  /** 새 분석 요청 중이면 그 요청 (첫 탭 「이번 요청 조건」이 생긴다). undefined = 요청 없음, null = 불러오는 중 */
  request?: DialogState | null
}) {
  const tabs: { id: InfoTab; label: string }[] = [
    ...(request !== undefined ? [{ id: "request" as const, label: "이번 요청 조건" }] : []),
    // 질문에 답하는 동안은 위쪽 1~5 단계 표시가 같은 내용이라 빼서 탭을 4개 이하로 (좁은 패널에서 한 줄)
    ...(request === undefined ? [{ id: "process" as const, label: "이렇게 진행돼요" }] : []),
    ...(trends.supported ? [{ id: "trends" as const, label: "요즘 강한 섹터" }] : []),
    { id: "profile", label: "내 투자조건" },
    { id: "reports", label: "최근 리포트" },
  ]
  const { amount, years } = profileRows(profile)
  return (
    <section aria-labelledby="home-foryou" className="@container flex min-w-0 flex-col rounded-card bg-surface px-6 py-6">
      <h2 id="home-foryou" className="t-heading">내게 맞는 정보</h2>
      <p className="mt-1 t-body">내 투자조건과 최근 시장을 바탕으로 보여드립니다</p>
      <div role="tablist" aria-label="내게 맞는 정보" className="mt-5 flex gap-4 border-b border-line @md:gap-6">
        {tabs.map((t) => (
          <button key={t.id} type="button" role="tab" id={`home-tab-${t.id}`} aria-selected={tab === t.id} aria-controls="home-panel" onClick={() => setTab(t.id)}
            className={`-mb-px whitespace-nowrap border-b-2 px-0.5 pb-3 text-13 font-semibold transition @md:text-14 ${tab === t.id ? "border-main text-main" : "border-transparent text-sub hover:text-main"}`}>{t.label}</button>
        ))}
      </div>
      <div role="tabpanel" id="home-panel" aria-labelledby={tab ? `home-tab-${tab}` : undefined} className="min-h-0 flex-1 pt-5">
        {tab === "request" && request !== undefined && <RequestConditions st={request} />}
        {tab === "process" && <div data-tour="home-process"><ProcessSteps amount={amount} years={years} /></div>}
        {tab === "trends" && trends.supported && <TrendsPanel trends={trends} market={market} busy={busy} onPrompt={onPrompt} />}
        {tab === "profile" && <ProfilePanel profile={profile} pick={pick} />}
        {tab === "reports" && <ReportsPanel reports={reports} />}
      </div>
    </section>
  )
}

/** 이번 요청 조건: 기본 투자조건과 달라진 조건(값 · 원래 값)과 전체 조건(묶음별). 값은 서버가 만든 ConditionRow 그대로 */
function RequestConditions({ st }: { st: DialogState | null }) {
  const rows = (st?.conditions ?? []).filter((r) => r.group_ko !== "아이디어")
  if (!rows.length) return <div className="rounded-box bg-sunken p-5"><p className="t-body">아이디어를 해석하면 이번 요청의 조건이 여기에 보여요.</p></div>
  const changed = rows.filter((r) => r.changed)
  const groups = [...new Set(rows.map((r) => r.group_ko))]
  return (
    <div className="space-y-3">
      <div className="rounded-box bg-sunken p-5">
        <h3 className="text-14 font-bold text-main">기본 투자조건과 달라진 조건 {changed.length}개</h3>
        {changed.length ? (
          <ul className="mt-3 space-y-2.5">
            {changed.map((r) => (
              <li key={r.field} className="grid grid-cols-[104px_minmax(0,1fr)] gap-3 text-14">
                <span className="text-sub">{r.label_ko}</span>
                <span className="min-w-0 break-words"><b className="font-semibold text-main">{r.value_ko}</b>{r.profile_value_ko != null && <span className="block t-meta">기본 {r.profile_value_ko}</span>}</span>
              </li>
            ))}
          </ul>
        ) : <p className="mt-2 t-body">달라진 항목이 없어요. 기본 투자조건을 그대로 씁니다.</p>}
      </div>
      <details className="group rounded-box bg-sunken p-5">
        <summary className="cursor-pointer list-none text-14 font-bold text-main">전체 조건 보기 <span className="font-normal text-sub">{rows.length}개 항목</span><ChevronRight className="ml-1 inline size-4 text-hint transition group-open:rotate-90" aria-hidden /></summary>
        <div className="mt-3 space-y-4">
          {groups.map((g) => (
            <section key={g}>
              <h4 className="t-label">{g}</h4>
              <dl className="mt-1.5 space-y-1.5 text-14">
                {rows.filter((r) => r.group_ko === g).map((r) => <div key={r.field} className="grid grid-cols-[104px_minmax(0,1fr)] gap-3"><dt className="text-sub">{r.label_ko}</dt><dd className="min-w-0 break-words font-semibold text-main">{r.value_ko}</dd></div>)}
              </dl>
            </section>
          ))}
        </div>
      </details>
    </div>
  )
}

/** 요즘 강한 섹터: 왼쪽에서 섹터를 고르면 오른쪽에 그 섹터에서 많이 오른 종목이 나오고, 아래 문장을 누르면 그 문장으로 분석을 시작한다 */
function TrendsPanel({ trends, market, busy, onPrompt }: { trends: SectorTrendsState; market: "US" | "KR"; busy: boolean; onPrompt: (idea: string) => void }) {
  const markets = trends.data?.markets ?? []
  const [code, setCode] = useState<"US" | "KR">(market)
  const [picked, setPicked] = useState<string | null>(null)
  const m = markets.find((x) => x.code === code) ?? markets[0] ?? null
  const rows = m ? m.top.flatMap((c) => m.sectors.filter((s) => s.code === c)) : []
  const cur = rows.find((r) => r.code === picked) ?? rows[0] ?? null

  if (!m) {  // 자료가 아직 없다: 불러오는 중이면 진행률, 실패면 다시 시도
    const loadingPct = Math.round(Math.max(0, Math.min(1, trends.progress)) * 100)
    return (
      <div data-tour="home-trends" className="rounded-box bg-sunken p-5">
        {trends.status === "error"
          ? <>
              <p className="t-body">섹터 자료를 불러오지 못했습니다.</p>
              <button type="button" onClick={trends.retry} className={`${LINK} mt-2`}><RotateCcw className="size-3.5" aria-hidden />다시 시도</button>
            </>
          : <>
              <div role="progressbar" aria-label="섹터 자료 불러오는 중" aria-valuemin={0} aria-valuemax={100} aria-valuenow={loadingPct} className="h-1.5 overflow-hidden rounded-full bg-line">
                <div className="h-full rounded-full bg-accent transition-[width] duration-300" style={{ width: `${loadingPct}%` }} />
              </div>
              <p className="mt-2 t-meta tabular-nums">불러오는 중 {loadingPct}%</p>
            </>}
      </div>
    )
  }
  return (
    <div>
      {/* 패널이 좁으면(448px 미만) 섹터 목록 아래에 종목 목록, 넓으면 나란히 */}
      <div className="grid grid-cols-1 gap-3 @md:grid-cols-2">
        <div data-tour="home-trends" className="rounded-box bg-sunken p-3">
          <div className="flex items-center justify-between gap-2 px-2 pb-2">
            <h3 className="text-14 font-bold text-main">많이 오른 섹터</h3>
            {markets.length > 1 && (
              <div role="group" aria-label="시장" className="flex rounded-[10px] bg-line p-0.5">
                {markets.map((x) => (
                  <button key={x.code} type="button" aria-pressed={x.code === m.code} onClick={() => { setCode(x.code); setPicked(null) }}
                    className={`whitespace-nowrap rounded-chip px-2.5 py-0.5 text-12 font-semibold transition ${x.code === m.code ? "bg-surface text-main" : "text-sub hover:text-main"}`}>{x.label_ko}</button>
                ))}
              </div>
            )}
          </div>
          {rows.length === 0 && <p className="px-2 py-2 text-13 text-body">최근 한 달은 시장 평균보다 많이 오른 섹터가 없습니다.</p>}
          <ul aria-label="많이 오른 섹터">
            {rows.map((r) => (
              <li key={r.code}>
                <button type="button" aria-pressed={r.code === cur?.code} onClick={() => setPicked(r.code)}
                  className={`flex w-full items-center justify-between gap-2 rounded-control px-2 py-2 text-left transition ${r.code === cur?.code ? "bg-surface" : "hover:bg-sunken-hover"}`}>
                  <span className="min-w-0"><span className="block truncate t-strong">{r.name_ko}</span><span className="block t-meta">{r.n}개 중 {r.up}개 상승</span></span>
                  <span className={`shrink-0 text-14 font-bold tabular-nums ${returnTone(r.avg_return)}`}>{pct(r.avg_return)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-box bg-sunken p-5">
          <h3 className="text-14 font-bold text-main">{cur ? `${cur.name_ko}에서 많이 오른 종목` : "많이 오른 종목"}</h3>
          <p className="mt-0.5 t-meta">최근 한 달 · 기준일 {m.end_date}</p>
          {cur && cur.leaders.length > 0 ? (
            <ul aria-label="많이 오른 종목" className="mt-3 space-y-2.5">
              {cur.leaders.slice(0, 4).map((l) => (
                <li key={l.ticker} className="flex items-center justify-between gap-2 text-14">
                  <span className="min-w-0 truncate"><span className="font-semibold text-main">{l.ticker}</span> <span className="text-body">{l.name}</span></span>
                  <span className={`shrink-0 font-bold tabular-nums ${returnTone(l.return)}`}>{pct(l.return)}</span>
                </li>
              ))}
            </ul>
          ) : <p className="mt-3 text-13 text-body">보여 줄 종목이 없습니다.</p>}
        </div>
      </div>
      {cur && <>
        <p className="mt-6 text-13 font-bold text-main">이렇게 시작해 보세요</p>
        <button type="button" data-tour="home-trend-prompt" disabled={busy} onClick={() => onPrompt(cur.prompt_ko)}
          className="mt-2.5 inline-flex items-center gap-2 rounded-control bg-sunken px-4 py-2.5 text-left text-14 text-main transition hover:bg-sunken-hover disabled:cursor-not-allowed disabled:opacity-50">{cur.prompt_ko}<ArrowRight className="size-4 shrink-0 text-hint" aria-hidden /></button>
      </>}
    </div>
  )
}

/** 내 투자조건: 저장된 기본 투자조건 항목·값, 필수 포함·제외 종목, 맨 아래 투자성향에 맞춘 섹터 (섹터 자료가 있을 때) */
function ProfilePanel({ profile, pick }: { profile: ProfileView; pick: ProposedSectorPick | null }) {
  const c = profile.profile.constraints
  const { rows } = profileRows(profile)
  const tickers = c.must_include_tickers.length + c.exclude_tickers.length > 0
  return (
    <div data-tour="home-profile" className="rounded-box bg-sunken p-5">
      <dl className="grid grid-cols-[88px_minmax(0,1fr)] gap-x-3 gap-y-3 text-14">
        {rows.map(([k, v]) => <div key={k} className="contents"><dt className="text-sub">{k}</dt><dd className="font-semibold text-main">{v}</dd></div>)}
      </dl>
      {tickers && (
        <div className="mt-4 flex flex-wrap gap-1.5">
          {c.must_include_tickers.map((t) => <span key={`in-${t}`} className="rounded-full bg-surface px-2.5 py-1 text-12 font-semibold text-accent">{t} 필수 포함</span>)}
          {c.exclude_tickers.map((t) => <span key={t} className="rounded-full bg-surface px-2.5 py-1 text-12 font-semibold text-danger">{t} 제외</span>)}
        </div>
      )}
      {pick && <p data-testid="tendency-sector" className="mt-4 border-t border-line pt-4 t-body">{pick.text_ko}</p>}
      <button type="button" onClick={() => navigate({ page: "profile" })} className={`${LINK} mt-5`}>내 투자조건 보기<ChevronRight className="size-4" aria-hidden /></button>
    </div>
  )
}

/** 최근 리포트 다섯 개와 전체 보기 */
function ReportsPanel({ reports }: { reports: Resource<ReportRow[]> }) {
  return (
    <div data-tour="home-reports" className="rounded-box bg-sunken p-2">
      {reports.status === "error" && <p className="px-3 py-2 text-13 text-danger">{reports.error}</p>}
      {(reports.data ?? []).slice(0, 5).map((r) => (
        <button key={r.run_id} type="button" onClick={() => navigate({ page: "report", reportId: r.report_id ?? r.run_id })} className="flex w-full items-center justify-between gap-2 rounded-control px-3 py-2.5 text-left transition hover:bg-surface">
          <span className="min-w-0"><span className="block truncate t-strong">{reportName(r)}{proposedNameOf(r) && <MockTag />}</span><span className="mt-0.5 block t-meta">{date(r.created_at)} · 기준일 {r.as_of}</span></span>
          <ChevronRight className="size-4 shrink-0 text-hint" aria-hidden />
        </button>
      ))}
      {reports.status === "ready" && (reports.data ?? []).length === 0 && <p className="px-3 py-2 t-body">아직 완료된 분석이 없습니다.</p>}
      <button type="button" onClick={() => navigate({ page: "reports" })} className={`${LINK} px-3 py-2`}>전체 보기<ChevronRight className="size-4" aria-hidden /></button>
    </div>
  )
}
