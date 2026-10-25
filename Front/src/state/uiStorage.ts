// 브라우저에만 두는 편의 상태 (서버가 진실). 깨져도 화면은 동작해야 하므로 모든 접근을 try/catch 로 감싼다.
const KEY = "myfinsight.ui.v1"
const LEGACY_KEY = "myfinsight.local.v1"

export interface UiState { version: 1; draftIdea?: string; activeRequestId?: string | null; activeRunId?: string | null; lastRoute?: string; legacyImported?: boolean; prefillIdea?: string | null; prefillOverrides?: Record<string, unknown> | null }

export function loadUi(): UiState {
  try {
    const raw = window.localStorage.getItem(KEY)
    if (raw) { const v = JSON.parse(raw) as UiState; if (v && v.version === 1) return v }
  } catch { /* ignore */ }
  return { version: 1 }
}

export function saveUi(patch: Partial<UiState>): UiState {
  const next = { ...loadUi(), ...patch, version: 1 as const }
  try { window.localStorage.setItem(KEY, JSON.stringify(next)) } catch { /* ignore */ }
  return next
}

/** 예전 fixture 앱의 프로필(localStorage myfinsight.local.v1)이 있으면 위저드 미리 채우기용으로 돌려준다. */
export function loadLegacyProfile(): Record<string, unknown> | null {
  try {
    const raw = window.localStorage.getItem(LEGACY_KEY)
    if (!raw) return null
    const v = JSON.parse(raw) as { profile?: Record<string, unknown> | null }
    return v?.profile ?? null
  } catch { return null }
}

export function clearLegacy() { try { window.localStorage.removeItem(LEGACY_KEY) } catch { /* ignore */ } }
