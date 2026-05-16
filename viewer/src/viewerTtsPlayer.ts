export type ViewerTtsViseme = {
  at_ms?: number;
  vowel?: string;
  intensity?: number;
  hold_ms?: number;
};

export type ViewerTtsPayload = {
  mime: string;
  data: string;
  duration_ms?: number;
  visemes?: ViewerTtsViseme[];
  /** When false, play audio only (co-host voice; no Luna lip-sync). */
  driveAvatar?: boolean;
};

let activeAudio: HTMLAudioElement | null = null;
let objectUrl: string | null = null;
let visemeTimers: number[] = [];

function clearVisemeTimers() {
  for (const t of visemeTimers) window.clearTimeout(t);
  visemeTimers = [];
}

export function stopViewerTts() {
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

/** Play TTS in the browser (OBS window / Browser Source audio). */
export function playViewerTts(payload: ViewerTtsPayload, onEnded: () => void) {
  stopViewerTts();
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

  const finish = () => {
    stopViewerTts();
    onEnded();
  };

  audio.onended = finish;
  audio.onerror = finish;

  void audio.play().then(() => {
    if (payload.driveAvatar === false) return;
    for (const v of payload.visemes ?? []) {
      const at = Math.max(0, Number(v.at_ms) || 0);
      const t = window.setTimeout(() => {
        window.dispatchEvent(
          new CustomEvent("luna-avatar-viseme", {
            detail: {
              vowel: String(v.vowel || ""),
              intensity: Number.isFinite(v.intensity) ? Number(v.intensity) : 1,
              holdMs: Number.isFinite(v.hold_ms) ? Number(v.hold_ms) : 120,
            },
          }),
        );
      }, at);
      visemeTimers.push(t);
    }
  }).catch(finish);
}
