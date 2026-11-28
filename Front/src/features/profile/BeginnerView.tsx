import { useState } from "react"
import { useProfile, useService } from "../../app/providers"
import { errorMessage } from "../../api/client"
import type { ProfileFields, ProfileView } from "../../api/types"
import { InfoTip } from "./inputs"

// 왕초보용 화면 설정 (2026-11-28). 켜면 투자 리포트를 왕초보용 화면으로 먼저 보여 준다.
// 값은 투자조건(프로필)에 beginner_view 로 저장한다. 화면 설정이라 분석 요청·계산에는 들어가지 않는다.
// 리포트 화면(features/report/ReportDetail)이 isBeginnerView 로 처음 화면을 고른다: 켜져 있으면 왕초보용(features/report/beginner), 아니면 원래 리포트. 리포트 안의 토글은 이 값을 바꾸지 않는다.
// 대화형 설정은 첫 질문으로 묻고(서버 profile_chat.py · 목업 profileChat.ts), 여기 카드는 저장된 투자조건 화면과 4단계 폼 맨 위에 둔다.

export const BEGINNER_TITLE = "왕초보용 화면"
const BEGINNER_INFO = "켜면 투자 리포트를 왕초보용 화면으로 먼저 보여 줍니다. 분석 결과는 달라지지 않습니다."

/** 요약표·버전 비교에 쓰는 값 글. */
export const beginnerText = (on: boolean | undefined) => (on ? "사용" : "사용 안 함")

/** 투자 리포트의 기본 화면이 왕초보용인가 (값이 없는 예전 투자조건은 일반 화면). */
export const isBeginnerView = (view: ProfileView | null | undefined) => !!view?.profile.beginner_view

/** 스위치 카드. 켜져 있으면 파란 면으로 눈에 띄게 한다 (파란색 = 선택한 옵션, 내 투자조건 화면의 규칙). */
export function BeginnerViewCard({ value, onChange, busy = false, error }: { value: boolean; onChange: (v: boolean) => void; busy?: boolean; error?: string }) {
  return (
    <section aria-label={BEGINNER_TITLE} className={`rounded-2xl border px-5 py-4 shadow-sm transition-colors sm:px-6 ${value ? "border-blue-300 bg-blue-50" : "border-slate-300 bg-white"}`}>
      <div className="flex items-center justify-between gap-4">
        <h2 className="flex items-center gap-1 text-base font-bold text-slate-950">{BEGINNER_TITLE}<InfoTip label={BEGINNER_TITLE}>{BEGINNER_INFO}</InfoTip></h2>
        <div className="flex shrink-0 items-center gap-3">
          <span aria-hidden className={`text-sm font-semibold ${value ? "text-blue-800" : "text-slate-500"}`}>{value ? "사용 중" : "사용 안 함"}</span>
          <button type="button" role="switch" aria-checked={value} aria-label={BEGINNER_TITLE} disabled={busy} onClick={() => onChange(!value)}
            className={`relative inline-flex h-7 w-12 shrink-0 items-center rounded-full transition focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-wait disabled:opacity-60 ${value ? "bg-blue-700" : "bg-slate-300"}`}>
            <span className={`inline-block size-5 rounded-full bg-white shadow transition ${value ? "translate-x-6" : "translate-x-1"}`} />
          </button>
        </div>
      </div>
      {error && <p role="alert" className="mt-2 text-xs font-medium text-red-600">{error}</p>}
    </section>
  )
}

/** 저장된 투자조건 화면용: 누르면 그 값만 바꿔 바로 저장한다 (새 버전 추가). 다른 값은 저장된 그대로 보낸다. */
export function BeginnerViewQuick({ view }: { view: ProfileView }) {
  const svc = useService()
  const { set, reload } = useProfile()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const change = async (next: boolean) => {
    const { version: _version, created_at: _createdAt, note: _note, ...fields } = view.profile
    const body: ProfileFields = { ...fields, beginner_view: next, note: next ? "왕초보용 화면 켬" : "왕초보용 화면 끔" }
    setBusy(true); setError("")
    try { set(await svc.saveProfile(body)); void reload() }
    catch (e) { setError(`저장하지 못했습니다: ${errorMessage(e)}`) }
    finally { setBusy(false) }
  }
  return <BeginnerViewCard value={isBeginnerView(view)} onChange={(v) => void change(v)} busy={busy} error={error} />
}
