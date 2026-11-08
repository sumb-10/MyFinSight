// 목업 모드 표시와 개발용 조작 패널. 목업 모드에서만 불러온다 (App 의 lazy import, 운영 빌드에는 들어가지 않음).
// 위쪽 띠: 모든 화면 맨 위에 「목업 데이터 화면입니다」. 오른쪽 아래 버튼: 스크롤해도 늘 보이는 목업 표시이자 시나리오 전환 패널.
import { useState } from "react"
import { FlaskConical, RotateCcw, X } from "lucide-react"
import { useProfile, useService } from "../app/providers"
import { navigate, type Route } from "../app/router"
import { clearGuideRecord } from "../features/tutorial/guideRecord"
import { exitMockHref } from "./mode"
import { PAPERS, REPORTS, RUN_STATES } from "./scenarios"
import type { MockService } from "./services/MockService"

export default function MockChrome() {
  const svc = useService() as unknown as MockService
  const { reload } = useProfile()
  const [open, setOpen] = useState(false)
  const [variant, setVariant] = useState(() => svc.state?.().profileVariant ?? "default")
  const go = (r: Route) => { navigate(r); setOpen(false) }
  const link = "block w-full rounded-lg px-2.5 py-1.5 text-left text-xs text-slate-700 hover:bg-amber-50 focus:outline-none focus:ring-2 focus:ring-amber-500"
  const head = "px-2.5 pt-3 text-[11px] font-bold tracking-wide text-amber-800"
  return (
    <>
      <div role="status" className="flex min-w-[1180px] items-center justify-center gap-3 border-b border-amber-300 bg-amber-100 px-4 py-1.5 text-xs font-semibold text-amber-950">
        <FlaskConical className="size-3.5" aria-hidden />
        <span>목업 데이터 화면입니다 · 실제 투자 분석 결과가 아닙니다.</span>
        <a href={exitMockHref()} className="font-normal underline underline-offset-2 hover:text-amber-800">일반 모드로 돌아가기</a>
      </div>
      <div className="fixed bottom-4 right-4 z-[60] flex flex-col items-end gap-2">
        {open && (
          <div role="dialog" aria-label="목업 패널" className="max-h-[70vh] w-72 overflow-y-auto rounded-2xl border border-amber-300 bg-white p-2 shadow-xl">
            <div className="flex items-center justify-between px-2.5 pt-1">
              <p className="text-sm font-bold text-slate-900">목업 시나리오</p>
              <button type="button" aria-label="목업 패널 닫기" onClick={() => setOpen(false)} className="rounded-md p-1 text-slate-500 hover:bg-slate-100"><X className="size-4" /></button>
            </div>
            <p className="px-2.5 text-[11px] leading-4 text-slate-500">개발용 조작입니다. 실제 서비스 화면에는 나타나지 않습니다.</p>
            <p className={head}>분석 리포트</p>
            {REPORTS.map((r) => <button key={r.id} type="button" className={link} onClick={() => go({ page: "report", reportId: r.id })}>{r.label_ko}</button>)}
            <p className={head}>분석 진행</p>
            {RUN_STATES.map((r) => <button key={r.id} type="button" className={link} onClick={() => go({ page: "run", runId: r.id })}>{r.label_ko}</button>)}
            <button type="button" className={link} onClick={() => go({ page: "run", runId: REPORTS[0].run_id })}>분석 완료</button>
            <button type="button" className={link} onClick={() => go({ page: "run", runId: svc.startLiveRun("success") })}>▶ 진행 재생: 대기 → 단계 진행 → 완료 (약 30초)</button>
            <button type="button" className={link} onClick={() => go({ page: "run", runId: svc.startLiveRun("failed") })}>▶ 진행 재생: 대기 → 단계 진행 → 실패</button>
            <p className={head}>새 분석</p>
            <button type="button" className={link} onClick={() => go({ page: "clarify", requestId: "mock_req_asking" })}>추가 질문 중인 요청</button>
            <button type="button" className={link} onClick={() => go({ page: "confirm", requestId: "mock_req_ready" })}>조건 확인 (질문 답변 완료)</button>
            <p className={head}>모의투자</p>
            <button type="button" className={link} onClick={() => go({ page: "paper" })}>모의투자 목록 ({PAPERS.length}개, 같은 리포트에서 3개)</button>
            <p className={head}>내 투자조건</p>
            <div className="flex gap-1 px-2.5 py-1">
              {(["default", "zero"] as const).map((v) => (
                <button key={v} type="button" aria-pressed={variant === v} onClick={() => { svc.setProfileVariant(v); setVariant(v); void reload() }} className={`rounded-lg border px-2 py-1 text-xs ${variant === v ? "border-amber-500 bg-amber-50 font-semibold text-amber-900" : "border-slate-200 text-slate-600 hover:bg-slate-50"}`}>{v === "default" ? "기본 (변경 이력 4개)" : "초기 투자금 0원"}</button>
              ))}
            </div>
            <button type="button" className={link} onClick={() => go({ page: "profile" })}>내 투자조건 열기</button>
            <div className="mt-2 border-t border-slate-100 pt-2">
              <button type="button" className={`${link} text-amber-900`} onClick={clearGuideRecord}>가이드 안내 기록 지우기</button>
              <button type="button" className={`${link} flex items-center gap-1.5 text-amber-900`} onClick={() => { svc.reset(); window.location.reload() }}><RotateCcw className="size-3.5" aria-hidden />목업 데이터 초기화 (바꾼 이름·조건·모의투자 지우기)</button>
            </div>
          </div>
        )}
        <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)} className="inline-flex items-center gap-1.5 rounded-full border border-amber-400 bg-amber-100 px-3 py-1.5 text-xs font-bold text-amber-950 shadow-md hover:bg-amber-200 focus:outline-none focus:ring-2 focus:ring-amber-500">
          <FlaskConical className="size-3.5" aria-hidden />목업 데이터
        </button>
      </div>
    </>
  )
}
