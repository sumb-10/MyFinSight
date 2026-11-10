// 대화형 초기 투자조건 (목업). 서버가 대화를 이끄는 제안 계약(ProposedProfileChat)을 정해진 규칙으로만 흉내 낸다.
// 질문 순서·보기·답 반영·다시 묻기가 모두 여기 한 곳에 있다. 자유 문장은 해석하지 않는다 (서버 연동 때 LLM 이 맡을 부분).
// 상태는 질문별 답만 저장하고, 말풍선·초안(draft)·다음 질문은 매번 답에서 다시 만든다 → 「고치기」는 그 답(과 그 답에 기대는 답)만 지우면 끝.
// 실제 서버(backend/analysis/m1_request/profile_chat.py, POST /profile/chat …)가 이 규칙을 그대로 옮겨 쓴다 — 바꾸면 둘 다 바꾼다
// (서버 test_profile_chat 이 질문 순서·이름·고정 보기·입력 범위·정해진 말풍선이 같은지 본다).
import type { ProposedChatAnswer, ProposedChatKind, ProposedChatMessage, ProposedChatQuestion, ProposedProfileChat } from "../../api/proposed"
import type { ProfileFields, Template, Tendency } from "../../api/types"
import { DEFAULT_FORM } from "../../features/profile/defaults"
import { QUESTIONS, TENDENCIES, TENDENCY_HELP, computeTendency, toRiskTolerance } from "../../features/profile/diagnosis"
import { UNIVERSE_HELP, money } from "../../features/profile/format"
import { TEMPLATE_INFO, TEMPLATE_ORDER, templateLabel, weightingLabel } from "../../features/profile/strategyInfo"
import { ko } from "../../lib/format"
import { recommendation } from "./strategy"

type Answer = { v: unknown } | { skip: true }
export interface ProfileChatState { id: string; answers: Record<string, Answer>; error: { question_id: string; text_ko: string } | null }

type Option = ProposedChatQuestion["options"][number]
interface Q {
  id: string
  label: string
  kind: ProposedChatKind
  fields: string[] | ((v: unknown) => string[])            // 이 답이 정하는 항목 = 요약표 행 키 (features/profile/compare.tsx profileRows)
  ask: (d: ProfileFields) => string                        // 봇 질문 (그때까지의 답이 반영된 초안을 보고 만든다)
  options: (d: ProfileFields) => Option[]
  input?: ProposedChatQuestion["input"]
  allowSkip?: boolean
  apply: (d: ProfileFields, v: unknown) => void
  say: (v: unknown, d: ProfileFields) => string            // 사용자 답 말풍선
}

const clone = <T>(x: T): T => JSON.parse(JSON.stringify(x)) as T
const won = (v: number) => money(v, "KRW")

/** 종목 수에 맞춰 범위(±20%)와 종목당 상한을 같이 정한다: 상한 × 최소 종목 수 ≥ 100% 여야 비중을 다 채울 수 있다 (validateProfile 규칙). */
export function holdingsFor(n: number, base: ProfileFields["constraints"] = DEFAULT_FORM.constraints) {
  const pad = Math.max(1, Math.round(n * 0.2))
  const min = Math.max(2, n - pad), max = n + pad
  const perStock = Math.max(base.max_weight_per_stock, Math.ceil((1 - base.min_cash_ratio) / min * 100) / 100)
  return { num_holdings: { target: n, min, max }, max_weight_per_stock: perStock, max_weight_per_sector: Math.max(base.max_weight_per_sector, perStock) }
}

/** 성향 진단 3문항 점수로 계산한 성향을 초안에 넣는다 (최종 성향은 「성향 확인」 질문에서 정한다). */
function diagnose(d: ProfileFields) {
  const dg = d.diagnosis!
  const t = computeTendency(dg.answers)
  dg.computed_tendency = t
  dg.final_tendency = t
  d.risk_type_computed = toRiskTolerance(t)
  d.risk.risk_tolerance = toRiskTolerance(t)
  d.risk_type_overridden = false
}

const diagQ = (i: 0 | 1 | 2): Q => {
  const q = QUESTIONS[i]
  return {
    id: q.id, label: "투자성향 진단", kind: "choice",
    fields: q.id === "loss" ? ["risk.max_drawdown_tolerance"] : q.id === "reaction" ? ["risk.loss_reaction"] : [],
    ask: () => (i === 0 ? `이제 투자성향을 알아볼게요. 질문 ${QUESTIONS.length}개만 답해 주세요.\n${q.question}` : q.question),
    options: () => q.options.map((o, idx) => ({ value: idx, label_ko: o.label })),
    apply: (d, v) => {
      const o = q.options[v as number] as (typeof q.options)[number] & { loss?: number; reaction?: "sell" | "hold" | "buy_more" }
      d.diagnosis!.answers[q.id] = o.score
      if (o.loss !== undefined) d.risk.max_drawdown_tolerance = o.loss
      if (o.reaction !== undefined) d.risk.loss_reaction = o.reaction
      diagnose(d)
    },
    say: (v) => q.options[v as number].label,
  }
}

export const CHAT_QUESTIONS: Q[] = [
  {
    id: "purpose", label: "투자 목적", kind: "choice", fields: ["horizon.purpose"],
    ask: () => "이번 투자의 목적은 무엇인가요?",
    options: () => (["wealth_growth", "income", "capital_preservation", "retirement"] as const).map((v) => ({ value: v, label_ko: ko(v) })),
    apply: (d, v) => { d.horizon.purpose = v as ProfileFields["horizon"]["purpose"] },
    say: (v) => ko(v),
  },
  {
    id: "amount", label: "처음 투자할 금액", kind: "money", fields: ["capital.initial_amount"],
    ask: () => "처음에 얼마로 시작할까요? 원화 기준으로 알려 주세요.",
    options: () => [5_000_000, 10_000_000, 30_000_000, 50_000_000].map((v) => ({ value: v, label_ko: won(v) })),
    input: { min: 100_000, max: 10_000_000_000, step: 100_000, unit_ko: "원" },
    apply: (d, v) => { d.capital.initial_amount = v as number; d.capital.currency = "KRW" },
    say: (v) => won(v as number),
  },
  {
    id: "monthly", label: "매월 추가 투자금", kind: "money", fields: ["capital.monthly"],
    ask: (d) => `매월 추가로 투자할 금액이 있나요? 있다면 매월 ${d.capital.contribution_day}일에 넣는 것으로 계산해요.`,
    options: () => [0, 300_000, 500_000, 1_000_000].map((v) => ({ value: v, label_ko: v ? `매월 ${won(v)}` : "추가 투자 없음" })),
    input: { min: 0, max: 100_000_000, step: 10_000, unit_ko: "원" },
    apply: (d, v) => { d.capital.monthly_contribution = v as number },
    say: (v) => ((v as number) ? `매월 ${won(v as number)}` : "추가 투자는 없어요"),
  },
  {
    id: "years", label: "투자 기간", kind: "number", fields: ["horizon.target_years"],
    ask: () => "앞으로 몇 년 동안 투자할 계획인가요?",
    options: () => [1, 3, 5, 10].map((v) => ({ value: v, label_ko: `${v}년` })),
    input: { min: 1, max: 10, step: 1, unit_ko: "년" },
    apply: (d, v) => { d.horizon.target_years = v as number },
    say: (v) => `${v as number}년`,
  },
  diagQ(0), diagQ(1), diagQ(2),
  {
    id: "tendency", label: "투자성향", kind: "choice", fields: ["tendency"],
    ask: (d) => { const t = d.diagnosis!.computed_tendency; return `답변을 보면 ‘${t}’에 가까워요. ${TENDENCY_HELP[t]}\n이 성향으로 정할까요? 다른 성향을 고를 수도 있어요.` },
    options: (d) => TENDENCIES.map((t) => ({ value: t, label_ko: t === d.diagnosis!.computed_tendency ? `${t} (진단 결과)` : t, help_ko: TENDENCY_HELP[t], recommended: t === d.diagnosis!.computed_tendency })),
    apply: (d, v) => {
      const t = v as Tendency, dg = d.diagnosis!
      dg.final_tendency = t
      d.risk.risk_tolerance = toRiskTolerance(t)
      d.risk_type_overridden = t !== dg.computed_tendency
    },
    say: (v, d) => (v === d.diagnosis!.computed_tendency ? `좋아요, ${v as string}으로 할게요` : `${v as string}으로 할게요`),
  },
  {
    id: "universe", label: "투자 대상 지수", kind: "multi", fields: ["constraints.universe"],
    ask: () => "어느 시장의 종목에서 고를까요? 여러 개 골라도 돼요.",
    options: () => (["SP500", "NASDAQ100", "KOSPI200"] as const).map((u) => ({ value: u, label_ko: ko(u), help_ko: UNIVERSE_HELP[u] })),
    apply: (d, v) => { d.constraints.universe = v as ProfileFields["constraints"]["universe"] },
    say: (v) => (v as string[]).map(ko).join(", "),
  },
  {
    id: "holdings", label: "종목 수", kind: "number", fields: ["constraints.num_holdings", "constraints.max_weight"],
    ask: () => "몇 종목 정도에 나눠 담을까요? 종목이 많을수록 한 종목에 덜 쏠려요.",
    options: () => [5, 10, 15, 20].map((v) => ({ value: v, label_ko: `${v}개` })),
    input: { min: 3, max: 30, step: 1, unit_ko: "개" },
    apply: (d, v) => { Object.assign(d.constraints, holdingsFor(v as number, d.constraints)) },
    say: (v) => `${v as number}개 정도요`,
  },
  {
    id: "strategy", label: "종목을 고르는 기준", kind: "choice", fields: (v) => (v === "recommended" ? ["strategy.template", "strategy.weighting", "strategy.news"] : ["strategy.template"]),
    ask: (d) => `마지막으로 종목을 고르는 기준을 정해요. ‘${d.diagnosis!.final_tendency}’ 성향이면 첫 번째 추천을 먼저 권해요.`,
    options: (d) => {
      const rec = recommendation(d.diagnosis!.final_tendency).recommended
      return [
        { value: "recommended", label_ko: `추천: ${templateLabel(rec.template)} · ${weightingLabel(rec.baseline_weighting)}`, help_ko: recommendation(d.diagnosis!.final_tendency).reasons_ko[0], recommended: true },
        ...TEMPLATE_ORDER.map((t) => ({ value: t, label_ko: templateLabel(t), help_ko: TEMPLATE_INFO[t].desc })),
      ]
    },
    apply: (d, v) => {
      if (v === "recommended") { const r = recommendation(d.diagnosis!.final_tendency).recommended; d.strategy_preference = { template: r.template as Template, baseline_weighting: r.baseline_weighting as ProfileFields["strategy_preference"]["baseline_weighting"], use_news_tilt: r.use_news_tilt } }
      else d.strategy_preference = { ...d.strategy_preference, template: v as Template }
    },
    say: (v, d) => (v === "recommended" ? `추천대로 할게요 (${templateLabel(d.strategy_preference.template)})` : templateLabel(v as string)),
  },
]

const GREETING: ProposedChatMessage = { id: "hello", role: "bot", text_ko: "안녕하세요! 몇 가지만 여쭤보고 기본 투자조건을 만들어 드릴게요. 답하신 내용은 마지막에 한 번에 확인하고 저장해요." }
const DONE_TEXT = "필요한 내용을 모두 들었어요. 아래 요약을 확인하고 저장해 주세요. 나머지 조건은 기본값으로 두었고, 저장한 뒤 언제든 바꿀 수 있어요."

export const newChat = (id: string): ProfileChatState => ({ id, answers: {}, error: null })

/** 지금 답할 질문 (다 답했으면 null). */
export const currentQuestion = (st: ProfileChatState): Q | null => CHAT_QUESTIONS.find((q) => !st.answers[q.id]) ?? null

/** 답에서 말풍선·초안·다음 질문을 만든다.
 *  말풍선은 처음으로 답이 비어 있는 질문까지만 보인다. 그 뒤에 이미 답한 질문(「고치기」로 앞 답만 지운 경우)은
 *  말풍선은 숨기되 초안에는 반영해 두고, 지금 질문에 답하면 다시 나타난다 → 고친 뒤 나머지를 다시 답할 필요가 없다. */
export function chatView(st: ProfileChatState): ProposedProfileChat {
  const draft = clone(DEFAULT_FORM)
  const messages: ProposedChatMessage[] = [GREETING]
  const asked = new Set<string>()
  let current: Q | null = null
  let question: ProposedChatQuestion | null = null
  for (const q of CHAT_QUESTIONS) {
    const a = st.answers[q.id]
    if (!current) messages.push({ id: `${q.id}:q`, role: "bot", text_ko: q.ask(draft), question_id: q.id })
    if (!a) {
      if (!current) { current = q; question = { id: q.id, field_label_ko: q.label, kind: q.kind, options: q.options(draft), input: q.input ?? null, allow_skip: !!q.allowSkip } }
      continue
    }
    if (!("skip" in a)) { q.apply(draft, a.v); (typeof q.fields === "function" ? q.fields(a.v) : q.fields).forEach((f) => asked.add(f)) }
    if (!current) messages.push({ id: `${q.id}:a`, role: "user", text_ko: "skip" in a ? "건너뛸게요 (기본값 사용)" : q.say(a.v, draft), question_id: q.id, editable: true })
  }
  const later = current ? CHAT_QUESTIONS.slice(CHAT_QUESTIONS.indexOf(current) + 1).filter((q) => st.answers[q.id]).length : 0
  if (later) messages.push({ id: `${current!.id}:keep`, role: "bot", text_ko: `이 질문만 다시 답해 주세요. 뒤에 답한 ${later}개는 그대로 두었다가 답하시면 다시 보여 드릴게요.`, question_id: current!.id })
  if (current && st.error?.question_id === current.id) messages.push({ id: `${current.id}:retry`, role: "bot", text_ko: st.error.text_ko, question_id: current.id })
  if (!current) messages.push({ id: "done", role: "bot", text_ko: DONE_TEXT })
  const done = CHAT_QUESTIONS.filter((q) => st.answers[q.id]).length
  return { chat_id: st.id, state: current ? "asking" : "review", messages, question, progress: { done, total: CHAT_QUESTIONS.length }, draft, asked_fields: [...asked] }
}

/** 지금 질문에 답한다. 맞지 않는 값이면 답을 저장하지 않고 다시 묻는 안내를 남긴다. 질문 ID 확인은 부르는 쪽(MockService)이 한다. */
export function answerChat(st: ProfileChatState, a: ProposedChatAnswer): ProfileChatState {
  const q = currentQuestion(st)!
  const next = clone(st)
  const retry = (text_ko: string) => ({ ...next, error: { question_id: q.id, text_ko } })
  if (a.skip) return q.allowSkip ? { ...next, answers: { ...next.answers, [q.id]: { skip: true } }, error: null } : retry("이 질문은 꼭 답해 주셔야 해요. 아래에서 골라 주세요.")
  const v = a.number ?? a.option_value
  const values = chatView(st).question!.options.map((o) => o.value)  // 그 질문 시점의 보기 (앞 답으로 정해진다)
  if (q.kind === "choice" && !values.includes(v)) return retry("아래 보기 중에서 골라 주세요.")
  if (q.kind === "multi" && !(Array.isArray(v) && v.length > 0 && v.every((x) => values.includes(x)))) return retry("하나 이상 골라 주세요.")
  if ((q.kind === "money" || q.kind === "number") && q.input) {
    const { min, max, unit_ko } = q.input
    const fmt = (n: number) => (unit_ko === "원" ? won(n) : `${n}${unit_ko}`)
    if (typeof v !== "number" || !Number.isFinite(v) || v < min || v > max) return retry(`${fmt(min)} 이상 ${fmt(max)} 이하로 알려 주세요.`)
    if (unit_ko !== "원" && !Number.isInteger(v)) return retry("정수로 알려 주세요.")
  }
  return { ...next, answers: { ...next.answers, [q.id]: { v } }, error: null }
}

/** 고친 답에 기대는 질문: 성향 진단 답이 바뀌면 진단 결과가 바뀌므로 「성향 확인」도 다시 묻는다.
 *  (종목 기준의 「추천」은 성향에서 매번 다시 계산하므로 지우지 않는다.) */
const DEPENDENTS: Record<string, string[]> = Object.fromEntries(QUESTIONS.map((q) => [q.id, ["tendency"]]))

/** 그 질문만 다시 묻는다 (그 답과 그 답에 기대는 답만 지우고, 나머지 답은 그대로 둔다). */
export function rewindChat(st: ProfileChatState, questionId: string): ProfileChatState {
  if (!CHAT_QUESTIONS.some((q) => q.id === questionId)) return st
  const drop = new Set([questionId, ...(DEPENDENTS[questionId] ?? [])])
  return { ...st, answers: Object.fromEntries(Object.entries(st.answers).filter(([k]) => !drop.has(k))), error: null }
}
