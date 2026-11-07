// 목업 모드 스위치. 기본은 일반 모드(실제 서버)이고, 목업은 아래 두 조건을 모두 만족할 때만 켜진다.
//  1) 허용된 환경: 개발 서버(import.meta.env.DEV) 또는 빌드할 때 VITE_ENABLE_MOCK=1 을 명시한 경우. 운영 빌드에서는 상수 false 가 되어
//     목업 코드 묶음(src/mocks/services 등)이 번들에 들어가지 않는다 (main.tsx 의 동적 import 가 죽은 코드로 제거됨).
//  2) 주소에 ?mock=1 이 있을 때. 해시 라우팅(#/reports/…)이라 화면을 옮겨도 ?mock=1 은 그대로 남는다. 주소에서 빼면 일반 모드로 돌아간다.

export const MOCK_ALLOWED: boolean = import.meta.env.DEV || import.meta.env.VITE_ENABLE_MOCK === "1"

const requested = (): boolean => {
  try { return new URLSearchParams(window.location.search).get("mock") === "1" } catch { return false }
}

/** 지금 목업 모드인가. 페이지를 처음 띄울 때 한 번 정해지고(서비스 객체가 그때 만들어진다), 주소를 바꿔 다시 불러오면 바뀐다. */
export const isMockMode = (): boolean => MOCK_ALLOWED && requested()

/** 목업 모드를 끄고 실제 서버 화면으로 돌아가는 주소 (현재 해시 경로는 유지). */
export function exitMockHref(): string {
  const u = new URL(window.location.href)
  u.searchParams.delete("mock")
  return u.toString()
}
