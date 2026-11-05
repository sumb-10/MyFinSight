/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string // 기본 /api/v1 (dev 서버 프록시 → http://localhost:8001)
  readonly VITE_PROXY_TARGET?: string
  readonly VITE_ENABLE_MOCK?: string // "1" 이면 개발 서버가 아닌 빌드에서도 ?mock=1 목업 모드를 허용 (기본: 개발 서버에서만)
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
