import { useState } from "react"
import { ArrowRight, ChevronRight, Compass, FileText, Loader2, SlidersHorizontal, X } from "lucide-react"
import { navigate } from "../../app/router"
import { date, pct } from "../../lib/format"
import { reportName } from "../../lib/reportName"
import { ActionError, IdeaPending } from "../analysis/flow"
import { OVERRIDE_LABELS, overrideText } from "../home/DetailConditions"
import { EXAMPLE_IDEAS } from "../home/HomeScreen"
import { ExampleFrame, PAGE, topSectors, trendsEmptyText, useHomeModel, type ExampleVersion, type HomeModel, type ProfileSummary } from "./shared"
import { CARD, QUIET, returnTone } from "./tossParts"
// 토스페이스 원본 (tossface/LICENSE.txt)
import iconIdea from "./tossface/u1F4AC.svg"

type Tab = "trends" | "profile" | "reports"

/** 흰 카드 안의 회색 상자 (테두리 대신 면 색으로 나눈다) */
const BOX = "rounded-[18px] bg-[#F2F5F7]"
const HEAD_BTN = "inline-flex h-8 items-center gap-1.5 rounded-[10px] px-2.5 text-[13px] font-medium text-[#646B77] transition hover:bg-[#F2F5F7] hover:text-[#34383F]"
const LINK = "hp-accent-text inline-flex items-center gap-1 text-[13px] font-semibold hover:underline"

/**
 * [이전 버전] 2026-11-15 단계 표시줄 넣기 전. 되돌리려면 이 파일을 Example3.tsx 로 바꾸고 함수 이름을 Example3 으로 되돌린다.
 * 홈 시안 3 (#/home/3): 좌우 분할. 왼쪽 카드는 아이디어를 적는 곳, 오른쪽 카드는 「내게 맞는 정보」(요즘 강한 섹터 · 내 투자조건 · 최근 리포트)를 탭으로 본다.
 * 차용한 점: 좌우 분할, 가운데 안내 + 예시 묶음, 맞춤 정보 탭, 표 옆의 설명 상자, 「이렇게 시작해 보세요」 문장.
 * 톤은 시안 1 과 같다 (toss.css): 회색 배경 위 흰 카드 두 장, 카드 안은 회색 상자. 남긴 선은 탭 기준선과 선택된 탭 밑줄뿐이다.
 */
export function Example3Prev({ bare, version }: { bare?: boolean; version?: ExampleVersion }) {
  const m = useHomeModel()
  const { busy } = m
  const [tab, setTab] = useState<Tab | null>(null)
  return (
    <ExampleFrame m={m} n={3} theme="toss" bare={bare} version={version}>{(s) => {
      const tabs: { id: Tab; label: string }[] = [...(m.trends.supported ? [{ id: "trends" as const, label: "요즘 강한 섹터" }] : []), { id: "profile", label: "내 투자조건" }, { id: "reports", label: "최근 리포트" }]
      const cur = tab ?? tabs[0].id
      return (
        <div className={`${PAGE} text-[#646B77]`}>
          <div className="grid flex-1 grid-cols-[minmax(0,0.82fr)_minmax(0,1fr)] gap-4">
            <section aria-labelledby="x3-new" className={`${CARD} flex min-w-0 flex-col`}>
              <div className="flex items-center justify-between border-b border-[#E5E8EB] px-6 py-3.5">
                <h1 id="x3-new" className="text-[15px] font-bold text-[#34383F]">새 분석</h1>
                <div className="flex gap-0.5">
                  <button type="button" title="처음이라면 화면을 한 단계씩 안내해요" onClick={() => m.setTour(0)} className={HEAD_BTN}><Compass className="size-4" aria-hidden />둘러보기</button>
                  <button type="button" title="예시 리포트로 읽는 법을 안내해요" onClick={() => navigate({ page: "tutorial" })} className={HEAD_BTN}><FileText className="size-4" aria-hidden />리포트 보는 법</button>
                </div>
              </div>
              <div className="flex flex-1 flex-col items-center justify-center px-8 py-4 text-center">
                <span className="grid size-14 place-items-center rounded-[18px] bg-[#F2F5F7]"><img src={iconIdea} alt="" className="size-8" /></span>
                <h2 className="mt-4 text-[22px] font-extrabold tracking-[-0.02em] text-[#34383F]">투자 아이디어를 적어 주세요</h2>
                <p className="mt-2 max-w-[360px] text-balance break-keep text-[14px] leading-6">내 투자조건에 맞는 종목과 비중을 고르고, 과거 성과와 위험을 리포트로 보여드립니다.</p>
                <ul data-tour="home-examples" aria-label="예시 문장" className="mt-5 flex flex-col items-center gap-2">
                  {EXAMPLE_IDEAS.map((t) => <li key={t}><button type="button" disabled={busy} onClick={() => void m.submit(t)} className={`${QUIET} px-4 py-2.5 text-[14px]`}>{t}</button></li>)}
                </ul>
              </div>
              <div className="p-4">
                {busy && <div className="pb-3"><IdeaPending /></div>}
                {m.apiErr && !busy && <div className="pb-3"><ActionError title="아이디어를 해석하지 못했습니다" message={m.apiErr} retry={() => void m.submit()} /></div>}
                <div data-tour="home-idea" className="rounded-[18px] bg-[#F2F5F7] p-3 transition-shadow focus-within:shadow-[0_0_0_2px_#4880EE]">
                  <textarea value={m.idea} readOnly={busy} aria-busy={busy} aria-label="투자하고 싶은 내용" rows={2} onChange={(e) => m.type(e.target.value)}
                    className="w-full resize-none border-0 bg-transparent px-1 text-[15px] leading-6 text-[#34383F] outline-none placeholder:text-[#646B77]" placeholder="예: 미국과 한국의 반도체 기업에 나눠 투자하고 싶어요." />
                  {m.nOverrides > 0 && (
                    <div className="flex flex-wrap items-center gap-1.5 pt-1">
                      {Object.entries(m.overrides).map(([k, v]) => <span key={k} className="hp-accent-text rounded-full bg-white px-2.5 py-1 text-xs font-semibold">{OVERRIDE_LABELS[k] ?? k} {overrideText(k, v)}</span>)}
                      <button type="button" className="text-xs hover:text-[#34383F] disabled:opacity-40" disabled={busy} onClick={() => m.setOverrides({})}><X className="inline size-3" aria-hidden /> 모두 지우기</button>
                    </div>
                  )}
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <span data-tour="home-detail" className="inline-flex"><button type="button" onClick={() => m.setDetail(true)} disabled={busy} className="inline-flex h-10 items-center gap-1.5 rounded-[12px] px-3 text-[14px] font-semibold text-[#34383F] transition hover:bg-white disabled:opacity-50"><SlidersHorizontal className="size-4" aria-hidden />상세 조건{m.nOverrides ? ` (${m.nOverrides})` : ""}</button></span>
                    <span data-tour="home-submit" className="inline-flex"><button type="button" onClick={() => void m.submit()} disabled={busy} className="hp-btn inline-flex h-10 items-center gap-1.5 rounded-[12px] px-4 text-[14px] font-semibold transition disabled:cursor-not-allowed disabled:opacity-60">{busy ? <><Loader2 className="size-4 animate-spin" aria-hidden />아이디어 해석 중…</> : <>투자조건 확인하기<ChevronRight className="size-4" aria-hidden /></>}</button></span>
                  </div>
                </div>
                {m.error && <p className="pt-2 text-xs font-medium text-red-700">{m.error}</p>}
              </div>
            </section>

            <section aria-labelledby="x3-foryou" className={`${CARD} flex min-w-0 flex-col px-7 py-6`}>
              <h2 id="x3-foryou" className="text-[22px] font-extrabold tracking-[-0.02em] text-[#34383F]">내게 맞는 정보</h2>
              <p className="mt-1 text-[14px]">내 투자조건과 최근 시장을 바탕으로 보여드립니다</p>
              <div role="tablist" aria-label="내게 맞는 정보" className="mt-5 flex gap-6 border-b border-[#E5E8EB]">
                {tabs.map((t) => (
                  <button key={t.id} type="button" role="tab" id={`x3-tab-${t.id}`} aria-selected={cur === t.id} aria-controls="x3-panel" onClick={() => setTab(t.id)}
                    className={`-mb-px border-b-2 px-0.5 pb-3 text-[14px] font-semibold transition ${cur === t.id ? "border-[#34383F] text-[#34383F]" : "border-transparent text-[#646B77] hover:text-[#34383F]"}`}>{t.label}</button>
                ))}
              </div>
              <div role="tabpanel" id="x3-panel" aria-labelledby={`x3-tab-${cur}`} className="min-h-0 flex-1 pt-5">
                {cur === "trends" && <TrendsPanel m={m} s={s} />}
                {cur === "profile" && (
                  <div data-tour="home-profile" className={`${BOX} p-5`}>
                    <dl className="grid grid-cols-[80px_minmax(0,1fr)] gap-x-3 gap-y-3 text-[14px]">
                      {s.rows.map(([k, v]) => <div key={k} className="contents"><dt>{k}</dt><dd className="font-semibold text-[#34383F]">{v}</dd></div>)}
                    </dl>
                    <button type="button" onClick={() => navigate({ page: "profile" })} className={`${LINK} mt-5`}>내 투자조건 보기<ChevronRight className="size-4" aria-hidden /></button>
                  </div>
                )}
                {cur === "reports" && (
                  <div data-tour="home-reports" className={`${BOX} p-2`}>
                    {m.reports.status === "error" && <p className="px-3 py-2 text-[13px] text-red-700">{m.reports.error}</p>}
                    {(m.reports.data ?? []).slice(0, 5).map((r) => (
                      <button key={r.run_id} type="button" onClick={() => navigate({ page: "report", reportId: r.report_id ?? r.run_id })} className="flex w-full items-center justify-between gap-2 rounded-[12px] px-3 py-2.5 text-left transition hover:bg-white">
                        <span className="min-w-0"><span className="block truncate text-[14px] font-semibold text-[#34383F]">{reportName(r)}</span><span className="mt-0.5 block text-[12px]">{date(r.created_at)} · 기준일 {r.as_of}</span></span>
                        <ChevronRight className="size-4 shrink-0 text-[#6B7684]" aria-hidden />
                      </button>
                    ))}
                    {m.reports.status === "ready" && (m.reports.data ?? []).length === 0 && <p className="px-3 py-2 text-[14px]">아직 완료된 분석이 없습니다.</p>}
                    <button type="button" onClick={() => navigate({ page: "reports" })} className={`${LINK} px-3 py-2`}>전체 보기<ChevronRight className="size-4" aria-hidden /></button>
                  </div>
                )}
              </div>
            </section>
          </div>
        </div>
      )
    }}</ExampleFrame>
  )
}

/** 요즘 강한 섹터 탭: 왼쪽 표에서 섹터를 고르면 오른쪽에 그 섹터에서 많이 오른 종목이 나오고, 아래 문장을 누르면 그 문장으로 분석을 시작한다. */
function TrendsPanel({ m, s }: { m: HomeModel; s: ProfileSummary }) {
  const markets = m.trends.data?.markets ?? []
  const [code, setCode] = useState<"US" | "KR">(s.market)
  const [picked, setPicked] = useState<string | null>(null)
  const { end, rows } = topSectors(m.trends, code)
  const cur = rows.find((r) => r.code === picked) ?? rows[0] ?? null
  if (rows.length === 0 && markets.length < 2) return <p data-tour="home-trends" className="text-[14px]">{trendsEmptyText(m.trends)}</p>
  return (
    <div>
      <div className="grid grid-cols-2 gap-3">
        <div data-tour="home-trends" className={`${BOX} p-3`}>
          <div className="flex items-center justify-between gap-2 px-2 pb-2">
            <h3 className="text-[14px] font-bold text-[#34383F]">많이 오른 섹터</h3>
            {markets.length > 1 && (
              <div role="group" aria-label="시장" className="flex rounded-[10px] bg-[#E5E8EB] p-0.5">
                {markets.map((x) => (
                  <button key={x.code} type="button" aria-pressed={x.code === code} onClick={() => { setCode(x.code); setPicked(null) }}
                    className={`rounded-[8px] px-2.5 py-0.5 text-[12px] font-semibold transition ${x.code === code ? "bg-white text-[#34383F]" : "text-[#646B77] hover:text-[#34383F]"}`}>{x.label_ko}</button>
                ))}
              </div>
            )}
          </div>
          {rows.length === 0 && <p className="px-2 py-2 text-[13px]">{trendsEmptyText(m.trends)}</p>}
          <ul>
            {rows.map((r) => (
              <li key={r.code}>
                <button type="button" aria-pressed={r.code === cur?.code} onClick={() => setPicked(r.code)}
                  className={`flex w-full items-center justify-between gap-2 rounded-[12px] px-2 py-2 text-left transition ${r.code === cur?.code ? "bg-white" : "hover:bg-[#E9EDF0]"}`}>
                  <span className="min-w-0"><span className="block truncate text-[14px] font-semibold text-[#34383F]">{r.name_ko}</span><span className="block text-[12px]">{r.n}개 중 {r.up}개 상승</span></span>
                  <span className={`shrink-0 text-[14px] font-bold tabular-nums ${returnTone(r.avg_return)}`}>{pct(r.avg_return)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
        <div className={`${BOX} p-5`}>
          <h3 className="text-[14px] font-bold text-[#34383F]">{cur ? `${cur.name_ko}에서 많이 오른 종목` : "많이 오른 종목"}</h3>
          {end && <p className="mt-0.5 text-[12px]">최근 한 달 · 기준일 {end}</p>}
          {cur && cur.leaders.length > 0 ? (
            <ul className="mt-3 space-y-2.5">
              {cur.leaders.slice(0, 4).map((l) => (
                <li key={l.ticker} className="flex items-center justify-between gap-2 text-[14px]">
                  <span className="min-w-0 truncate"><span className="font-semibold text-[#34383F]">{l.ticker}</span> <span>{l.name}</span></span>
                  <span className={`shrink-0 font-bold tabular-nums ${returnTone(l.return)}`}>{pct(l.return)}</span>
                </li>
              ))}
            </ul>
          ) : <p className="mt-3 text-[13px]">보여 줄 종목이 없습니다.</p>}
        </div>
      </div>
      {cur && <>
        <p className="mt-6 text-[13px] font-bold text-[#34383F]">이렇게 시작해 보세요</p>
        <button type="button" data-tour="home-trend-prompt" disabled={m.busy} onClick={() => void m.submit(cur.prompt_ko)} className={`${QUIET} mt-2.5 inline-flex items-center gap-2 px-4 py-2.5 text-[14px]`}>{cur.prompt_ko}<ArrowRight className="size-4 shrink-0 text-[#6B7684]" aria-hidden /></button>
      </>}
    </div>
  )
}
