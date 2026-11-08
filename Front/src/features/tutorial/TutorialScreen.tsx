import { useCallback, useEffect, useMemo, useState } from "react"
import { Compass, FileText, Home, Pencil, Trash2 } from "lucide-react"
import { ServiceContext } from "../../app/providers"
import { navigate } from "../../app/router"
import type { ReportDoc } from "../../api/types"
import { Button, ErrorState, Loading } from "../../ui"
import { ReportDetail } from "../report/ReportDetail"
import { Coachmark } from "./Coachmark"
import { DeleteExampleDialog, RenameExampleDialog } from "./ExampleReportParts"
import { useExample } from "./exampleReport"
import type { GuideDestination } from "./GuidePrompt"
import { recordGuide } from "./guideRecord"
import { TOUR_STEPS } from "./steps"
import { createTutorialService, loadTutorialDoc, TUTORIAL_REPORT_ID } from "./tutorialService"

/** 예시 리포트 화면. 두 가지로 연다.
 *  - 「리포트 보는 법 둘러보기」(#/tutorial, startTour): 코치마크로 단계별로 안내한다.
 *  - 목록의 「[예시]」 리포트(#/reports/example): 일반 리포트처럼 열고, 띠의 버튼으로 둘러보기를 시작할 수 있다. 더보기에서 목록에서 지울 수 있다.
 *  실제 서버·목업 서비스와 상관없이 예시 데이터만 쓰고, 쓰기 동작은 모두 막는다. */
export function TutorialScreen({ load = loadTutorialDoc, startTour = true, after = null }: { load?: () => Promise<ReportDoc>; startTour?: boolean; after?: GuideDestination | null }) {
  const [doc, setDoc] = useState<ReportDoc | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [step, setStep] = useState(0)
  const [touring, setTouring] = useState(startTour)
  const [done, setDone] = useState(false)
  const [removing, setRemoving] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const ex = useExample()
  useEffect(() => {
    let alive = true
    load().then((d) => { if (alive) setDoc(d) }, (e) => { if (alive) setErr(e instanceof Error ? e.message : String(e)) })
    return () => { alive = false }
  }, [load])
  const svc = useMemo(() => (doc ? createTutorialService(doc) : null), [doc])
  useEffect(() => { if (startTour) recordGuide("seen") }, [startTour])  // 둘러보기를 시작하면 「본 것」: 안내 창을 다시 띄우지 않는다
  const close = useCallback(() => { setTouring(false); setDone(true); if (after) navigate(after) }, [after])  // 마치기·건너뛰기·Esc 모두. 돌아갈 곳이 있으면 바로 이동
  const next = useCallback(() => { if (step >= TOUR_STEPS.length - 1) close(); else setStep((s) => s + 1) }, [step, close])
  const prev = useCallback(() => setStep((s) => Math.max(0, s - 1)), [])
  const restart = () => { recordGuide("seen"); setStep(0); setDone(false); setTouring(true); window.scrollTo?.({ top: 0 }) }
  const extraMenu = useMemo(() => (startTour ? [] : [{ label: "이름 바꾸기", icon: Pencil, onClick: () => setRenaming(true) }, { label: "리포트 삭제", icon: Trash2, onClick: () => setRemoving(true), danger: true }]), [startTour])

  if (err) return <ErrorState title="예시 리포트를 열지 못했습니다" message={err} retry={() => window.location.reload()} />
  if (!doc || !svc) return <Loading label="예시 리포트를 준비하는 중…" />
  return (
    <div className="space-y-5">
      <div role="note" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-950">
        <p className="flex items-center gap-2 font-semibold"><Compass className="size-4 shrink-0" aria-hidden />{startTour ? "예시 데이터로 보는 화면입니다. 실제 분석 결과가 아니며, 버튼을 눌러도 아무것도 실행되지 않습니다." : "예시 리포트입니다. 실제 분석 결과가 아니며, 모의투자 시작 같은 버튼은 실행되지 않습니다."}</p>
        <div className="flex gap-2">
          {!touring && <Button variant="secondary" onClick={restart}>{startTour ? "처음부터 다시 보기" : "리포트 보는 법 둘러보기"}</Button>}
          {after
            ? <Button onClick={() => navigate(after)}><FileText className="size-4" />{after.page === "report" ? "내 리포트 보기" : "리포트 목록으로"}</Button>
            : <Button onClick={() => navigate({ page: "home" })}><Home className="size-4" />내 분석 시작하기</Button>}
        </div>
      </div>
      {done && (
        <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700">
          둘러보기를 마쳤습니다. 아래 예시 리포트는 자유롭게 펼쳐 볼 수 있습니다. 준비가 되면 「내 분석 시작하기」로 내 투자 아이디어를 분석해 보세요.
        </div>
      )}
      <ServiceContext.Provider value={svc}>
        <ReportDetail reportId={TUTORIAL_REPORT_ID} readOnly extraMenu={extraMenu} title={ex.name} />
      </ServiceContext.Provider>
      {touring && <Coachmark steps={TOUR_STEPS} index={step} onPrev={prev} onNext={next} onClose={close} />}
      {renaming && <RenameExampleDialog close={() => setRenaming(false)} />}
      {removing && <DeleteExampleDialog close={() => setRemoving(false)} onDeleted={() => navigate({ page: "reports" })} />}
    </div>
  )
}
