import { useState } from "react"
import { useService } from "../../app/providers"
import type { ProfileView } from "../../api/types"
import { VersionCompare } from "./compare"
import { PartDisclosure } from "./parts"

// 변경 이력: GET /profile 은 과거 버전의 번호·저장 시각만 주고 값은 주지 않는다 (현재 버전 값만 온다).
// 그래서 무엇이 바뀌었는지는 추측하지 않고 표시하지 않는다 (현재 값을 과거 값처럼 보여 주지 않는다).

/** "2026-10-30T16:58:12+09:00" → "10월 30일 16:58" (올해가 아니면 연도도). 저장된 시각 글자를 그대로 읽어 시간대를 다시 바꾸지 않는다. */
export function whenText(iso: string, now = new Date()): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso)
  if (!m) return iso
  const [, y, mo, d, h, mi] = m
  return `${Number(y) !== now.getFullYear() ? `${y}년 ` : ""}${Number(mo)}월 ${Number(d)}일 ${h}:${mi}`
}

export function VersionHistory({ view }: { view: ProfileView }) {
  const svc = useService()
  const canCompare = !!svc.getProfileVersion && view.versions.length > 1  // 제안 기능: 과거 버전 값 전체를 받을 수 있을 때만
  const [to, setTo] = useState(view.current_version)
  const desc = [...view.versions].sort((a, b) => b.version - a.version)
  const first = desc[desc.length - 1]?.version
  return (
    <PartDisclosure title="변경 이력 보기" summary={desc[0] ? `버전 ${desc.length}개 · 마지막 변경 ${whenText(desc[0].created_at)}` : undefined}>
      <p className="text-xs text-slate-500">{canCompare ? "버전을 골라 바로 앞 버전(또는 고른 버전)과 무엇이 바뀌었는지 비교합니다." : "버전별로 무엇이 바뀌었는지는 아직 제공되지 않아 저장 시각과 버전만 보여 줍니다."}</p>
      <ol className="space-y-2">
        {desc.map((v) => (
          <li key={v.version} className={`flex flex-wrap items-center gap-2 rounded-xl border bg-white px-4 py-3 text-sm ${canCompare && v.version === to ? "border-blue-300 ring-1 ring-blue-100" : "border-slate-200"}`}>
            <span className="font-semibold text-slate-900">{whenText(v.created_at)} · 버전 {v.version}</span>
            {v.version === view.current_version && <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] font-semibold text-slate-600">현재</span>}
            {v.version === first && <span className="text-slate-500">최초 설정</span>}
            {canCompare && v.note && v.version !== first && <span className="text-slate-500">{v.note}</span>}
            {canCompare && v.version !== first && <button type="button" className="ml-auto text-xs font-semibold text-blue-700 hover:underline" aria-label={`버전 ${v.version}을 앞 버전과 비교`} onClick={() => setTo(v.version)}>앞 버전과 비교</button>}
          </li>
        ))}
      </ol>
      {canCompare && <VersionCompare view={view} to={to} setTo={setTo} />}
    </PartDisclosure>
  )
}
