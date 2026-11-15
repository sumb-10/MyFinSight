import { useLayoutEffect, useState, type ReactNode } from "react"
import { Compass, FileText, Sparkles } from "lucide-react"
import { useProfile, useService } from "../../app/providers"
import { navigate, type Route } from "../../app/router"
import { errorMessage } from "../../api/client"
import type { ProfileView } from "../../api/types"
import type { ProposedSectorRow } from "../../api/proposed"
import { useResource } from "../../state/useResource"
import { saveUi } from "../../state/uiStorage"
import { ErrorState, Loading } from "../../ui"
import { ko } from "../../lib/format"
import { tendencyLabel } from "../../lib/tendency"
import { money, pctText } from "../profile/format"
import { DetailConditionsDialog, type Overrides } from "../home/DetailConditions"
import { scopeOf, useSectorTrends, type SectorTrendsState } from "../home/sectorTrends"
import { useRenameTick } from "../report/ReportName"
import { Coachmark } from "../tutorial/Coachmark"
import { HOME_TOUR_STEPS } from "../tutorial/homeSteps"
import "./shared.css"

// 홈 화면 시안(예시 페이지)들이 같이 쓰는 부분: 자료·동작(useHomeModel), 화면 틀(ExampleFrame), 시안 전환 막대.
// 기존 홈(features/home/HomeScreen.tsx)과 같은 서비스 호출을 쓰므로 시안에서도 입력 → 조건 확인 흐름이 실제로 동작한다.

export type ExampleRoute = Extract<Route, { page: "home-example" }>

/** 시안 목록 (전환 막대에 보이는 순서). 시안을 더하거나 빼면 여기와 index.tsx 를 같이 고친다. */
export const HOME_EXAMPLES: { n: number; label: string }[] = [
  { n: 0, label: "기존 구성" },
  { n: 1, label: "결과 흐름" },
  { n: 2, label: "시작 카드" },
  { n: 3, label: "분할 화면" },
  { n: 4, label: "기능 안내" },
]

/**
 * 분석 순서 5단계. 문구는 소개 화면(노션 「튜토리얼 개선 사항」, 팀원 브랜치 tutorial-improve 의 IntroScroll)과 같은 순서·뜻을 짧게 줄인 것이다.
 * 소개 화면과 홈이 같은 말을 쓰게, 시안들은 단계 문구를 여기서만 가져다 쓴다. short·note 는 좁은 자리(시안 3 진행 표시줄)용 짧은 이름과 한 줄 메모.
 */
export const PROCESS_STEPS: { title: string; body: string; short: string; note: string }[] = [
  { title: "아이디어 적기", body: "평소 말로 한 줄이면 돼요", short: "아이디어", note: "지금 여기" },
  { title: "질문에 답하기", body: "빠진 조건만, 보기 중에서 골라요", short: "질문 답하기", note: "보기 중 선택" },
  { title: "조건 확인", body: "「분석 시작」을 눌러야 실행돼요", short: "조건 확인", note: "확인해야 시작" },
  { title: "분석·검증", body: "보통 5~10분 걸려요", short: "분석·검증", note: "보통 5~10분" },
  { title: "리포트·모의투자", body: "실제 돈 없이 따라가 봐요", short: "리포트", note: "+ 모의투자" },
]

/**
 * 소개 화면(#/intro)이 main 에 있는가. 팀원 브랜치(tutorial-improve)가 합쳐지기 전에는 그 주소가 「없는 페이지」라서 링크를 숨긴다.
 * 합쳐진 뒤 true 로 바꾸면 안내 링크에 「MyFinSight 소개」가 나타난다 (주소는 router 에 그 경로가 생기면 그대로 쓴다).
 */
export const INTRO_READY = false

/** 처음 쓰는 사람을 위한 안내 링크 (소개 화면 마지막 장의 세 가지 선택과 같은 순서): MyFinSight 소개 · 예시 리포트 · 화면 둘러보기 */
export function GuideLinks({ m, className = "", linkClass }: { m: HomeModel; className?: string; linkClass: string }) {
  return (
    <div className={`flex shrink-0 gap-1 ${className}`}>
      {INTRO_READY && <button type="button" onClick={() => { window.location.hash = "#/intro" }} className={linkClass}><Sparkles className="size-4" aria-hidden />MyFinSight 소개</button>}
      <button type="button" title="리포트 읽는 법을 단계별로 안내해요" onClick={() => navigate({ page: "tutorial" })} className={linkClass}><FileText className="size-4" aria-hidden />예시 리포트</button>
      <button type="button" title="홈 화면의 각 부분을 짚어 줘요" onClick={() => m.setTour(0)} className={linkClass}><Compass className="size-4" aria-hidden />화면 둘러보기</button>
    </div>
  )
}

/** 홈의 자료와 동작. 기존 홈과 달리 입력 초안을 저장하지 않는다 (시안이 기존 홈의 초안을 건드리지 않게). */
export function useHomeModel() {
  const svc = useService()
  const { profile, status, error: profileError, reload } = useProfile()
  const trends = useSectorTrends(svc)
  const [idea, setIdea] = useState("")
  const [error, setError] = useState("")      // 입력 확인 (5자 미만)
  const [apiErr, setApiErr] = useState("")    // 서버가 요청을 만들지 못함
  const [busy, setBusy] = useState(false)
  const [overrides, setOverrides] = useState<Overrides>({})
  const [detail, setDetail] = useState(false)
  const [tour, setTour] = useState<number | null>(null)
  const renamed = useRenameTick()
  const reports = useResource(() => svc.listReports(), [svc, renamed])

  /** text 를 주면(예시·추천 문장) 그 문장으로 바로 시작한다 */
  const submit = async (text: string = idea) => {
    const t = text.trim()
    if (t.length < 5) { setError("분석할 투자 아이디어를 5자 이상 입력해주세요."); return }
    setIdea(text); setBusy(true); setError(""); setApiErr("")
    try {
      const st = await svc.createRequest({ idea: t, mode: "new", overrides })
      saveUi({ activeRequestId: st.request_id })
      navigate({ page: "clarify", requestId: st.request_id })
    } catch (e) { setApiErr(errorMessage(e)) } finally { setBusy(false) }
  }
  const type = (v: string) => { setIdea(v); setError("") }

  return { svc, profile, status, profileError, reload, trends, idea, type, error, apiErr, busy, overrides, setOverrides, nOverrides: Object.keys(overrides).length, detail, setDetail, tour, setTour, reports, submit }
}
export type HomeModel = ReturnType<typeof useHomeModel>

/** 저장된 기본 투자조건을 화면에 쓰는 글로 (기존 홈 카드와 같은 표기) */
export function profileSummary(profile: ProfileView) {
  const p = profile.profile
  const c = p.capital
  const monthly = c.monthly_contribution > 0 ? `매달 ${money(c.monthly_contribution, c.currency)}` : ""
  const amount = c.initial_amount > 0 ? [money(c.initial_amount, c.currency), monthly].filter(Boolean).join(" · ") : monthly || money(0, c.currency)
  const years = `${p.horizon.target_years}년`
  const tendency = tendencyLabel({ final: p.diagnosis?.final_tendency, code: p.risk.risk_tolerance })
  const universe = p.constraints.universe.map(ko).join(" · ")
  const rows: [string, string][] = [["금액", amount], ["기간", years], ["성향", `${tendency} · 손실 감내 ${pctText(p.risk.max_drawdown_tolerance)}`], ["투자 대상", universe]]
  const market: "US" | "KR" = scopeOf(p.constraints.universe) === "KR" ? "KR" : "US"
  return { p, amount, years, tendency, universe, rows, market, line: [amount, years, tendency, universe].join(" · ") }
}
export type ProfileSummary = ReturnType<typeof profileSummary>

/** 그 시장에서 최근 한 달 성과가 좋았던 섹터 (최대 3개, 기존 홈 상자와 같은 규칙) */
export function topSectors(trends: SectorTrendsState, code: "US" | "KR"): { end: string | null; rows: ProposedSectorRow[] } {
  const markets = trends.data?.markets ?? []
  const m = markets.find((x) => x.code === code) ?? markets[0] ?? null
  return { end: m?.end_date ?? null, rows: m ? m.top.flatMap((c) => m.sectors.filter((s) => s.code === c)) : [] }
}

/** 섹터 자료가 없을 때의 한 줄 (불러오는 중 · 실패 · 오른 섹터 없음) */
export const trendsEmptyText = (trends: SectorTrendsState) =>
  trends.status === "error" ? "섹터 자료를 불러오지 못했습니다." : !trends.data ? "섹터 자료를 불러오는 중입니다…" : "최근 한 달은 시장 평균보다 많이 오른 섹터가 없습니다."

/** 시안 화면의 바깥 틀: 16:9 화면 한 장에 들어오게 높이를 채운다. 맨 아래에는 전환 막대(와 목업 모드 띠)가 들어갈 만큼 남긴다 */
export const PAGE = "flex min-h-[calc(100vh-7.5rem)] flex-col"

/** 이 시안이 켜져 있는 동안만 <html data-home-example="…"> 을 달아 그 톤(toss.css)을 사이드바까지 적용한다. 화면을 떠나면 지운다. */
export function useExampleTheme(theme?: "toss", color?: "mix" | "all") {
  useLayoutEffect(() => {
    const d = document.documentElement.dataset
    if (theme) d.homeExample = theme
    if (color === "all") d.homeExampleColor = "all"
    return () => { delete d.homeExample; delete d.homeExampleColor }
  }, [theme, color])
}

/** 시안의 새 버전 / 이전 버전 전환 (이전 버전이 남아 있는 시안만). go: 그 시안의 다른 주소 값(구성·색)을 지킨 채 버전만 바꾼다 */
export interface ExampleVersion { prev: boolean; go: (prev: boolean) => void }

/** 시안 공통 틀. 프로필을 불러온 뒤 children(요약)을 그리고, 상세 조건 대화상자·둘러보기·전환 막대를 붙인다. theme·color: useExampleTheme */
export function ExampleFrame({ m, n, theme, color, bare, options, version, children }: { m: HomeModel; n: number; theme?: "toss"; color?: "mix" | "all"; bare?: boolean; options?: ReactNode; version?: ExampleVersion; children: (s: ProfileSummary) => ReactNode }) {
  useExampleTheme(theme, color)

  if (m.status === "loading") return <Loading />
  if (m.status === "error") return <ErrorState title="분석 서버에 연결할 수 없습니다" message={m.profileError ?? ""} retry={() => void m.reload()} />
  if (!m.profile) return null  // App 이 투자조건 설정으로 보낸다
  const s = profileSummary(m.profile)
  return (
    <div className="home-example">
      {children(s)}
      {m.detail && <DetailConditionsDialog profile={s.p} initial={m.overrides} onApply={m.setOverrides} close={() => m.setDetail(false)} />}
      {m.tour !== null && (
        <Coachmark steps={HOME_TOUR_STEPS} index={m.tour} onClose={() => m.setTour(null)}
          onPrev={() => m.setTour((i) => Math.max(0, (i ?? 0) - 1))} onNext={() => m.setTour((i) => (i === null || i >= HOME_TOUR_STEPS.length - 1 ? null : i + 1))} />
      )}
      {!bare && (
        <ExampleSwitch n={n}>
          {version && <SwitchGroup label="버전" items={[{ label: "새 버전", on: !version.prev, go: () => version.go(false) }, { label: "이전 버전", on: version.prev, go: () => version.go(true) }]} />}
          {options}
        </ExampleSwitch>
      )}
    </div>
  )
}

const segClass = (on: boolean) => `rounded-[8px] px-2.5 py-1 font-semibold transition ${on ? "bg-[#FFFFFF] text-[#34383F]" : "text-[#D5DAE0] hover:text-[#FFFFFF]"}`

/** 전환 막대 안의 묶음 하나 (둘 중 하나 고르기) */
export function SwitchGroup({ label, items }: { label: string; items: { label: string; on: boolean; go: () => void }[] }) {
  return (
    <div role="group" aria-label={label} className="flex rounded-[10px] bg-[#4A4F58] p-0.5">
      {items.map((it) => <button key={it.label} type="button" aria-pressed={it.on} onClick={it.go} className={segClass(it.on)}>{it.label}</button>)}
    </div>
  )
}

/** 시안 전환 막대 (시안의 일부가 아님). 주소에 bare=1 을 붙이면 숨는다. 색을 직접 적어 어느 톤에서도 같게 보인다. */
export function ExampleSwitch({ n, children }: { n: number; children?: ReactNode }) {
  return (
    <aside aria-label="시안 전환" className="home-example fixed bottom-1 left-[260px] z-40 flex items-center gap-3 rounded-[14px] bg-[#34383F] px-3.5 py-1 text-[13px] text-[#FFFFFF] shadow-lg">
      <span className="font-semibold">홈 시안</span>
      <SwitchGroup label="시안" items={HOME_EXAMPLES.map((e) => ({ label: `${e.n} ${e.label}`, on: e.n === n, go: () => navigate({ page: "home-example", n: e.n }) }))} />
      {children}
      <button type="button" onClick={() => navigate({ page: "home" })} className="rounded-[8px] px-2 py-1 font-semibold text-[#D5DAE0] hover:text-[#FFFFFF]">기존 홈</button>
    </aside>
  )
}
