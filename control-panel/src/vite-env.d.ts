/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_TEACHARM_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
