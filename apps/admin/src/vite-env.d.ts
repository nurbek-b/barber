/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  /** Firebase Hosting: Cloud Run URL for the WebSocket (e.g. https://barber-api-xxxx.run.app) */
  readonly VITE_WS_URL?: string;
}
