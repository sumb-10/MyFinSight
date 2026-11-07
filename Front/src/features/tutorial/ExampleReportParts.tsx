import { Compass } from "lucide-react"
import { navigate } from "../../app/router"
import { Button, Dialog } from "../../ui"
import { EXAMPLE_REPORT_ID, EXAMPLE_ROW, setExampleHidden } from "./exampleReport"

export const openExample = () => navigate({ page: "report", reportId: EXAMPLE_REPORT_ID })

/** 「예시」 표시 (목록·사이드바에서 실제 리포트와 구분) */
export function ExampleBadge() {
  return <span className="mr-1.5 inline-flex items-center rounded-full border border-blue-200 bg-blue-50 px-1.5 py-px align-[1px] text-[10px] font-bold text-blue-800">예시</span>
}

/** 예시 리포트 지우기 확인. 서버는 부르지 않고 이 브라우저의 목록에서만 숨긴다. */
export function DeleteExampleDialog({ close, onDeleted }: { close: () => void; onDeleted?: () => void }) {
  return (
    <Dialog title="예시 리포트를 목록에서 지울까요?" close={close}>
      <div className="space-y-2 px-6 py-5 text-sm leading-6 text-slate-700">
        <p><b className="text-slate-950">「{EXAMPLE_ROW.name}」</b>를 리포트 목록에서 지웁니다.</p>
        <p className="text-slate-600">홈의 「리포트 보는 법 둘러보기」로 언제든 다시 볼 수 있고, 리포트 목록 아래 「예시 리포트 다시 보이기」로 되돌릴 수 있어요.</p>
      </div>
      <div className="flex justify-end gap-2 border-t border-slate-200 px-6 py-4">
        <Button variant="neutral" onClick={close}>취소</Button>
        <Button variant="destructive" onClick={() => { setExampleHidden(true); close(); onDeleted?.() }}>확인</Button>
      </div>
    </Dialog>
  )
}

/** 리포트 목록 아래 작은 복원 링크 */
export function RestoreExampleLink() {
  return (
    <p className="text-center text-sm text-slate-500">
      <button type="button" onClick={() => setExampleHidden(false)} className="inline-flex items-center gap-1 font-semibold text-blue-700 hover:underline focus:outline-none focus:ring-2 focus:ring-blue-500"><Compass className="size-4" aria-hidden />예시 리포트 다시 보이기</button>
    </p>
  )
}
