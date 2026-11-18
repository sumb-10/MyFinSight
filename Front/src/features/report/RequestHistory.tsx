import { useService } from "../../app/providers"
import { useResource } from "../../state/useResource"
import { Button, Disclosure, Loading } from "../../ui"
import { RevisionCard } from "../analysis/RevisionCard"
import { whenText } from "../profile/history"
import type { ProposedRequestLog } from "../../api/proposed"
import { MockTag } from "./proposedView"
import { SubPart } from "./SubPart"

function Bubble({ who, time, children }: { who: "user" | "system"; time?: string | null; children: React.ReactNode }) {
  const user = who === "user"
  return (
    <li className={`flex flex-col ${user ? "items-end" : "items-start"}`}>
      <span className="mb-0.5 text-[11px] text-slate-500">{user ? "사용자" : "분석 모델 질문"}{time ? ` · ${whenText(time)}` : ""}</span>
      <p className={`max-w-[90%] whitespace-pre-line break-words rounded-2xl px-3 py-2 text-sm leading-6 ${user ? "rounded-tr-sm bg-slate-800 text-white" : "rounded-tl-sm bg-slate-100 text-slate-800"}`}>{children}</p>
    </li>
  )
}

const OUTCOME: Record<ProposedRequestLog["messages"][number]["outcome"], [string, string]> = { applied: ["반영됨", "border-emerald-200 bg-emerald-50 text-emerald-800"], not_applied: ["반영되지 않음", "border-slate-200 bg-slate-50 text-slate-700"], needs_confirmation: ["추가 확인 필요", "border-amber-300 bg-amber-50 text-amber-900"] }

/** 이 리포트를 만든 요청의 실제 기록 (GET /requests/{id}): 처음 아이디어와 최종 반영 조건을 먼저, 질문·답변 전체는 펼쳐서. 서버가 주는 기록만 보여 준다.
 *  「말로 보탠 요청」 원문과 결과는 요청 기록에 없다 — 리포트의 제안 계약 request_log 가 있을 때만 보여 준다
 *  (실제 서버도 준다. 단 결과 기록이 생기기 전에 말을 보낸 예전 요청은 없음 → 아래 안내 문장). */
/** 최종 분석 조건 묶음 (서버 항목 이름 기준). 목록에 없는 이름은 「그 밖의 조건」으로 — 빠뜨리지 않는다. */
const CONDITION_GROUPS: [string, string[]][] = [
  ["투자금과 기간", ["투자금", "투자금 통화", "월 적립금", "적립일", "투자기간(년)", "투자 목적", "백테스트 기간(년)"]],
  ["투자성향과 목표", ["위험 성향", "손실 감내 수준(최대낙폭)", "손실 시 대응", "목표 연수익률", "비교지수"]],
  ["종목 범위와 제약", ["투자 유니버스", "자산 유형", "종목 수", "종목당 상한", "섹터당 상한", "최소 현금 비율", "제외 종목", "제외 섹터", "제외 테마", "필수 포함 종목", "최소 시가총액(USD)", "최소 일평균 거래대금(USD)"]],
  ["투자 전략과 운용", ["선정 기준(템플릿)", "기준 비중 방식", "뉴스 반영", "리밸런싱", "리밸런싱 규칙"]],
  ["분석 기준", ["분석 기준일", "환율", "투자금(USD 환산)", "백테스트 창"]],
]
type Cond = ProposedRequestLog["final_conditions"][number]

/** 최종 분석 조건: 묶음마다 제목 줄이 있는 상자, 상자 안은 한 줄에 조건 하나 「이름 … 값」 + 구분선. 넓은 화면은 묶음 상자를 두 칸으로.
 *  요청으로 바뀐 조건은 파랗게 강조 (2026-11-14 사용자 요청: 조건끼리 구분이 잘 되게). */
function FinalConditions({ items }: { items: Cond[] }) {
  const known = new Set(CONDITION_GROUPS.flatMap(([, ks]) => ks))
  const groups: [string, Cond[]][] = [...CONDITION_GROUPS.map(([g, ks]) => [g, ks.map((k) => items.find((c) => c.label_ko === k)).filter(Boolean) as Cond[]] as [string, Cond[]]), ["그 밖의 조건", items.filter((c) => !known.has(c.label_ko))] as [string, Cond[]]].filter(([, cs]) => cs.length > 0)
  // 두 열로 나눠 놓는다 — 왼쪽: 투자금과 기간 → 종목 범위와 제약, 오른쪽: 투자성향과 목표 → 투자 전략과 운용 → 분석 기준 (→ 그 밖의 조건). 좁은 화면은 왼쪽 열 다음 오른쪽 열 순서로 한 줄씩
  const LEFT = new Set(["투자금과 기간", "종목 범위와 제약"])
  const box = ([g, cs]: [string, Cond[]]) => (
        <section key={g} aria-label={g} className="overflow-hidden rounded-xl border border-slate-200">
          <h4 className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-4 py-2 text-sm font-bold text-slate-800">{g}<span className="text-xs font-normal text-slate-500">{cs.length}개</span></h4>
          <dl className="divide-y divide-slate-100">
            {cs.map((c) => (
              <div key={c.label_ko} className={`flex items-start justify-between gap-4 px-4 py-2.5 text-sm ${c.changed ? "bg-blue-50/70" : ""}`}>
                <dt className="flex shrink-0 flex-col items-start gap-0.5 text-slate-500">{c.label_ko}{c.changed && <span className="rounded-full bg-blue-100 px-1.5 py-px text-[11px] font-semibold text-blue-800">요청으로 바뀜</span>}</dt>
                <dd className={`min-w-0 break-words text-right ${c.changed ? "font-bold text-slate-950" : "font-semibold text-slate-900"}`}>{c.value_ko}</dd>
              </div>
            ))}
          </dl>
        </section>
  )
  return (
    <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
      <div className="space-y-4">{groups.filter(([g]) => LEFT.has(g)).map(box)}</div>
      <div className="space-y-4">{groups.filter(([g]) => !LEFT.has(g)).map(box)}</div>
    </div>
  )
}

export function RequestHistory({ requestId, log }: { requestId: string; log?: ProposedRequestLog | null }) {
  const svc = useService()
  const res = useResource(() => svc.getRequest(requestId), [svc, requestId])
  if (res.status === "loading" && !res.data) return <Loading label="요청 내역을 불러오는 중…" />
  const st = res.data
  if (!st) return <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600"><p>요청 내역을 불러오지 못했습니다. {res.error ?? ""}</p><Button variant="secondary" className="mt-2" onClick={res.reload}>다시 시도</Button></div>
  const answered = st.questions.filter((q) => q.answered_at).sort((a, b) => a.seq - b.seq)
  const changed = (st.confirmation?.rows ?? st.conditions ?? []).filter((r) => r.changed && r.group_ko !== "아이디어")
  // 큰 파트 (2026-11-14 사용자 요청: 다른 섹션과 같은 모양) — 처음 요청 / 요청 대화 기록 / 최종 분석 조건 / 수정 요청
  return (
    <>
      <SubPart title="투자 아이디어와 변경 조건">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="rounded-xl border border-slate-200 p-4">
            <h4 className="text-base font-semibold text-slate-900">처음 입력한 투자 아이디어</h4>
            <p className="mt-2 whitespace-pre-line break-words text-[15px] leading-7 text-slate-800">{st.idea}</p>
          </div>
          <div className="rounded-xl border border-slate-200 p-4">
            <h4 className="text-base font-semibold text-slate-900">최종 분석에 반영된 변경 조건</h4>
            {changed.length ? (
              <ul className="mt-2 divide-y divide-slate-100 text-sm">{changed.map((r) => <li key={r.field} className="flex flex-col gap-0.5 py-2 sm:flex-row sm:gap-4"><span className="shrink-0 font-semibold text-slate-800 sm:w-36">{r.label_ko}</span><span className="min-w-0 break-words text-slate-700">{r.profile_value_ko != null && <><span className="text-slate-500">{r.profile_value_ko}</span><span className="mx-1.5 text-slate-400">→</span></>}<b>{r.value_ko}</b></span></li>)}</ul>
            ) : <p className="mt-2 text-sm text-slate-600">기본 투자조건과 달라진 항목이 없습니다.</p>}
          </div>
        </div>
      </SubPart>
      <SubPart title="요청 대화 기록" desc="분석 모델의 추가 질문에 답한 내용과, 말로 보탠 요청의 처리 결과입니다.">
        <Disclosure title="추가 질문과 답변" summary={`${answered.length}건`}>
          {answered.length ? (
            <ol className="space-y-3" aria-label="요청 기록">
              <Bubble who="user">{st.idea}</Bubble>
              {answered.flatMap((q) => [
                <Bubble key={`q${q.seq}`} who="system" time={q.asked_at}>{q.question_ko}</Bubble>,
                <Bubble key={`a${q.seq}`} who="user" time={q.answered_at}>{q.skipped ? "답하지 않음 (기본값 사용)" : q.answer}</Bubble>,
              ])}
            </ol>
          ) : <p className="text-sm text-slate-600">저장된 추가 질문과 답변이 없습니다.</p>}
        </Disclosure>
        {/* 말로 보탠 요청: 접어 두고 눌러서 연다 (2026-11-14 사용자 요청) */}
        {log && (
          <Disclosure title={<span className="inline-flex items-center">말로 보탠 요청<MockTag /></span>} summary={`${log.messages.length}건`}>
            {log.messages.length ? (
              <ul className="space-y-2">
                {log.messages.map((m, i) => (
                  <li key={i} className="rounded-lg bg-slate-50 px-3 py-2.5">
                    <p className="flex flex-wrap items-center justify-between gap-2"><span className="text-sm font-semibold text-slate-900">“{m.text}”</span><span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${OUTCOME[m.outcome][1]}`}>{OUTCOME[m.outcome][0]}</span></p>
                    <p className="text-xs text-slate-500">{whenText(m.at)}</p>
                    {m.changes_ko.length > 0 && <ul className="mt-1 list-disc pl-5 text-sm leading-6 text-slate-700">{m.changes_ko.map((c, j) => <li key={j}>{c}</li>)}</ul>}
                    {m.outcome !== "applied" && <p className="mt-1 text-sm leading-6 text-slate-600">{m.note_ko ?? "기존 조건이 그대로 유지됩니다."}</p>}
                  </li>
                ))}
              </ul>
            ) : <p className="text-sm text-slate-600">말로 보탠 요청이 없습니다.</p>}
          </Disclosure>
        )}
      </SubPart>
      {log && (
        <SubPart title="최종 분석 조건" desc={`${log.final_conditions.length}개 항목${log.final_conditions.some((c) => c.changed) ? ` · 요청으로 바뀜 ${log.final_conditions.filter((c) => c.changed).length}개` : ""}`}>
          <FinalConditions items={log.final_conditions} />
        </SubPart>
      )}
      {st.revision && <SubPart title="수정 요청"><RevisionCard rev={st.revision} /></SubPart>}
    </>
  )
}
