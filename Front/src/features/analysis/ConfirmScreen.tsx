import { useState } from "react"
import { MessageSquareText, Play, SlidersHorizontal } from "lucide-react"
import { useProfile, useService } from "../../app/providers"
import { navigate } from "../../app/router"
import { errorMessage } from "../../api/client"
import type { ConditionRow, DialogState } from "../../api/types"
import { useResource } from "../../state/useResource"
import { saveUi } from "../../state/uiStorage"
import { Alert, Badge, Button, Card, EmptyState, ErrorState, Loading, PageHeader, inputClass } from "../../ui"
import { ko } from "../../lib/format"
import { RevisionCard } from "./RevisionCard"
import { startNewWith } from "./ClarifyScreen"
import { DetailConditionsDialog } from "../home/DetailConditions"

const SOURCE_KO: Record<ConditionRow["source"], string> = { profile: "프로필", idea: "아이디어", answer: "보충 답변", default: "기본값", derived: "계산" }

export function ConfirmScreen({ requestId }: { requestId: string }) {
  const svc = useService()
  const { profile } = useProfile()
  const res = useResource(() => svc.getRequest(requestId), [svc, requestId])
  const [busy, setBusy] = useState<"" | "start" | "overrides" | "message">("")
  const [err, setErr] = useState("")
  const [toolErr, setToolErr] = useState("")
  const [editing, setEditing] = useState(false)
  const [note, setNote] = useState("")
  if (res.status === "loading" && !res.data) return <Loading label="확정 조건을 불러오는 중…" />
  if (res.status === "error" || !res.data) return <ErrorState message={res.error ?? ""} retry={res.reload} />
  const st = res.data
  if (st.status === "cancelled") return <EmptyState title="취소된 요청입니다" description="이 요청은 취소되어 분석을 시작할 수 없습니다. 같은 아이디어와 조건으로 새 요청을 시작할 수 있습니다." action={<div className="flex gap-2"><Button onClick={() => startNewWith(st.idea, st.overrides)}>같은 조건으로 새 요청</Button><Button variant="ghost" onClick={() => navigate({ page: "home" })}>홈으로</Button></div>} />
  if (st.state === "asking" || st.state === "blocked") { navigate({ page: "clarify", requestId }); return null }
  if (st.status === "confirmed" && st.run_id) {
    return <Alert title="이미 분석이 시작된 요청입니다" tone="info"><Button variant="secondary" onClick={() => navigate({ page: "run", runId: st.run_id! })}>실행 상태 보기</Button></Alert>
  }
  if (!st.confirmation) return <ErrorState title="확정 조건을 만들지 못했습니다" message="조건을 바꾸거나 새 요청으로 다시 시작해 주세요." retry={res.reload} />
  const rows = st.confirmation.rows
  const groups = [...new Set(rows.map((r) => r.group_ko))]
  const unsupported = rows.filter((r) => !r.supported)
  const changed = rows.filter((r) => r.changed)

  const start = async () => {
    setBusy("start"); setErr("")
    try {
      const { run_id } = await svc.confirm(requestId)
      saveUi({ activeRequestId: null, activeRunId: run_id })
      navigate({ page: "run", runId: run_id })
    } catch (e) { setErr(errorMessage(e)) } finally { setBusy("") }
  }
  // 조건 확인 화면에서도 조건을 바꾸거나 말로 보탤 수 있다 (P1-1). 바뀐 뒤 질문이 생기면 대화 화면으로 돌아간다.
  const after = (next: DialogState) => { if (next.state === "asking" || next.hard_errors.length > 0) navigate({ page: "clarify", requestId }); else res.reload() }
  const tool = async (kind: "overrides" | "message", fn: () => Promise<DialogState>) => {
    setBusy(kind); setToolErr("")
    try { after(await fn()); setNote("") } catch (e) { setToolErr(errorMessage(e)) } finally { setBusy("") }
  }
  const applyOverrides = (o: Record<string, unknown>) => {
    const prev = st.overrides ?? {}
    const merged: Record<string, unknown> = { ...o }
    for (const k of Object.keys(prev)) if (!(k in o)) merged[k] = null
    void tool("overrides", () => svc.updateOverrides(requestId, merged))
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <PageHeader eyebrow={`${ko(st.mode)} · 조건 확인`} title={st.mode === "revision" ? "이 수정안으로 분석을 시작할까요?" : "이 조건으로 분석을 시작할까요?"} description={st.mode === "revision" ? "원안의 조건에 수정 요청을 반영한 최종 조건입니다. 파란 줄이 원안과 달라진 항목입니다. 분석이 끝나면 원안과 비교한 결과를 볼 수 있습니다." : "프로필 기본값에 보충 답변을 반영한 최종 조건입니다. 「분석 시작」을 누르기 전에는 어떤 분석도 실행되지 않습니다. 아직 바꿀 수 있습니다. 시작 후에는 조건을 바꿀 수 없고, 바꾸려면 새 요청으로 다시 분석합니다."} />
      {st.summary.interpretation_summary_ko && (
        <Card className="p-5"><p className="text-xs font-bold text-slate-400">분석 모델의 이해</p><p className="mt-1 text-sm text-slate-800">{st.summary.interpretation_summary_ko}</p><div className="mt-2 flex flex-wrap gap-2">{st.summary.themes.map((t) => <Badge key={t.id} tone="blue">{t.label_ko}</Badge>)}</div></Card>
      )}
      {st.revision && <RevisionCard rev={st.revision} />}
      {st.blocked_reason_ko && (
        <Alert title="보충 질문을 모두 써서 남은 항목은 지금 조건으로 둡니다" tone="info">
          <p>{st.blocked_reason_ko}</p>
          {st.unresolved.length > 0 && <ul className="mt-2 list-disc pl-5">{st.unresolved.map((u) => <li key={u.field}><b>{u.label_ko}</b>: {u.hint_ko}</li>)}</ul>}
        </Alert>
      )}
      {changed.length > 0 && <Alert title={`${st.mode === "revision" ? "원안과" : "프로필과"} 달라진 조건 ${changed.length}개`} tone="info">{changed.map((r) => <span key={r.field} className="mr-3">{r.label_ko}: {r.profile_value_ko} → <b>{r.value_ko}</b></span>)}</Alert>}
      {(st.summary.derived?.warnings?.length ?? 0) > 0 && <Alert title="계산 조건 안내" tone="warning"><ul className="list-disc pl-5">{st.summary.derived!.warnings!.map((w, i) => <li key={i}>{w}</li>)}</ul></Alert>}
      {unsupported.length > 0 && <Alert title="지원하지 않는 조건이 있어 분석을 시작할 수 없습니다" tone="error"><ul className="list-disc pl-5">{unsupported.map((r) => <li key={r.field}>{r.label_ko}: {r.note_ko}</li>)}</ul></Alert>}
      <Card className="overflow-hidden">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-slate-200 bg-slate-50 text-left text-xs font-semibold text-slate-500"><th className="px-5 py-3">구분</th><th className="px-5 py-3">항목</th><th className="px-5 py-3">이번 분석 값</th><th className="px-5 py-3">출처</th></tr></thead>
          <tbody>
            {groups.map((g) => rows.filter((r) => r.group_ko === g).map((r, i) => (
              <tr key={r.field} className={`border-b border-slate-100 ${r.changed ? "bg-blue-50/40" : ""}`}>
                <td className="px-5 py-2.5 text-xs font-semibold text-slate-400">{i === 0 ? g : ""}</td>
                <td className="px-5 py-2.5 font-medium text-slate-800">{r.label_ko}</td>
                <td className="px-5 py-2.5 text-slate-800">{r.value_ko}{r.changed && r.profile_value_ko && <span className="ml-2 text-xs text-slate-400">({st.mode === "revision" ? "원안" : "프로필"} {r.profile_value_ko})</span>}{r.note_ko && <span className="ml-2 text-xs text-amber-700">{r.note_ko}</span>}</td>
                <td className="px-5 py-2.5"><Badge tone={r.changed ? "blue" : "slate"}>{SOURCE_KO[r.source]}{r.changed ? " · 변경" : ""}</Badge></td>
              </tr>
            )))}
          </tbody>
        </table>
      </Card>
      {st.mode !== "revision" && (
        <Card className="p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div><p className="text-xs font-bold text-slate-400">아직 바꿀 수 있습니다</p><p className="mt-1 text-xs text-slate-500">숫자 조건은 「조건 바꾸기」가 정확하고, 그 밖의 요청은 말로 적으면 분석 모델이 해석해 반영합니다. 바꾸면 조건을 다시 확인합니다.</p></div>
            {profile && <Button variant="secondary" onClick={() => setEditing(true)} disabled={busy !== ""}><SlidersHorizontal className="size-4" />조건 바꾸기</Button>}
          </div>
          <div className="mt-3 flex items-start gap-2">
            <textarea className={`${inputClass} min-h-14 flex-1`} value={note} onChange={(e) => setNote(e.target.value)} placeholder="예: 한국 종목은 빼 주세요 / 종목은 8개만 / 배당주 위주로" disabled={busy !== ""} aria-label="말로 조건 보태기" />
            <Button variant="secondary" onClick={() => { if (!note.trim()) { setToolErr("보탤 내용을 적어 주세요."); return } void tool("message", () => svc.sendMessage(requestId, note.trim())) }} disabled={busy !== ""}><MessageSquareText className="size-4" />{busy === "message" ? "반영하는 중…" : "말로 보태기"}</Button>
          </div>
          {toolErr && <p className="mt-2 text-xs font-medium text-red-600">{toolErr}</p>}
        </Card>
      )}
      {err && <Alert title="분석을 시작하지 못했습니다" tone="error">{err}</Alert>}
      <div className="flex items-center justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" onClick={() => startNewWith(st.idea, st.overrides)}>아이디어 수정 (조건 그대로 새 요청)</Button>
          <span title="프로필을 바꿔도 이 요청에는 적용되지 않습니다. 저장한 뒤 새 요청으로 시작해 주세요."><Button variant="ghost" onClick={() => navigate({ page: "profile", mode: "edit" })}>기본 투자조건 수정</Button></span>
        </div>
        <Button onClick={start} disabled={busy !== "" || unsupported.length > 0}><Play className="size-4" />{busy === "start" ? "큐에 등록 중…" : "분석 시작"}</Button>
      </div>
      {editing && profile && <DetailConditionsDialog profile={profile.profile} initial={st.overrides ?? {}} onApply={applyOverrides} close={() => setEditing(false)} title="이번 요청의 조건 바꾸기" applyLabel="이 조건으로 다시 확인" intro="프로필에서 가져온 기본값을 이번 요청에서만 바꿉니다. 적용하면 분석 모델이 바뀐 조건으로 다시 해석하고, 필요한 질문만 다시 묻습니다. 프로필 자체는 그대로입니다." />}
    </div>
  )
}
