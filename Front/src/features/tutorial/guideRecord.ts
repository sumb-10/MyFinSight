import { isMockMode } from "../../mocks/mode"

// 리포트 가이드(튜토리얼) 안내 기록: 본 적이 있거나(seen) 안내 창에서 거절했으면(declined) 안내 창을 다시 띄우지 않는다.
// 서버에는 사용자별 기록이 없어 이 브라우저에만 저장한다. 목업 모드는 다른 키를 쓴다. 일반 모드는 브라우저 저장소를 지워야 처음으로 돌아간다.

export type GuideRecord = "seen" | "declined"

export const guideKey = () => (isMockMode() ? "myfinsight.mock.guide.v1" : "myfinsight.guide.v1")

let mem: GuideRecord | null = null  // 저장소를 못 쓰는 브라우저용 (이번 화면에서만 유지)

export function guideRecord(): GuideRecord | null {
  try {
    const v = window.localStorage.getItem(guideKey())
    if (v === "seen" || v === "declined") return v
  } catch { /* 저장소를 못 쓰면 메모리 값으로 */ }
  return mem
}

export function recordGuide(r: GuideRecord) {
  try { window.localStorage.setItem(guideKey(), r) } catch { mem = r }
}

export function clearGuideRecord() {
  mem = null
  try { window.localStorage.removeItem(guideKey()) } catch { /* ignore */ }
}
