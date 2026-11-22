// 연결 흐름을 「나중에 하기」로 넘겼다는 기록. 이번에 켠 동안(이 창을 닫을 때까지)만 기억한다 — sessionStorage.
// 연결 안 된 것이 있으면 앱을 켤 때마다 한 번 묻고, 넘기면 그 실행 동안은 다시 띄우지 않는다 (알림과 사이드바 「연결 설정」은 그대로).
// 예전에는 브라우저에 영영 남겨서(localStorage), 한 번 넘긴 뒤 키를 지우거나 설정이 바뀌어도 다시 뜨지 않았다 (2026-11-23).
// 둘 다 연결되면 App 이 흐름을 띄우지 않으므로 「끝냈다」는 기록은 따로 필요 없다.
import { isMockMode } from "../../mocks/mode"

// 목업 모드는 다른 키 (state/uiStorage.ts 와 같은 이유: 목업에서 넘긴 것이 일반 모드에 섞이지 않게)
const key = () => (isMockMode() ? "myfinsight.mock.connect.skipped" : "myfinsight.connect.skipped")

/** 이번 실행에서 연결 흐름을 이미 지나갔나. 저장소를 못 쓰면 false (매번 묻는 쪽이 안전하다) */
export function connectSkipped(): boolean {
  try { return window.sessionStorage.getItem(key()) === "1" } catch { return false }
}

/** 흐름을 끝까지 갔거나 「나중에 하기」로 넘겼다 */
export function markConnectSkipped() {
  try { window.sessionStorage.setItem(key(), "1") } catch { /* ignore */ }
}

/** 다시 묻게 한다 (목업 패널의 「처음 켠 것처럼」) */
export function clearConnectSkipped() {
  try { window.sessionStorage.removeItem(key()) } catch { /* ignore */ }
}
