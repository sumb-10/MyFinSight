import type { RiskTolerance, Tendency } from "../../api/types"

export const TENDENCIES: Tendency[] = ["안정형", "안정추구형", "위험중립형", "적극투자형", "공격투자형"]

// 성향 진단 문항·점수·성향 설명은 실제 서버의 대화형 설정(backend/analysis/m1_request/profile_chat.py)에도 같은 표가 있다 — 바꾸면 함께 바꾼다 (서버 test_profile_chat 이 확인).
export const QUESTIONS = [
  { id: "loss", question: "과거에 투자금이 일시적으로 하락했을 때 어느 수준까지 감수할 수 있나요?", options: [
    { label: "약 5% 하락도 크게 부담됩니다", score: 0, loss: 0.05 }, { label: "약 10% 하락까지 감수할 수 있습니다", score: 1, loss: 0.1 },
    { label: "약 20% 하락까지 감수할 수 있습니다", score: 2, loss: 0.2 }, { label: "약 30% 이상 하락도 장기 관점에서 감수할 수 있습니다", score: 4, loss: 0.3 }] },
  { id: "reaction", question: "시장 급락 시 가장 가까운 행동은 무엇인가요?", options: [
    { label: "즉시 대부분 매도합니다", score: 0, reaction: "sell" }, { label: "일부를 줄이고 상황을 지켜봅니다", score: 1, reaction: "hold" },
    { label: "계획을 유지합니다", score: 2, reaction: "hold" }, { label: "추가 매수를 검토합니다", score: 4, reaction: "buy_more" }] },
  { id: "priority", question: "수익과 안정성 중 더 중요한 것은 무엇인가요?", options: [
    { label: "원금 변동 최소화", score: 0 }, { label: "안정성을 조금 더 중시", score: 1 }, { label: "균형", score: 2 }, { label: "높은 변동을 감수한 장기 성장", score: 4 }] },
] as const

export function computeTendency(answers: Record<string, number>): Tendency {
  const score = Object.values(answers).reduce((s, v) => s + v, 0)
  return TENDENCIES[Math.min(4, Math.floor(score / 2.3))]
}

/** 5단계 성향 라벨 → 백엔드 3단계 risk_tolerance */
export function toRiskTolerance(t: Tendency): RiskTolerance {
  if (t === "안정형" || t === "안정추구형") return "conservative"
  if (t === "위험중립형") return "moderate"
  return "aggressive"
}

export const TENDENCY_HELP: Record<Tendency, string> = {
  안정형: "원금 변동을 최소화하려는 성향입니다. 손실 감내 수준과 변동성 기준을 낮게 둡니다.",
  안정추구형: "작은 손실은 감수하되 안정적인 결과를 선호합니다.",
  위험중립형: "수익과 안정성의 균형을 추구합니다.",
  적극투자형: "더 높은 수익을 위해 변동성을 감수합니다.",
  공격투자형: "큰 변동성과 손실 가능성을 감수하고 장기 성장을 노립니다.",
}

/** 투자성향별 기본값: 진단과 다른 성향을 고르면 「이렇게 바뀝니다」로 보여 주고 고른 대로 둔다 (대화형 설정의 「성향 기본값」 질문).
 *  목표 연수익률은 따로 묻지 않으므로 진단 성향의 값을 쓴다. 서버 profile_chat.py TENDENCY_DEFAULTS 와 같다 (서버 테스트가 확인). */
export const TENDENCY_DEFAULTS: Record<Tendency, { max_drawdown_tolerance: number; loss_reaction: "sell" | "hold" | "buy_more"; target_annual_return: number }> = {
  안정형: { max_drawdown_tolerance: 0.1, loss_reaction: "sell", target_annual_return: 0.04 },
  안정추구형: { max_drawdown_tolerance: 0.15, loss_reaction: "hold", target_annual_return: 0.06 },
  위험중립형: { max_drawdown_tolerance: 0.2, loss_reaction: "hold", target_annual_return: 0.08 },
  적극투자형: { max_drawdown_tolerance: 0.25, loss_reaction: "hold", target_annual_return: 0.1 },
  공격투자형: { max_drawdown_tolerance: 0.3, loss_reaction: "buy_more", target_annual_return: 0.12 },
}

/** 「일부를 줄이고 상황을 지켜봅니다」(진단 reaction 점수 1)는 보유로 저장하지만, 보일 때는 그 뜻을 붙인다. */
export const PARTIAL_REACTION_SCORE = 1
export const reactionText = (reaction: string, reactionScore: number | undefined, ko: (x: string) => string) =>
  ko(reaction) + (reaction === "hold" && reactionScore === PARTIAL_REACTION_SCORE ? " (일부 줄이고 지켜봄)" : "")
