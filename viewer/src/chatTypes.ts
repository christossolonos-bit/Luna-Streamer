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

export type ViewerAvatarId = "luna" | "cohost" | "himari";

export type BridgeControlAvatarEmotionMessage = {
  type: "control";
  name: "avatar_emotion";
  value: string;
  /** How long to hold the expression preset (ms); should cover most of TTS. */
  duration_ms?: number;
  avatar?: ViewerAvatarId;
};

export type BridgeControlAvatarSpeakingMessage = {
  type: "control";
  name: "avatar_speaking";
  value: boolean;
  avatar?: ViewerAvatarId;
};

export type BridgeControlAvatarThinkingMessage = {
  type: "control";
  name: "avatar_thinking";
  /** ``luna`` | ``cohost`` | ``himari``. */
  avatar: string;
  value: boolean;
};

export type BridgeControlAvatarVisemeMessage = {
  type: "control";
  name: "avatar_viseme";
  value: string;
  intensity?: number;
  hold_ms?: number;
  avatar?: ViewerAvatarId;
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
  avatar?: ViewerAvatarId;
  /** Twitch/YouTube @Viktor reply — show co-host VRM/voice even in solo mode. */
  chat_reply?: boolean;
};

export type BridgeControlStopTtsMessage = {
  type: "control";
  name: "stop_tts";
};

export type BridgeControlCohostAvatarMessage = {
  type: "control";
  name: "cohost_avatar";
  /** When true, show Luna + co-host together (no swapping). */
  dual_layout?: boolean;
  /** Luna + Viktor + Himari on stage for cast banter. */
  trio_layout?: boolean;
  vrm_url?: string;
  himari_vrm_url?: string;
  active_speaker?: ViewerAvatarId;
  /** Twitch/YouTube live chat routed to Viktor — bypass solo-mode viewer blocks. */
  chat_reply?: boolean;
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

export type BridgeControlLiveSocialTitlePromptMessage = {
  type: "control";
  name: "live_social_title_prompt";
  open: boolean;
  platform?: string;
  suggested_title?: string;
  url?: string;
  stream_id?: string;
};

export type BridgeControlPerfConfigMessage = {
  type: "control";
  name: "perf_config";
  screen_capture_interval_ms?: number;
  screen_context_interval_sec?: number;
  screen_capture_max_width?: number;
  screen_capture_jpeg_quality?: number;
  renderer_max_dpr?: number;
};

export type BridgeControlMessage =
  | BridgeControlSpeakMessage
  | BridgeControlTtsVoicesMessage
  | BridgeControlTtsSpeakerMessage
  | BridgeControlAvatarEmotionMessage
  | BridgeControlAvatarSpeakingMessage
  | BridgeControlAvatarThinkingMessage
  | BridgeControlAvatarVisemeMessage
  | BridgeControlMicReadyMessage
  | BridgeControlTtsAudioMessage
  | BridgeControlStopTtsMessage
  | BridgeControlEnrollStateMessage
  | BridgeControlYoutubeLivePromptMessage
  | BridgeControlLiveSocialTitlePromptMessage
  | BridgeControlCohostAvatarMessage
  | BridgeControlPerfConfigMessage;

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
    const avatarRaw = typeof o.avatar === "string" ? o.avatar.trim().toLowerCase() : "";
    const avatar: ViewerAvatarId | undefined =
      avatarRaw === "himari"
        ? "himari"
        : avatarRaw === "cohost"
          ? "cohost"
          : avatarRaw === "luna"
            ? "luna"
            : undefined;
    return {
      type: "control",
      name: "avatar_emotion",
      value: o.value,
      ...(duration_ms !== undefined ? { duration_ms } : {}),
      ...(avatar ? { avatar } : {}),
    };
  }
  if (t === "control" && o.name === "avatar_speaking" && typeof o.value === "boolean") {
    const avatarRaw = typeof o.avatar === "string" ? o.avatar.trim().toLowerCase() : "";
    const avatar: ViewerAvatarId | undefined =
      avatarRaw === "himari"
        ? "himari"
        : avatarRaw === "cohost"
          ? "cohost"
          : avatarRaw === "luna"
            ? "luna"
            : undefined;
    return {
      type: "control",
      name: "avatar_speaking",
      value: o.value,
      ...(avatar ? { avatar } : {}),
    };
  }
  if (
    t === "control" &&
    o.name === "avatar_thinking" &&
    typeof o.value === "boolean" &&
    typeof o.avatar === "string"
  ) {
    return {
      type: "control",
      name: "avatar_thinking",
      avatar: o.avatar,
      value: o.value,
    };
  }
  if (t === "control" && o.name === "avatar_viseme" && typeof o.value === "string") {
    const avatarRaw = typeof o.avatar === "string" ? o.avatar.trim().toLowerCase() : "";
    const avatar: ViewerAvatarId | undefined =
      avatarRaw === "himari"
        ? "himari"
        : avatarRaw === "cohost"
          ? "cohost"
          : avatarRaw === "luna"
            ? "luna"
            : undefined;
    return {
      type: "control",
      name: "avatar_viseme",
      value: o.value,
      intensity: typeof o.intensity === "number" ? o.intensity : undefined,
      hold_ms: typeof o.hold_ms === "number" ? o.hold_ms : undefined,
      ...(avatar ? { avatar } : {}),
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
    const avatar: ViewerAvatarId =
      avatarRaw === "himari"
        ? "himari"
        : avatarRaw === "cohost" || avatarRaw === "viktor"
          ? "cohost"
          : "luna";
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
      chat_reply: o.chat_reply === true,
    };
  }
  if (t === "control" && o.name === "stop_tts") {
    return { type: "control", name: "stop_tts" };
  }
  if (t === "control" && o.name === "cohost_avatar") {
    const sp = typeof o.active_speaker === "string" ? o.active_speaker.trim().toLowerCase() : "";
    return {
      type: "control",
      name: "cohost_avatar",
      dual_layout: o.dual_layout === true || o.visible === true,
      trio_layout: o.trio_layout === true,
      vrm_url: typeof o.vrm_url === "string" ? o.vrm_url : undefined,
      himari_vrm_url:
        typeof o.himari_vrm_url === "string" ? o.himari_vrm_url : undefined,
      active_speaker:
        sp === "himari"
          ? "himari"
          : sp === "cohost"
            ? "cohost"
            : sp === "luna"
              ? "luna"
              : undefined,
      chat_reply: o.chat_reply === true,
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
  if (t === "control" && o.name === "live_social_title_prompt") {
    const open = o.open !== false;
    return {
      type: "control",
      name: "live_social_title_prompt",
      open,
      platform: typeof o.platform === "string" ? o.platform : undefined,
      suggested_title:
        typeof o.suggested_title === "string" ? o.suggested_title : undefined,
      url: typeof o.url === "string" ? o.url : undefined,
      stream_id: typeof o.stream_id === "string" ? o.stream_id : undefined,
    };
  }
  if (t === "control" && o.name === "perf_config") {
    const capMs =
      typeof o.screen_capture_interval_ms === "number" &&
      Number.isFinite(o.screen_capture_interval_ms)
        ? o.screen_capture_interval_ms
        : undefined;
    const ctxSec =
      typeof o.screen_context_interval_sec === "number" &&
      Number.isFinite(o.screen_context_interval_sec)
        ? o.screen_context_interval_sec
        : undefined;
    const dpr =
      typeof o.renderer_max_dpr === "number" && Number.isFinite(o.renderer_max_dpr)
        ? o.renderer_max_dpr
        : undefined;
    const maxW =
      typeof o.screen_capture_max_width === "number" &&
      Number.isFinite(o.screen_capture_max_width)
        ? o.screen_capture_max_width
        : undefined;
    const jpegQ =
      typeof o.screen_capture_jpeg_quality === "number" &&
      Number.isFinite(o.screen_capture_jpeg_quality)
        ? o.screen_capture_jpeg_quality
        : undefined;
    return {
      type: "control",
      name: "perf_config",
      ...(capMs !== undefined ? { screen_capture_interval_ms: capMs } : {}),
      ...(ctxSec !== undefined ? { screen_context_interval_sec: ctxSec } : {}),
      ...(maxW !== undefined ? { screen_capture_max_width: maxW } : {}),
      ...(jpegQ !== undefined ? { screen_capture_jpeg_quality: jpegQ } : {}),
      ...(dpr !== undefined ? { renderer_max_dpr: dpr } : {}),
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
