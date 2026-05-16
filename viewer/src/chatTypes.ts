export type BridgeChatMessage = {
  type: "chat";
  user: string;
  text: string;
  channel: string;
  ts?: number;
};

export type BridgeAssistantMessage = {
  type: "assistant";
  user: string;
  text: string;
  channel: string;
  ts?: number;
};

/** One streamed token chunk; merge into the in-progress assistant line in the UI. */
export type BridgeAssistantDeltaMessage = {
  type: "assistant_delta";
  user: string;
  text: string;
  channel: string;
};

export type BridgeStatusMessage = {
  type: "status";
  text: string;
};

export type BridgeControlSpeakMessage = {
  type: "control";
  name: "speak_enabled";
  value: boolean;
};

export type BridgeTtsVoice = { id: string; label: string };

export type BridgeControlTtsVoicesMessage = {
  type: "control";
  name: "tts_voices";
  voices: BridgeTtsVoice[];
  current: string;
  enabled: boolean;
};

export type BridgeControlTtsSpeakerMessage = {
  type: "control";
  name: "tts_speaker";
  value: string;
};

export type BridgeControlAvatarEmotionMessage = {
  type: "control";
  name: "avatar_emotion";
  value: string;
  /** How long to hold the expression preset (ms); should cover most of TTS. */
  duration_ms?: number;
};

export type BridgeControlAvatarSpeakingMessage = {
  type: "control";
  name: "avatar_speaking";
  value: boolean;
};

export type BridgeControlAvatarVisemeMessage = {
  type: "control";
  name: "avatar_viseme";
  value: string;
  intensity?: number;
  hold_ms?: number;
};

export type BridgeControlMicReadyMessage = {
  type: "control";
  name: "mic_ready";
  value: true;
  hint?: string;
};

export type BridgeControlTtsAudioMessage = {
  type: "control";
  name: "tts_audio";
  mime: string;
  data: string;
  duration_ms?: number;
  visemes?: Array<{
    at_ms?: number;
    vowel?: string;
    intensity?: number;
    hold_ms?: number;
  }>;
  /** @deprecated use avatar */
  drive_avatar?: boolean;
  /** Speaking avatar for routing / lip-sync — default Luna when omitted. */
  avatar?: "luna" | "cohost";
};

export type BridgeControlCohostAvatarMessage = {
  type: "control";
  name: "cohost_avatar";
  /** When true, show Luna + co-host together (no swapping). */
  dual_layout?: boolean;
  vrm_url?: string;
  active_speaker?: "luna" | "cohost";
};

export type BridgeControlEnrollStateMessage = {
  type: "control";
  name: "enroll_state";
  enabled: boolean;
  enrolled: boolean;
  min_sim: number;
  last_sim: number | null;
  samples?: number;
};

export type BridgeControlYoutubeLivePromptMessage = {
  type: "control";
  name: "youtube_live_prompt";
  open: boolean;
  title?: string;
  url?: string;
  stream_id?: string;
};

export type BridgeControlMessage =
  | BridgeControlSpeakMessage
  | BridgeControlTtsVoicesMessage
  | BridgeControlTtsSpeakerMessage
  | BridgeControlAvatarEmotionMessage
  | BridgeControlAvatarSpeakingMessage
  | BridgeControlAvatarVisemeMessage
  | BridgeControlMicReadyMessage
  | BridgeControlTtsAudioMessage
  | BridgeControlEnrollStateMessage
  | BridgeControlYoutubeLivePromptMessage
  | BridgeControlCohostAvatarMessage;

export type BridgeMessage =
  | BridgeChatMessage
  | BridgeAssistantMessage
  | BridgeAssistantDeltaMessage
  | BridgeStatusMessage
  | BridgeControlMessage;

function parseTtsVoices(o: Record<string, unknown>): BridgeTtsVoice[] | null {
  if (!Array.isArray(o.voices)) return null;
  const out: BridgeTtsVoice[] = [];
  for (const item of o.voices) {
    if (!item || typeof item !== "object") continue;
    const v = item as Record<string, unknown>;
    if (typeof v.id !== "string" || typeof v.label !== "string") continue;
    out.push({ id: v.id, label: v.label });
  }
  return out;
}

export function parseBridgeMessage(raw: unknown): BridgeMessage | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  const t = o.type;
  if (t === "status" && typeof o.text === "string") {
    return { type: "status", text: o.text };
  }
  if (t === "control" && o.name === "speak_enabled" && typeof o.value === "boolean") {
    return { type: "control", name: "speak_enabled", value: o.value };
  }
  if (t === "control" && o.name === "tts_voices") {
    const voices = parseTtsVoices(o);
    if (!voices || typeof o.current !== "string") return null;
    const enabled = o.enabled === true;
    return {
      type: "control",
      name: "tts_voices",
      voices,
      current: o.current,
      enabled,
    };
  }
  if (t === "control" && o.name === "tts_speaker" && typeof o.value === "string") {
    return { type: "control", name: "tts_speaker", value: o.value };
  }
  if (t === "control" && o.name === "avatar_emotion" && typeof o.value === "string") {
    const duration_ms =
      typeof o.duration_ms === "number" && Number.isFinite(o.duration_ms)
        ? o.duration_ms
        : undefined;
    return {
      type: "control",
      name: "avatar_emotion",
      value: o.value,
      ...(duration_ms !== undefined ? { duration_ms } : {}),
    };
  }
  if (t === "control" && o.name === "avatar_speaking" && typeof o.value === "boolean") {
    return { type: "control", name: "avatar_speaking", value: o.value };
  }
  if (t === "control" && o.name === "avatar_viseme" && typeof o.value === "string") {
    return {
      type: "control",
      name: "avatar_viseme",
      value: o.value,
      intensity: typeof o.intensity === "number" ? o.intensity : undefined,
      hold_ms: typeof o.hold_ms === "number" ? o.hold_ms : undefined,
    };
  }
  if (t === "control" && o.name === "mic_ready" && o.value === true) {
    return {
      type: "control",
      name: "mic_ready",
      value: true,
      hint: typeof o.hint === "string" ? o.hint : undefined,
    };
  }
  if (t === "control" && o.name === "tts_audio" && typeof o.data === "string") {
    const visemes = Array.isArray(o.visemes)
      ? o.visemes
          .filter((v) => v && typeof v === "object")
          .map((v) => {
            const row = v as Record<string, unknown>;
            return {
              at_ms: typeof row.at_ms === "number" ? row.at_ms : undefined,
              vowel: typeof row.vowel === "string" ? row.vowel : undefined,
              intensity: typeof row.intensity === "number" ? row.intensity : undefined,
              hold_ms: typeof row.hold_ms === "number" ? row.hold_ms : undefined,
            };
          })
      : undefined;
    const avatarRaw = typeof o.avatar === "string" ? o.avatar.trim().toLowerCase() : "";
    const avatar: "luna" | "cohost" = avatarRaw === "cohost" ? "cohost" : "luna";
    const drive_avatar = o.drive_avatar !== false;
    return {
      type: "control",
      name: "tts_audio",
      mime: typeof o.mime === "string" ? o.mime : "audio/mpeg",
      data: o.data,
      duration_ms: typeof o.duration_ms === "number" ? o.duration_ms : undefined,
      visemes,
      drive_avatar,
      avatar,
    };
  }
  if (t === "control" && o.name === "cohost_avatar") {
    const sp = typeof o.active_speaker === "string" ? o.active_speaker.trim().toLowerCase() : "";
    return {
      type: "control",
      name: "cohost_avatar",
      dual_layout: o.dual_layout === true || o.visible === true,
      vrm_url: typeof o.vrm_url === "string" ? o.vrm_url : undefined,
      active_speaker: sp === "cohost" ? "cohost" : sp === "luna" ? "luna" : undefined,
    };
  }
  if (t === "control" && o.name === "enroll_state") {
    const enabled = o.enabled === true;
    const enrolled = o.enrolled === true;
    const minSim = typeof o.min_sim === "number" ? o.min_sim : 0;
    const lastSim =
      typeof o.last_sim === "number"
        ? o.last_sim
        : o.last_sim === null
        ? null
        : null;
    const samples = typeof o.samples === "number" ? o.samples : undefined;
    return {
      type: "control",
      name: "enroll_state",
      enabled,
      enrolled,
      min_sim: minSim,
      last_sim: lastSim,
      samples,
    };
  }
  if (t === "control" && o.name === "youtube_live_prompt") {
    const open = o.open !== false;
    return {
      type: "control",
      name: "youtube_live_prompt",
      open,
      title: typeof o.title === "string" ? o.title : undefined,
      url: typeof o.url === "string" ? o.url : undefined,
      stream_id: typeof o.stream_id === "string" ? o.stream_id : undefined,
    };
  }
  if (t === "chat" && typeof o.user === "string" && typeof o.text === "string") {
    return {
      type: "chat",
      user: o.user,
      text: o.text,
      channel: typeof o.channel === "string" ? o.channel : "",
      ts: typeof o.ts === "number" ? o.ts : undefined,
    };
  }
  if (t === "assistant" && typeof o.user === "string" && typeof o.text === "string") {
    return {
      type: "assistant",
      user: o.user,
      text: o.text,
      channel: typeof o.channel === "string" ? o.channel : "",
      ts: typeof o.ts === "number" ? o.ts : undefined,
    };
  }
  if (t === "assistant_delta" && typeof o.user === "string" && typeof o.text === "string") {
    return {
      type: "assistant_delta",
      user: o.user,
      text: o.text,
      channel: typeof o.channel === "string" ? o.channel : "",
    };
  }
  return null;
}
