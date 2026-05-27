/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_LUNA_NAME?: string;
  readonly VITE_HIMARI_NAME?: string;
  readonly VITE_VIKTOR_NAME?: string;
  readonly VITE_YOUTUBE_CHANNEL_URL?: string;
  readonly VITE_YOUTUBE_CHANNEL_HANDLE?: string;
  readonly VITE_YOUTUBE_CHANNEL_TITLE?: string;
  readonly VITE_YOUTUBE_VIDEO_IDS?: string;
  readonly VITE_BASE_PATH?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
