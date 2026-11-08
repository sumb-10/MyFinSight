import { useEffect, useState } from "react"
import { createPortal } from "react-dom"
import { navigate, type Route } from "../../app/router"
import { Button, Dialog } from "../../ui"
import { guideRecord, recordGuide } from "./guideRecord"

export type GuideDestination = Extract<Route, { page: "reports" } | { page: "report" }>

/** 가이드를 마친 뒤 돌아갈 곳을 담은 튜토리얼 주소 */
export const tutorialThen = (to: GuideDestination): Route => (to.page === "report" ? { page: "tutorial", reportId: to.reportId } : { page: "tutorial", next: "reports" })

/** 튜토리얼 주소에 담긴 돌아갈 곳 (없으면 null) */
export const guideDestination = (r: Extract<Route, { page: "tutorial" }>): GuideDestination | null => (r.reportId ? { page: "report", reportId: r.reportId } : r.next === "reports" ? { page: "reports" } : null)

/** 안내 창. 예 = 가이드로(시작하면 「본 것」으로 기록된다), 아니요 = 거절 기록 후 원래 가려던 곳으로. 닫기·바깥·Esc 는 기록 없이 창만 닫고 그 자리에 머문다. */
function GuidePrompt({ to, close }: { to: GuideDestination; close: () => void }) {
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") close() }
    window.addEventListener("keydown", key)
    return () => window.removeEventListener("keydown", key)
  }, [close])
  const yes = () => { close(); navigate(tutorialThen(to)) }
  const no = () => { recordGuide("declined"); close(); navigate(to) }
  return createPortal(  // 사이드바(sticky)의 쌓임 맥락에 갇히면 리포트의 고정 탭 아래로 깔린다
    <Dialog title="리포트 가이드를 보시겠습니까?" close={close}>
      <p className="px-6 py-5 text-sm leading-6 text-slate-700">예시 리포트로 리포트 보는 법을 안내합니다. 가이드는 홈의 「리포트 보는 법 둘러보기」에서 언제든 다시 볼 수 있습니다.</p>
      <div className="flex justify-end gap-2 border-t border-slate-200 px-6 py-4">
        <Button variant="neutral" onClick={no}>아니요</Button>
        <Button onClick={yes}>예</Button>
      </div>
    </Dialog>,
    document.body,
  )
}

/** 리포트로 가는 이동을 가이드 안내 창으로 한 번 거르는 훅. 본 적도 거절한 적도 없을 때만 창을 띄운다. */
export function useGuideGate() {
  const [pending, setPending] = useState<GuideDestination | null>(null)
  const go = (to: GuideDestination) => { if (guideRecord()) navigate(to); else setPending(to) }
  return { go, dialog: pending && <GuidePrompt to={pending} close={() => setPending(null)} /> }
}
