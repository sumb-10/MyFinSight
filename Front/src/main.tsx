import React, { useEffect, useState } from "react"
import ReactDOM from "react-dom/client"
import App from "./app/App"
import { Providers } from "./app/providers"
import { createServiceAsync } from "./api/service"
import type { AnalysisService } from "./api/service"
import "./index.css"

function Root() {
  const [service, setService] = useState<AnalysisService | null>(null)
  useEffect(() => { void createServiceAsync().then(setService) }, [])
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
