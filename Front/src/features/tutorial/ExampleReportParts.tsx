import { useState } from "react"
import { Compass } from "lucide-react"
import { navigate } from "../../app/router"
import { Alert, Button, Dialog, Field, inputClass } from "../../ui"
import { EXAMPLE_NAME_MAX, EXAMPLE_REPORT_ID, EXAMPLE_ROW, exampleCustomName, exampleName, setExampleHidden, setExampleName } from "./exampleReport"

export const openExample = () => navigate({ page: "report", reportId: EXAMPLE_REPORT_ID })

/** 「예시」 표시 (목록·사이드바에서 실제 리포트와 구분). 좁은 칸에서도 한 줄로. */
export function ExampleBadge() {
  return <span className="mr-1.5 inline-flex shrink-0 items-center whitespace-nowrap rounded-full border border-blue-200 bg-blue-50 px-1.5 py-px align-[1px] text-[10px] font-bold text-blue-800">예시</span>
}

/** 예시 리포트 지우기 확인. 서버는 부르지 않고 이 브라우저의 목록에서만 숨긴다. */
export function DeleteExampleDialog({ close, onDeleted }: { close: () => void; onDeleted?: () => void }) {
  return (
    <Dialog title="예시 리포트를 목록에서 지울까요?" close={close}>
      <div className="space-y-2 px-6 py-5 text-sm leading-6 text-slate-700">
        <p><b className="text-slate-950">「{exampleName()}」</b> 예시 리포트를 리포트 목록에서 지웁니다.</p>
        <p className="text-slate-600">홈의 「리포트 보는 법 둘러보기」로 언제든 다시 볼 수 있고, 리포트 목록 아래 「예시 리포트 다시 보이기」로 되돌릴 수 있어요.</p>
      </div>
      <div className="flex justify-end gap-2 border-t border-slate-200 px-6 py-4">
        <Button variant="neutral" onClick={close}>취소</Button>
        <Button variant="destructive" onClick={() => { setExampleHidden(true); close(); onDeleted?.() }}>확인</Button>
      </div>
    </Dialog>
  )
}

/** 예시 리포트 이름 바꾸기 (일반 리포트의 이름 바꾸기 창과 같은 모양). 이 브라우저에만 저장한다. */
export function RenameExampleDialog({ close }: { close: () => void }) {
  const [value, setValue] = useState(exampleName)
  const [error, setError] = useState<string | null>(null)
  const custom = exampleCustomName()
  const save = (next: string | null) => {
    if (next !== null && !next.trim()) { setError("이름을 입력해 주세요. 기본 이름을 쓰려면 ‘기본 이름으로 되돌리기’를 누르세요."); return }
    setExampleName(next); close()
  }
  return (
    <Dialog title="리포트 이름 바꾸기" close={close}>
      <form className="space-y-4 p-4 text-sm text-slate-700 sm:p-6" onSubmit={(e) => { e.preventDefault(); save(value) }}>
        <Field label="리포트 이름" help={`최대 ${EXAMPLE_NAME_MAX}자`}>
          <input className={inputClass} value={value} maxLength={EXAMPLE_NAME_MAX} autoFocus onChange={(e) => { setValue(e.target.value); setError(null) }} />
        </Field>
        <p className="break-words text-xs leading-5 text-slate-500">기본 이름: <b className="font-semibold text-slate-700">{EXAMPLE_ROW.name}</b>{custom && " · 지금은 직접 정한 이름을 쓰고 있습니다"}</p>
        {error && <Alert tone="error" title="저장하지 못했습니다">{error}</Alert>}
        <div className="flex flex-wrap justify-between gap-2 border-t border-slate-200 pt-4">
          <Button variant="ghost" onClick={() => save(null)} disabled={!custom}>기본 이름으로 되돌리기</Button>
          <div className="flex gap-2">
            <Button variant="neutral" onClick={close}>취소</Button>
            <Button type="submit" disabled={value.trim() === exampleName()}>저장</Button>
          </div>
        </div>
      </form>
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
