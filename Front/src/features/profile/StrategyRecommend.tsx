import { Check } from "lucide-react"
import { useService } from "../../app/providers"
import type { ProposedStrategyRecommendation } from "../../api/proposed"
import type { StrategyPreference, Template, Tendency, Weighting } from "../../api/types"
import { useResource } from "../../state/useResource"
import { Button } from "../../ui"
import { MockTag } from "../report/proposedView"
import { Part } from "./parts"
import { templateLabel, weightingLabel } from "./strategyInfo"

// 투자성향 기반 추천 전략 (제안 기능): 서비스에 recommendStrategy 가 있을 때만 보인다. 실제 서버(GET /strategy/recommendation)와 목업 모두 성향마다 정해 둔 고정 규칙 표다.

type Rec = ProposedStrategyRecommendation["recommended"]
export const asPref = (r: Rec): Partial<StrategyPreference> => ({ template: r.template as Template, baseline_weighting: r.baseline_weighting as Weighting, use_news_tilt: r.use_news_tilt })
const same = (r: Rec, v: StrategyPreference) => r.template === v.template && r.baseline_weighting === v.baseline_weighting && r.use_news_tilt === v.use_news_tilt
const text = (r: Rec) => [templateLabel(r.template), weightingLabel(r.baseline_weighting), r.use_news_tilt ? "뉴스·공시 반영" : "뉴스·공시 반영 안 함"]

/** 추천 결과. 없으면(일반 모드) null — 화면은 지금처럼 직접 고르기만 한다. */
export function useRecommendation(tendency: Tendency | undefined, purpose?: string | null) {
  const svc = useService()
  return useResource(() => (svc.recommendStrategy && tendency ? svc.recommendStrategy(tendency, purpose) : Promise.resolve(null)), [svc, tendency, purpose]).data
}

export function StrategyRecommendation({ rec, value, onPick }: { rec: ProposedStrategyRecommendation; value: StrategyPreference; onPick: (p: Partial<StrategyPreference>) => void }) {
  const applied = same(rec.recommended, value)
  return (
    <Part title={`${rec.tendency}에게 추천하는 전략`} aside={<MockTag />} desc="투자성향과 투자 목적에 맞춘 추천입니다. 추천을 그대로 쓰거나, 아래에서 직접 고를 수 있습니다.">
      <div className={`rounded-xl border p-4 ${applied ? "border-blue-300 bg-blue-50" : "border-slate-200 bg-slate-50"}`}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-bold text-blue-700">추천 전략</p>
            <p className="mt-1 text-sm font-semibold leading-6 text-slate-900">{text(rec.recommended).join(" · ")}</p>
          </div>
          {applied ? <span className="inline-flex items-center gap-1 rounded-lg bg-white px-2.5 py-1.5 text-xs font-semibold text-blue-800"><Check className="size-4" />지금 적용됨</span> : <Button variant="secondary" onClick={() => onPick(asPref(rec.recommended))}>추천 전략 적용</Button>}
        </div>
        <p className="mt-3 text-xs font-semibold text-slate-500">추천 이유</p>
        <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs leading-5 text-slate-700">{rec.reasons_ko.map((r) => <li key={r}>{r}</li>)}</ul>
      </div>
      <div>
        <p className="text-sm font-semibold text-slate-800">다른 전략과의 차이</p>
        <ul className="mt-2 space-y-2">
          {rec.alternatives.map((a) => {
            const on = same(a, value)
            return (
              <li key={text(a).join()} className={`flex flex-col gap-2 rounded-xl border p-3 sm:flex-row sm:items-center sm:justify-between ${on ? "border-blue-300 bg-blue-50/60" : "border-slate-200 bg-white"}`}>
                <span className="min-w-0 text-xs leading-5 text-slate-600"><b className="block text-sm text-slate-800">{text(a).join(" · ")}</b>{a.diff_ko}</span>
                {on ? <span className="shrink-0 text-xs font-semibold text-blue-800">지금 적용됨</span> : <Button variant="ghost" className="shrink-0" onClick={() => onPick(asPref(a))}>이 전략 고르기</Button>}
              </li>
            )
          })}
        </ul>
      </div>
      <p className="text-xs leading-5 text-slate-500">{applied ? "" : "지금은 추천과 다른 전략을 쓰고 있습니다. "}{rec.note_ko}</p>
    </Part>
  )
}
