import type { StrategyPreference, Template, Weighting } from "../../api/types"
import { Disclosure } from "../../ui"
import { Part } from "./parts"
import { MockTag } from "../report/proposedView"
import { NEWS_INFO, TEMPLATE_INFO, TEMPLATE_ORDER, WEIGHTING_INFO, WEIGHTING_ORDER } from "./strategyInfo"

/** 투자 전략 설정: ① 어떤 기업을 고를지 → ② 투자금을 어떻게 나눌지 → ③ 뉴스·공시로 비중을 조정할지. 값은 enum 그대로 onChange 로 넘긴다. */
/** recommended: 투자성향 기반 추천(제안 기능, 목업에서만 온다). 주면 해당 카드에 「추천」 표시만 붙인다. */
export function StrategyFields({ value, onChange, templates, weightings, recommended }: { value: StrategyPreference; onChange: (patch: Partial<StrategyPreference>) => void; templates?: Template[]; weightings?: Weighting[]; recommended?: Partial<StrategyPreference> | null }) {
  return (
    <div className="space-y-8">
      <TemplatePicker value={value.template} options={sortBy(templates ?? TEMPLATE_ORDER, TEMPLATE_ORDER)} onChange={(t) => onChange({ template: t })} recommended={recommended?.template} />
      <WeightingPicker value={value.baseline_weighting} options={sortBy(weightings ?? WEIGHTING_ORDER, WEIGHTING_ORDER)} onChange={(w) => onChange({ baseline_weighting: w })} recommended={recommended?.baseline_weighting} />
      <NewsToggle value={value.use_news_tilt} onChange={(v) => onChange({ use_news_tilt: v })} />
    </div>
  )
}

const sortBy = <T extends string>(xs: T[], order: T[]) => [...xs].sort((a, b) => (order.indexOf(a) + 99) % 99 - (order.indexOf(b) + 99) % 99)


/** 쉬운 이름 + 괄호 전문용어 ("최근 주가 상승세가 좋은 기업(모멘텀)"). 전문용어는 이름과 같은 색·굵기 — 아래 회색 설명과 헷갈리지 않게 이름의 일부로 보인다. */
const Named = ({ name, short }: { name: string; short: string }) => <>{name}({short})</>
const RecBadge = () => <span className="ml-1.5 inline-flex items-center rounded border border-blue-200 bg-white px-1.5 py-px align-middle text-[11px] font-semibold text-blue-700">추천</span>
const cardClass = (on: boolean) => `rounded-xl border p-3 text-left transition focus:outline-none focus:ring-2 focus:ring-blue-500 ${on ? "border-blue-400 bg-blue-50 ring-1 ring-blue-200" : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"}`

function TemplatePicker({ value, options, onChange, recommended }: { value: Template; options: Template[]; onChange: (t: Template) => void; recommended?: Template }) {
  const cur = TEMPLATE_INFO[value]
  return (
    <Part title="어떤 기업에 투자하고 싶나요?" info="투자 아이디어에 맞는 후보 기업 가운데, 고른 기준으로 순위를 매겨 투자할 종목을 정합니다.">
      <div role="radiogroup" aria-label="어떤 기업에 투자하고 싶나요?" className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {options.map((t) => {
          const i = TEMPLATE_INFO[t]
          const on = value === t
          return (
            <button key={t} type="button" role="radio" aria-checked={on} onClick={() => onChange(t)} className={cardClass(on)}>
              <span className={`block text-sm font-semibold ${on ? "text-blue-900" : "text-slate-800"}`}>{i ? <Named name={i.name} short={i.short} /> : t}{recommended === t && <><RecBadge /><MockTag /></>}</span>
              <span className="mt-0.5 block text-xs leading-5 text-slate-500">{i?.desc}</span>
            </button>
          )
        })}
      </div>
      {cur && (
        <div className="space-y-2 rounded-xl bg-slate-50 p-4 text-xs leading-5 text-slate-700">
          <p className="text-sm font-semibold text-slate-900">선택: <Named name={cur.name} short={cur.short} /></p>
          <p><b className="text-emerald-700">장점</b> {cur.pros}</p>
          <p><b className="text-amber-700">주의할 점</b> {cur.caution}</p>
          <Disclosure size="sm" title="자세히 알아보기">
            <dl className="space-y-1 text-xs leading-5 text-slate-600">
              <div><dt className="inline font-semibold">순위를 매기는 지표 </dt><dd className="inline">{cur.metric}</dd></div>
            </dl>
          </Disclosure>
        </div>
      )}
    </Part>
  )
}

function WeightingPicker({ value, options, onChange, recommended }: { value: Weighting; options: Weighting[]; onChange: (w: Weighting) => void; recommended?: Weighting }) {
  const cur = WEIGHTING_INFO[value]
  return (
    <Part title="선정한 기업에 투자금을 어떻게 나눌까요?" info={<>여기서 정한 비율을 <b>기준 비중</b>이라고 합니다. 선정한 종목에 투자금을 처음 나누는 방식이며, 어떤 방식이든 종목당·섹터당 상한은 지킵니다. 2단계에서 고른 <b>비교지수</b>는 성과를 견주는 기준일 뿐, 투자금을 나누는 방식과는 관계가 없습니다.</>}>
      <div role="radiogroup" aria-label="선정한 기업에 투자금을 어떻게 나눌까요?" className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {options.map((w) => {
          const i = WEIGHTING_INFO[w]
          const on = value === w
          return (
            <button key={w} type="button" role="radio" aria-checked={on} onClick={() => onChange(w)} className={`flex gap-3 ${cardClass(on)}`}>
              <span className="min-w-0 flex-1">
                <span className={`block text-sm font-semibold ${on ? "text-blue-900" : "text-slate-800"}`}>{i ? <Named name={i.name} short={i.short} /> : w}{recommended === w && <><RecBadge /><MockTag /></>}</span>
                <span className="mt-0.5 block text-xs leading-5 text-slate-500">{i?.desc}</span>
              </span>
              {i && <ExampleBars weights={i.example} active={on} />}
            </button>
          )
        })}
      </div>
      <p className="mt-2 text-[11px] text-slate-400">막대는 <b>설명용 예시</b>입니다 (4개 기업 A~D 가정). 실제 분석 결과가 아닙니다.</p>
      {cur && (
        <div className="mt-2 space-y-2 rounded-xl bg-slate-50 p-4 text-xs leading-5 text-slate-700">
          <p className="text-sm font-semibold text-slate-900">선택: <Named name={cur.name} short={cur.short} /></p>
          <p><b className="text-amber-700">주의할 점</b> {cur.caution}</p>
          <p className="text-slate-500">{cur.exampleNote ? `예시에서 ${cur.exampleNote} · ` : ""}리포트에서는 비교를 위해 다른 나누는 방식의 결과도 함께 계산해 보여 줍니다.</p>
        </div>
      )}
    </Part>
  )
}

/** 설명용 예시 비중 막대 (실제 계산 아님). */
function ExampleBars({ weights, active }: { weights: number[]; active: boolean }) {
  return (
    <span className="flex shrink-0 items-end gap-1" role="img" aria-label={`설명용 예시: ${weights.map((v, i) => `${"ABCD"[i]} ${v}%`).join(", ")}`}>
      {weights.map((v, i) => (
        <span key={i} className="flex w-6 flex-col items-center gap-0.5">
          <span className="text-[9px] tabular-nums text-slate-500">{v}%</span>
          <span className={`w-4 rounded-t ${active ? "bg-blue-600" : "bg-slate-300"}`} style={{ height: `${Math.max(3, v * 0.9)}px` }} />
          <span className="text-[9px] font-semibold text-slate-400">{"ABCD"[i]}</span>
        </span>
      ))}
    </span>
  )
}

function NewsToggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <Part title={NEWS_INFO.title} info={NEWS_INFO.desc} aside={
      <button type="button" role="switch" aria-checked={value} aria-label={NEWS_INFO.title} onClick={() => onChange(!value)} className={`relative inline-flex h-7 w-12 shrink-0 items-center rounded-full transition focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 ${value ? "bg-blue-700" : "bg-slate-300"}`}>
        <span className={`inline-block size-5 rounded-full bg-white shadow transition ${value ? "translate-x-6" : "translate-x-1"}`} />
      </button>
    }>
      <div className="space-y-2 rounded-xl bg-slate-50 p-4 text-xs leading-5 text-slate-700">
        <p className="text-sm font-semibold text-slate-900">선택: {value ? "뉴스·공시 반영 켜짐" : "뉴스·공시 반영 꺼짐"}</p>
        <p>{value ? NEWS_INFO.on : NEWS_INFO.off}</p>
        <p><b className="text-amber-700">주의할 점</b> {NEWS_INFO.caution}</p>
        <Disclosure size="sm" title="자세히 알아보기">
          <ul className="list-disc space-y-1 pl-5 text-xs leading-5 text-slate-600">{NEWS_INFO.details.map((d) => <li key={d}>{d}</li>)}</ul>
        </Disclosure>
      </div>
    </Part>
  )
}
