/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string // 기본 /api/v1 (dev 서버 프록시 → http://localhost:8001)
  readonly VITE_PROXY_TARGET?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
