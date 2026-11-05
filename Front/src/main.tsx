import React, { useEffect, useState } from "react"
import ReactDOM from "react-dom/client"
import App from "./app/App"
import { Providers } from "./app/providers"
import { createServiceAsync } from "./api/service"
import type { AnalysisService } from "./api/service"
import { isMockMode } from "./mocks/mode"
import "./index.css"

function Root() {
  const [service, setService] = useState<AnalysisService | null>(null)
  useEffect(() => {
    // 기본은 실제 서버. 개발 환경에서 ?mock=1 일 때만 목업 서비스. 환경 조건을 여기 그대로 써야 운영 빌드에서 상수 false 로 바뀌어
    // 이 import(목업 자료 전체)가 번들에서 빠진다 (다른 모듈의 상수로는 빌드 도구가 지우지 못한다).
    if ((import.meta.env.DEV || import.meta.env.VITE_ENABLE_MOCK === "1") && isMockMode()) void import("./mocks/services/MockService").then((m) => setService(new m.MockService()))
    else void createServiceAsync().then(setService)
  }, [])
  if (!service) return <div className="p-10 text-sm text-slate-500">초기화 중…</div>
  return (
    <Providers service={service}>
      <App />
    </Providers>
  )
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
