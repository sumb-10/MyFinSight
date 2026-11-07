import { useEffect, useState } from "react"
import { isMockMode } from "../../mocks/mode"

// 「[예시]」 리포트: 리포트 목록 맨 위에 늘 두는 예시 리포트(튜토리얼과 같은 자료). 서버에는 없고, 지우기는 이 브라우저에만 숨김으로 남긴다.
// 새 리포트 배지·리포트 개수에는 넣지 않는다 (목록 화면이 따로 그린다).

export const EXAMPLE_REPORT_ID = "example"
/** 목록에 보이는 이름·날짜 (예시 자료 = 목업 「정상 추천」 시나리오와 같은 값. 목록 화면이 목업 자료를 불러오지 않게 여기 적어 둔다) */
export const EXAMPLE_ROW = { name: "[예시] 미국 반도체 장비·메모리 분산 투자", summary: "리포트 보는 법을 익히는 예시 리포트입니다. 실제 분석 결과가 아닙니다.", as_of: "2026-10-30", created_at: "2026-10-31" }

const KEY = () => (isMockMode() ? "myfinsight.mock.exampleReport.v1" : "myfinsight.exampleReport.v1")
const EVENT = "myfinsight:example-report"

export function isExampleHidden(): boolean {
  try { return window.localStorage.getItem(KEY()) === "hidden" } catch { return false }
}

export function setExampleHidden(hidden: boolean) {
  try { if (hidden) window.localStorage.setItem(KEY(), "hidden"); else window.localStorage.removeItem(KEY()) } catch { /* 저장소를 못 쓰면 이번 화면에서만 반영 */ }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: hidden }))
}

/** 예시 리포트를 목록에 보일지. 다른 화면에서 지우거나 되돌리면 바로 따라 바뀐다. */
export function useExampleVisible(): boolean {
  const [hidden, setHidden] = useState(isExampleHidden)
  useEffect(() => {
    const on = (e: Event) => setHidden((e as CustomEvent<boolean>).detail ?? isExampleHidden())
    window.addEventListener(EVENT, on)
    return () => window.removeEventListener(EVENT, on)
  }, [])
  return !hidden
}
