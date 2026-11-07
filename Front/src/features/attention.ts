import { useEffect, useMemo } from "react"
import type { PaperSummary, ReportRow } from "../api/types"
import { useService } from "../app/providers"
import { initPapers, initReports, loadSeen, markRebalanceSeen, useSeen } from "../lib/seen"
import { useResource } from "../state/useResource"
import { freshRebalance } from "./paper/rebalance"

// 사이드바 숫자 배지와 목록 표시: 새로 완료된 리포트, 확인하지 않은 리밸런싱이 있는 모의투자.
// 확인 기록은 이 브라우저에만 있다 (lib/seen.ts). 서버 데이터는 읽기만 한다.

export const reportKey = (r: Pick<ReportRow, "report_id" | "run_id">) => r.report_id ?? r.run_id

/** 아직 열어 보지 않은 리포트(키 = 화면 주소의 reportId). 처음이면 지금 있는 리포트는 본 것으로 두고 시작한다. */
export function useNewReports(rows: ReportRow[] | null | undefined): Set<string> {
  const svc = useService()
  const seen = useSeen(svc.mode)
  useEffect(() => { if (rows) initReports(svc.mode, rows.map(reportKey), svc.seenSeed?.()) }, [svc, rows])
  return useMemo(() => new Set(seen.reports === null ? [] : (rows ?? []).map(reportKey).filter((k) => !seen.reports!.includes(k))), [rows, seen])
}

const checked = new Map<string, Promise<boolean>>()  // 같은 (모의투자, 리밸런싱 수, 확인 번호) 는 한 번만 상세를 불러 확인한다

/** 확인하지 않은 리밸런싱 거래가 있는 모의투자 ID.
 *  목록의 리밸런싱 수가 확인한 번호보다 큰 모의투자만 상세를 불러, 실제로 거래한 리밸런싱인지 본다 (중지 중 건너뛴 리밸런싱은 알리지 않고 확인 처리). */
export function useRebalanceAlerts(papers: PaperSummary[] | null | undefined): Set<string> {
  const svc = useService()
  const seen = useSeen(svc.mode)
  useEffect(() => { if (papers) initPapers(svc.mode, papers, svc.seenSeed?.()) }, [svc, papers])
  const cands = (papers ?? []).filter((p) => seen.papers[p.paper_id] !== undefined && p.n_rebalances > seen.papers[p.paper_id])
  const key = cands.map((p) => `${p.paper_id}:${p.n_rebalances}:${seen.papers[p.paper_id]}`).join(",")
  const res = useResource(() => Promise.all(cands.map(async (p) => {
    const at = seen.papers[p.paper_id]
    const k = `${svc.mode}:${p.paper_id}:${p.n_rebalances}:${at}`
    if (!checked.has(k)) checked.set(k, svc.getPaper(p.paper_id).then((d) => {
      const fresh = !!freshRebalance(d, at)
      if (!fresh && (loadSeen(svc.mode).papers[p.paper_id] ?? -1) === at) markRebalanceSeen(svc.mode, p.paper_id, p.n_rebalances)  // 거래 없는 리밸런싱만 늘었다 → 알릴 것 없음
      return fresh
    }).catch(() => false))
    return (await checked.get(k)!) ? p.paper_id : null
  })), [svc, key])
  return useMemo(() => new Set((key && res.data ? res.data : []).filter((x): x is string => !!x)), [key, res.data])
}
