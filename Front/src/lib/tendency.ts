import type { RiskTolerance, Tendency } from "../api/types"

// 투자성향·변동성 기준 표시 이름 (투자조건 화면·홈·리포트가 함께 쓴다).
// 사용자에게 보이는 성향 이름은 투자조건 화면의 다섯 가지(안정형 … 공격투자형)이다. 서버는 이를 세 단계(conservative/moderate/aggressive)로 합쳐
// 저장하므로, 다섯 가지 중 어느 것인지 저장돼 있지 않으면 세 단계에서 확인할 수 있는 범위로만 쓴다 (예: 「안정형·안정추구형」).

/** 세 단계 → 다섯 가지 이름 중 확인 가능한 범위. */
export const RISK_TOLERANCE_RANGE: Record<RiskTolerance, string> = {
  conservative: "안정형·안정추구형",
  moderate: "위험중립형",
  aggressive: "적극투자형·공격투자형",
}

export const isRiskTolerance = (x: unknown): x is RiskTolerance => x === "conservative" || x === "moderate" || x === "aggressive"

/** 표시용 투자성향: 저장된 최종 선택 성향(다섯 가지)을 먼저, 없으면 세 단계의 범위, 그것도 없으면 「성향 미확인」. 자동 진단 결과는 최종 선택이 없을 때만. */
export function tendencyLabel(t: { final?: Tendency | null; computed?: Tendency | null; code?: string | null }): string {
  if (t.final) return t.final
  if (t.computed) return t.computed
  if (isRiskTolerance(t.code)) return RISK_TOLERANCE_RANGE[t.code]
  return "성향 미확인"
}

/** 변동성 기준(low/medium/high): 이번 분석에 적용한 변동성 기준의 강도. 다섯 가지 투자성향과 일대일로 대응하는 이름이 아니다. */
export type VolPref = "low" | "medium" | "high"
export const isVolPref = (x: unknown): x is VolPref => x === "low" || x === "medium" || x === "high"
export const VOL_PREF_LABEL: Record<VolPref, string> = { low: "낮은 변동성 기준", medium: "중간 변동성 기준", high: "높은 변동성 기준" }

/** 투자성향(세 단계)의 기본 변동성 기준. 백엔드 02_intent 규칙: conservative→low, moderate→medium, aggressive→high, 요청 문장에 변동성 언급이 있으면 그것이 우선. */
export const DEFAULT_VOL_PREF: Record<RiskTolerance, VolPref> = { conservative: "low", moderate: "medium", aggressive: "high" }

/** 서버 검증 문장에 쓰인 변동성 기준 이름(validate.py PREF_KO) → 변동성 기준. 성향 이름처럼 보이지만 실제로는 변동성 기준이다. */
export const LEGACY_PREF_KO: Record<string, VolPref> = { "안정 성향": "low", "중립 성향": "medium", "적극 성향": "high" }

/** 서버 문장 속 옛 이름(「안정 성향」 등)을 변동성 기준 이름으로 바꾼다. 다른 글자는 그대로. */
export const prefTerms = (text: string) => text.replace(/(안정|중립|적극) 성향/g, (m) => VOL_PREF_LABEL[LEGACY_PREF_KO[m]])
