import "@testing-library/jest-dom/vitest"
import { afterEach } from "vitest"
import { cleanup } from "@testing-library/react"

// globals: false 라 RTL 의 자동 정리가 돌지 않는다 → 테스트마다 DOM 을 비운다 (한 파일에 여러 render 가 있을 때 중복 요소 방지)
afterEach(() => cleanup())
