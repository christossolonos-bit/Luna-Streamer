export type ViewerTtsViseme = {
  at_ms?: number;
  vowel?: string;
  intensity?: number;
  hold_ms?: number;
};

export type ViewerTtsAvatar = "luna" | "cohost" | "himari";

export type ViewerTtsPayload = {
  mime: string;
  data: string;
  duration_ms?: number;
  visemes?: ViewerTtsViseme[];
  /** When false, play audio only (co-host voice; no Luna lip-sync). */
  driveAvatar?: boolean;
  /** Lip-sync target when ``driveAvatar`` is true. */
  avatar?: ViewerTtsAvatar;
};

let activeAudio: HTMLAudioElement | null = null;
let objectUrl: string | null = null;
let visemeTimers: number[] = [];
let playGeneration = 0;

function clearVisemeTimers() {
  for (const t of visemeTimers) window.clearTimeout(t);
  visemeTimers = [];
}

export function stopViewerTts() {
  playGeneration += 1;
  clearVisemeTimers();
  if (activeAudio) {
    activeAudio.pause();
    activeAudio.src = "";
    activeAudio = null;
  }
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  }
}

function safetyTimeoutMs(audio: HTMLAudioElement, payload: ViewerTtsPayload): number {
  const fromMeta =
    Number.isFinite(audio.duration) && audio.duration > 0
      ? audio.duration * 1000 + 3000
      : 0;
  const fromPayload = (payload.duration_ms || 0) * 1.25 + 2500;
  const charEst = 8000;
  return Math.min(120_000, Math.max(6000, fromMeta, fromPayload, charEst));
}

/** Play TTS in the browser (OBS window / Browser Source audio). */
export function playViewerTts(payload: ViewerTtsPayload, onEnded: () => void) {
  stopViewerTts();
  const gen = playGeneration;
  const raw = (payload.data || "").trim();
  if (!raw) {
    onEnded();
    return;
  }
  const binary = atob(raw);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  const blob = new Blob([bytes], { type: payload.mime || "audio/mpeg" });
  objectUrl = URL.createObjectURL(blob);
  const audio = new Audio(objectUrl);
  activeAudio = audio;

  let finished = false;
  let safetyTimer = 0;

  const finish = () => {
    if (finished || gen !== playGeneration) return;
    finished = true;
    if (safetyTimer) window.clearTimeout(safetyTimer);
    stopViewerTts();
    onEnded();
  };

  audio.onended = () => finish();

  audio.onerror = () => finish();

  const armSafety = () => {
    if (finished || gen !== playGeneration) return;
    if (safetyTimer) window.clearTimeout(safetyTimer);
    safetyTimer = window.setTimeout(() => finish(), safetyTimeoutMs(audio, payload));
  };

  audio.addEventListener("loadedmetadata", armSafety, { once: true });
  audio.addEventListener("durationchange", armSafety, { once: true });

  void audio.play().then(() => {
    armSafety();
    if (payload.driveAvatar === false) return;
    for (const v of payload.visemes ?? []) {
      const at = Math.max(0, Number(v.at_ms) || 0);
      const t = window.setTimeout(() => {
        if (gen !== playGeneration) return;
        window.dispatchEvent(
          new CustomEvent("luna-avatar-viseme", {
            detail: {
              vowel: String(v.vowel || ""),
              intensity: Number.isFinite(v.intensity) ? Number(v.intensity) : 1,
              holdMs: Number.isFinite(v.hold_ms) ? Number(v.hold_ms) : 120,
              avatar: payload.avatar,
            },
          }),
        );
      }, at);
      visemeTimers.push(t);
    }
  }).catch(() => finish());
}
