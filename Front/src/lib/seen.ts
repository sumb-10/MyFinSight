import { useEffect, useState } from "react"

// 「확인함」 기록: 새로 완료된 리포트를 열어 봤는지, 모의투자의 리밸런싱 거래를 확인했는지.
// 서버에는 사용자별 읽음 상태가 없어 이 브라우저에만 저장하고 서버로 보내지 않는다 (다른 기기·브라우저와 공유되지 않음).
// 일반 모드는 localStorage(브라우저를 닫아도 남음), 목업 모드는 sessionStorage(목업 상태처럼 탭을 닫거나 초기화하면 처음으로).
// 처음 켤 때 이미 있던 리포트·리밸런싱은 확인한 것으로 두고 시작한다 — 그 뒤에 새로 생긴 것만 알린다.

export type SeenScope = "api" | "mock"
export interface SeenState { v: 1; reports: string[] | null; papers: Record<string, number> }  // papers: 모의투자별로 확인한 마지막 리밸런싱 번호(seq)
/** 목업 전용: 처음 켤 때 '확인 안 함'으로 둘 항목 (시연용). 일반 모드에는 없다. */
export interface SeenSeed { unseenReports: string[]; papers: Record<string, number> }

export const SEEN_KEYS: Record<SeenScope, string> = { api: "myfinsight.seen.v1", mock: "myfinsight.mock.seen.v1" }
const SEEN_EVENT = "myfinsight:seen"

const store = (scope: SeenScope): Storage | null => { try { return scope === "mock" ? window.sessionStorage : window.localStorage } catch { return null } }

export function loadSeen(scope: SeenScope): SeenState {
  try {
    const raw = store(scope)?.getItem(SEEN_KEYS[scope])
    if (raw) { const s = JSON.parse(raw) as SeenState; if (s?.v === 1) return { v: 1, reports: Array.isArray(s.reports) ? s.reports : null, papers: s.papers && typeof s.papers === "object" ? s.papers : {} } }
  } catch { /* 깨진 기록은 처음 상태로 */ }
  return { v: 1, reports: null, papers: {} }
}

function save(scope: SeenScope, s: SeenState) {
  try { store(scope)?.setItem(SEEN_KEYS[scope], JSON.stringify(s)) } catch { /* 저장이 막혀 있어도 화면은 계속 (알림만 다시 보일 수 있음) */ }
  window.dispatchEvent(new Event(SEEN_EVENT))
}

/** 처음 보는 리포트 목록이면(기록 없음) 지금 있는 리포트를 모두 확인한 것으로 둔다. seed 의 리포트만 '새 리포트'로 남긴다 (목업). */
export function initReports(scope: SeenScope, ids: string[], seed?: SeenSeed | null) {
  const s = loadSeen(scope)
  if (s.reports !== null) return
  save(scope, { ...s, reports: ids.filter((id) => !seed?.unseenReports.includes(id)) })
}

/** 처음 보는 모의투자는 지금까지의 리밸런싱을 확인한 것으로 둔다 (seed 에 번호가 있으면 그 번호, 목업). */
export function initPapers(scope: SeenScope, papers: { paper_id: string; n_rebalances: number }[], seed?: SeenSeed | null) {
  const s = loadSeen(scope)
  const add = papers.filter((p) => s.papers[p.paper_id] === undefined)
  if (!add.length) return
  save(scope, { ...s, papers: { ...s.papers, ...Object.fromEntries(add.map((p) => [p.paper_id, Math.min(p.n_rebalances, seed?.papers[p.paper_id] ?? p.n_rebalances)])) } })
}

export function markReportSeen(scope: SeenScope, id: string) {
  const s = loadSeen(scope)
  if (s.reports === null || s.reports.includes(id)) return
  save(scope, { ...s, reports: [...s.reports, id] })
}

export function markRebalanceSeen(scope: SeenScope, paperId: string, seq: number) {
  const s = loadSeen(scope)
  if ((s.papers[paperId] ?? -1) >= seq) return
  save(scope, { ...s, papers: { ...s.papers, [paperId]: seq } })
}

/** 확인 기록이 바뀔 때(이 탭·다른 탭) 다시 그리게 하는 값. */
export function useSeen(scope: SeenScope): SeenState {
  const [s, setS] = useState(() => loadSeen(scope))
  useEffect(() => {
    const on = () => setS(loadSeen(scope))
    on()
    window.addEventListener(SEEN_EVENT, on)
    window.addEventListener("storage", on)
    return () => { window.removeEventListener(SEEN_EVENT, on); window.removeEventListener("storage", on) }
  }, [scope])
  return s
}
