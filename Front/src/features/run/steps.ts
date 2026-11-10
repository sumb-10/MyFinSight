// 분석 진행 화면의 단계 이름. 키 = 백엔드 단계 ID(run_step.step, backend/analysis/executor/stages.py STAGES)·묶음 ID(schemas/run.py BUCKETS).
// 단계 ID·순서·상태 값은 서버 것을 그대로 쓰고, 여기서는 사용자에게 보이는 이름과 짧은 설명만 바꾼다. 모르는 ID 는 서버 label_ko 를 쓴다.

import type { ProposedRunWarning } from "../../api/proposed"
import type { RunStep } from "../../api/types"

export interface StepText { title: string; desc: string }

export const STEP_TEXT: Record<string, StepText> = {
  "01_request": { title: "투자조건 확정과 자료 준비", desc: "확정한 조건으로 분석 기준일과 과거 성과 분석 기간을 정하고, 필요한 가격·환율 자료를 불러옵니다." },
  "02_intent": { title: "투자 아이디어 이해", desc: "조건 확인 단계에서 정리한 투자 의도(테마·선정 기준)를 불러옵니다." },
  "03_candidates": { title: "투자 후보 기업 찾기", desc: "투자 시장과 제외 조건, 시가총액·거래대금 하한에 맞는 후보 기업을 모읍니다." },
  "04_tagging": { title: "투자 테마에 맞는 기업 고르기", desc: "AI가 후보 기업이 투자 테마에 해당하는지 하나씩 판단합니다." },
  "05_selection": { title: "투자 조건에 맞는 종목 선정", desc: "고른 선정 기준의 지표로 후보의 순위를 매겨 목표 종목 수만큼 고릅니다." },
  "06_explain": { title: "기업별 선정 이유 정리", desc: "선정된 기업마다 지표·뉴스·공시를 바탕으로 선정 이유를 정리합니다." },
  "07_backtest_spec": { title: "과거 성과 분석 조건 설정", desc: "과거 성과 분석 기간·투자금·비교지수를 정하고, 분석 시작일 시점의 자료만으로 종목을 다시 고릅니다." },
  "10f_current": { title: "현재 시점의 종목별 투자 비중 계산", desc: "분석 기준일에 선정 종목의 투자 비중을 계산하고 투자금을 종목별로 나눕니다." },
  "10_targets": { title: "과거 분석 시작 시점의 투자 비중 계산", desc: "과거 성과 분석 시작일에 비중 배분 방식별 비중을 계산하고, 뉴스 반영을 켰다면 당시 뉴스·공시로 조정한 비중도 만듭니다." },
  "10w_paths": { title: "투자 비중 재조정(리밸런싱) 시점별 계산", desc: "과거 성과 분석 기간의 재조정 날짜마다 그 시점까지의 자료만으로 비중을 다시 계산합니다. 종목은 그대로 둡니다." },
  "11_backtest": { title: "과거 성과 계산", desc: "구성한 포트폴리오를 과거 가격으로 운용했을 때의 수익률과 하락 폭을 계산합니다." },
  "12_validation": { title: "내 투자조건 충족 여부 점검", desc: "허용 낙폭·목표 수익률·비중 상한 같은 조건을 지켰는지 확인하고 추천안을 고릅니다." },
  "13_results": { title: "분석 결과 모으기", desc: "선정·비중·과거 성과·점검 결과와 근거 자료를 하나로 모읍니다." },
  "14_report": { title: "분석 결과 정리 및 리포트 작성", desc: "리포트를 작성하고 숫자와 근거가 실제 결과와 맞는지 확인합니다." },
}

export const BUCKET_TEXT: Record<string, string> = {
  conditions: "조건과 자료 확인",
  candidates: "종목 선정과 투자 비중 계산",
  backtest: "과거 성과 분석",
  validation: "내 투자조건 충족 여부 점검",
  report: "분석 결과 정리 및 리포트 작성",
}

export const stepTitle = (step: string, fallback: string) => STEP_TEXT[step]?.title ?? fallback

/** 서버 요약 "본문 · 확인 필요 N건: 경고1; 경고2" 를 나눈다 (backend/analysis/executor/runner.py 의 형식). 원본 문자열은 그대로 두고 표시만 나눈다. */
export function splitSummary(summary: string | null | undefined): { main: string; warnings: string[]; warnCount: number } {
  if (!summary) return { main: "", warnings: [], warnCount: 0 }
  const i = summary.indexOf(" · 확인 필요 ")
  if (i < 0) return { main: summary, warnings: [], warnCount: 0 }
  const m = /^ · 확인 필요 (\d+)건: ([\s\S]*)$/.exec(summary.slice(i))
  if (!m) return { main: summary, warnings: [], warnCount: 0 }
  return { main: summary.slice(0, i), warnings: m[2].split("; ").map((w) => w.trim()).filter(Boolean), warnCount: Number(m[1]) }
}

export interface RunNote { key: string; text: string; from: string[]; count?: number }  // count: 같은 문구가 나온 횟수 (전체 경고 목록이 있을 때만)
export interface RunNotes {
  notes: RunNote[]        // 본문이 있는 고유 안내 (같은 문구는 하나, 나온 단계를 함께)
  unlisted: number        // 서버가 건수만 주고 본문을 주지 않은 안내
  total: number           // 화면 전체 개수 = 고유 안내 + unlisted
  keys: string[]          // 새 안내 판별용 (스크린리더 알림). 안내에 ID 가 없어 본문은 문구로, unlisted 는 단계+순번으로 구분한다
  byBucket: Record<string, number>  // 묶음 안에서 센 수. 같은 안내가 여러 묶음에서 나오면 묶음마다 세므로 합이 total 과 다를 수 있다
}

export function collectNotes(steps: RunStep[]): RunNotes {
  const byText = new Map<string, string[]>()
  const bucketTexts: Record<string, Set<string>> = {}
  const bucketHidden: Record<string, number> = {}
  const unlistedKeys: string[] = []
  for (const s of steps) {
    const sp = splitSummary(s.summary)
    const texts = (bucketTexts[s.bucket] ??= new Set())
    for (const w of sp.warnings) {
      const from = stepTitle(s.step, s.label_ko)
      const seen = byText.get(w) ?? []
      byText.set(w, seen.includes(from) ? seen : [...seen, from])
      texts.add(w)
    }
    const hidden = Math.max(0, sp.warnCount - sp.warnings.length)
    for (let i = 0; i < hidden; i++) unlistedKeys.push(`unlisted:${s.step}:${i}`)
    bucketHidden[s.bucket] = (bucketHidden[s.bucket] ?? 0) + hidden
  }
  const byBucket = Object.fromEntries(Object.entries(bucketTexts).map(([b, texts]) => [b, texts.size + (bucketHidden[b] ?? 0)]))
  const notes = [...byText].map(([text, from]) => ({ key: `text:${text}`, text, from }))
  return { notes, unlisted: unlistedKeys.length, total: notes.length + unlistedKeys.length, keys: [...notes.map((n) => n.key), ...unlistedKeys], byBucket }
}

/** 전체 경고 목록(제안 기능 getRunWarnings)으로 만든 안내. 같은 문구는 하나로 묶고 나온 단계와 횟수를 함께 둔다. 요약에 빠진 안내가 없으므로 unlisted 는 0. */
export function notesFromWarnings(ws: ProposedRunWarning[], steps: RunStep[]): RunNotes {
  const byText = new Map<string, { from: string[]; count: number }>()
  const bucketOf = new Map(steps.map((s) => [s.step, s.bucket]))
  const bucketTexts: Record<string, Set<string>> = {}
  for (const w of ws) {
    const e = byText.get(w.message_ko) ?? { from: [], count: 0 }
    const from = stepTitle(w.step, w.step_label_ko)
    byText.set(w.message_ko, { from: e.from.includes(from) ? e.from : [...e.from, from], count: e.count + w.count })
    const b = bucketOf.get(w.step)
    if (b) (bucketTexts[b] ??= new Set()).add(w.message_ko)
  }
  const notes = [...byText].map(([text, x]) => ({ key: `text:${text}`, text, from: x.from, count: x.count }))
  return { notes, unlisted: 0, total: notes.length, keys: notes.map((n) => n.key), byBucket: Object.fromEntries(Object.entries(bucketTexts).map(([b, t]) => [b, t.size])) }
}
