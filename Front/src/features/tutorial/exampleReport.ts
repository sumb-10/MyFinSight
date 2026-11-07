import { useEffect, useState } from "react"
import { isMockMode } from "../../mocks/mode"

// 「예시」 리포트: 리포트 목록 맨 위에 늘 두는 예시 리포트(튜토리얼과 같은 자료). 서버에는 없고, 지우기·이름 바꾸기는 이 브라우저에만 남긴다.
// 새 리포트 배지·리포트 개수에는 넣지 않는다 (목록 화면이 따로 그린다).

export const EXAMPLE_REPORT_ID = "example"
/** 목록에 보이는 기본 이름·날짜 (예시 자료 = 목업 「정상 추천」 시나리오와 같은 값. 목록 화면이 목업 자료를 불러오지 않게 여기 적어 둔다).
 *  「예시」는 이름에 넣지 않고 배지로만 보여 준다. */
export const EXAMPLE_ROW = { name: "미국 반도체 장비·메모리 분산 투자", summary: "리포트 보는 법을 익히는 예시 리포트입니다. 실제 분석 결과가 아닙니다.", as_of: "2026-10-30", created_at: "2026-10-31" }
export const EXAMPLE_NAME_MAX = 60

const KEY = () => (isMockMode() ? "myfinsight.mock.exampleReport.v1" : "myfinsight.exampleReport.v1")
const NAME_KEY = () => `${KEY()}.name`
const EVENT = "myfinsight:example-report"

const read = (k: string) => { try { return window.localStorage.getItem(k) } catch { return null } }
const write = (k: string, v: string | null) => { try { if (v === null) window.localStorage.removeItem(k); else window.localStorage.setItem(k, v) } catch { /* 저장소를 못 쓰면 이번 화면에서만 반영 */ } }
const announce = () => window.dispatchEvent(new CustomEvent(EVENT))

let memHidden: boolean | null = null  // 저장소를 못 쓰는 브라우저용
let memName: string | null | undefined

export function isExampleHidden(): boolean { return memHidden ?? read(KEY()) === "hidden" }
export function setExampleHidden(hidden: boolean) { memHidden = hidden; write(KEY(), hidden ? "hidden" : null); announce() }

/** 직접 정한 이름 (없으면 null) */
export function exampleCustomName(): string | null { return memName !== undefined ? memName : read(NAME_KEY()) }
export const exampleName = () => exampleCustomName() ?? EXAMPLE_ROW.name
/** null = 기본 이름으로 되돌리기 */
export function setExampleName(name: string | null) {
  const v = name?.trim() ? name.trim().slice(0, EXAMPLE_NAME_MAX) : null
  memName = v; write(NAME_KEY(), v); announce()
}

/** 예시 리포트를 목록에 보일지와 표시 이름. 다른 화면에서 지우거나 이름을 바꾸면 바로 따라 바뀐다. */
export function useExample(): { visible: boolean; name: string } {
  const [s, setS] = useState(() => ({ visible: !isExampleHidden(), name: exampleName() }))
  useEffect(() => {
    const on = () => setS({ visible: !isExampleHidden(), name: exampleName() })
    window.addEventListener(EVENT, on)
    return () => window.removeEventListener(EVENT, on)
  }, [])
  return s
}
export const useExampleVisible = () => useExample().visible

/** 테스트용: 메모리 상태 초기화 */
export function resetExampleMemory() { memHidden = null; memName = undefined }
