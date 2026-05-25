import { useCallback, useEffect, useRef, useState, type MutableRefObject } from "react";
import {
  type BridgeMessage,
  type BridgeTtsVoice,
  type ViewerAvatarId,
  parseBridgeMessage,
} from "./chatTypes";
import { getCohostSoloMode, readCohostSoloModeStored } from "./cohostScenePrefs";
import { playViewerTts, stopViewerTts } from "./viewerTtsPlayer";

const DEFAULT_WS = "ws://127.0.0.1:8765/ws";
const MAX_LINES = 250;
const RECONNECT_MS = 450;
const CHAT_STORAGE_KEY = "luna.chat.lines.v1";
const TTS_SPEAKER_STORAGE_KEY = "luna.tts.speaker.v1";
/** Matches App.tsx: “full conversation” = open-ended script (`LUNA_COHOST_FULL_BANTER_MAX_LINES` caps parse). */
const COHOST_FULL_SCRIPT_STORAGE_KEY = "luna.cohostFullConversation.v1";
const REPLY_TO_STORAGE_KEY = "luna.replyTo.v1";

function readReplyToStored(): ViewerAvatarId {
  try {
    const raw = window.localStorage.getItem(REPLY_TO_STORAGE_KEY);
    if (raw === "luna" || raw === "himari" || raw === "cohost") return raw;
  } catch {
    /* ignore */
  }
  return "luna";
}

function replyToWireId(target: ViewerAvatarId): string {
  return target === "cohost" ? "viktor" : target;
}

function normalizeViewerAvatar(avatar?: string): ViewerAvatarId | undefined {
  const a = (avatar || "").trim().toLowerCase();
  if (a === "luna") return "luna";
  if (a === "himari") return "himari";
  if (a === "cohost" || a === "viktor") return "cohost";
  return undefined;
}

/** Lip-sync / TTS only — do not reload idle or reframe the stage (avoids head shake). */
function dispatchLipSyncAvatar(avatar?: string) {
  const target = normalizeViewerAvatar(avatar);
  if (!target) return;
  window.dispatchEvent(
    new CustomEvent("luna-lipsync-avatar", { detail: { avatar: target } }),
  );
}

/** Creator tab / explicit scene focus — show that VRM on stage. */
function dispatchFocusAvatar(avatar?: string) {
  const target = normalizeViewerAvatar(avatar);
  if (!target) return;
  window.dispatchEvent(
    new CustomEvent("luna-focus-avatar", { detail: { avatar: target } }),
  );
}

function readCohostFullScriptStored(): boolean {
  try {
    const raw = window.localStorage.getItem(COHOST_FULL_SCRIPT_STORAGE_KEY);
    if (raw === "0") return false;
    return true;
  } catch {
    return true;
  }
}

export type ChatLine =
  | { id: string; kind: "status"; text: string; ts: number }
  | { id: string; kind: "chat"; user: string; text: string; channel: string; ts: number }
  | {
      id: string;
      kind: "assistant";
      user: string;
      text: string;
      channel: string;
      ts: number;
      streaming?: boolean;
    };

export function wsUrl(): string {
  if (typeof window !== "undefined") {
    try {
      const q = new URLSearchParams(window.location.search).get("chat_ws");
      if (q) {
        const trimmed = q.trim();
        if (trimmed.startsWith("ws://") || trimmed.startsWith("wss://")) {
          return trimmed;
        }
      }
    } catch {
      /* ignore */
    }
  }
  const u = import.meta.env.VITE_CHAT_WS_URL;
  if (typeof u === "string" && u.trim()) return u.trim();
  return DEFAULT_WS;
}

let idCounter = 0;
function nextId() {
  idCounter += 1;
  return `${Date.now()}-${idCounter}`;
}

function append(prev: ChatLine[], row: ChatLine): ChatLine[] {
  const next = [...prev, row];
  if (next.length > MAX_LINES) return next.slice(-MAX_LINES);
  return next;
}

function isChatLine(value: unknown): value is ChatLine {
  if (!value || typeof value !== "object") return false;
  const row = value as Record<string, unknown>;
  if (typeof row.id !== "string" || typeof row.ts !== "number") return false;
  if (row.kind === "status") return typeof row.text === "string";
  if (row.kind === "chat" || row.kind === "assistant") {
    return (
      typeof row.user === "string" &&
      typeof row.text === "string" &&
      typeof row.channel === "string" &&
      (row.streaming === undefined || typeof row.streaming === "boolean")
    );
  }
  return false;
}

function loadPersistedLines(): ChatLine[] {
  try {
    const raw = window.localStorage.getItem(CHAT_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    const rows = parsed.filter(isChatLine).map((r) =>
      r.kind === "assistant" && r.streaming
        ? { ...r, streaming: false as boolean | undefined }
        : r,
    );
    return rows.slice(-MAX_LINES);
  } catch {
    return [];
  }
}

function waitForOpenWebSocket(
  wsRef: MutableRefObject<WebSocket | null>,
  maxMs: number,
): Promise<WebSocket | null> {
  return new Promise((resolve) => {
    const start = Date.now();
    const poll = () => {
      const w = wsRef.current;
      if (w?.readyState === WebSocket.OPEN) {
        resolve(w);
        return;
      }
      if (Date.now() - start >= maxMs) {
        resolve(w ?? null);
        return;
      }
      window.setTimeout(poll, 40);
    };
    poll();
  });
}

export type EnrollState = {
  enabled: boolean;
  enrolled: boolean;
  minSim: number;
  lastSim: number | null;
  samples: number;
};

export type YoutubeLivePromptState = {
  open: boolean;
  title: string;
  hintUrl: string;
  streamId: string;
};

export type LiveSocialTitlePromptState = {
  open: boolean;
  platform: string;
  suggestedTitle: string;
  url: string;
  streamId: string;
};

export function useChatBridge(enabled: boolean) {
  const [lines, setLines] = useState<ChatLine[]>(() => loadPersistedLines());
  const [conn, setConn] = useState<"connecting" | "open" | "closed">("closed");
  const [speakEnabled, setSpeakEnabled] = useState(true);
  const replyToRef = useRef<ViewerAvatarId>(readReplyToStored());
  const [replyTo, setReplyToState] = useState<ViewerAvatarId>(() => replyToRef.current);
  const [ttsVoices, setTtsVoices] = useState<BridgeTtsVoice[]>([]);
  const [ttsSpeakerId, setTtsSpeakerId] = useState("");
  const [ttsEnabled, setTtsEnabled] = useState(false);
  const [enrollState, setEnrollState] = useState<EnrollState>({
    enabled: false,
    enrolled: false,
    minSim: 0,
    lastSim: null,
    samples: 0,
  });
  const [youtubeLivePrompt, setYoutubeLivePrompt] = useState<YoutubeLivePromptState>({
    open: false,
    title: "",
    hintUrl: "",
    streamId: "",
  });
  const [liveSocialTitlePrompt, setLiveSocialTitlePrompt] =
    useState<LiveSocialTitlePromptState>({
      open: false,
      platform: "twitch",
      suggestedTitle: "",
      url: "",
      streamId: "",
    });
  /** True while Luna is synthesising / playing TTS locally (viewer path). */
  const [avatarSpeaking, setAvatarSpeaking] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<number>(0);
  const bridgeUrl = wsUrl();

  const appendParsed = useCallback((msg: BridgeMessage) => {
    const ts = Date.now();
    if (msg.type === "status") {
      setLines((p) => append(p, { id: nextId(), kind: "status", text: msg.text, ts }));
      return;
    }
    if (msg.type === "chat") {
      setLines((p) =>
        append(p, {
          id: nextId(),
          kind: "chat",
          user: msg.user,
          text: msg.text,
          channel: msg.channel,
          ts: msg.ts ?? ts,
        }),
      );
      return;
    }
    if (msg.type === "assistant_delta") {
      setLines((p) => {
        const last = p[p.length - 1];
        if (
          last?.kind === "assistant" &&
          last.streaming &&
          last.user === msg.user &&
          last.channel === msg.channel
        ) {
          const next = [...p.slice(0, -1), { ...last, text: last.text + msg.text }];
          return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next;
        }
        return append(p, {
          id: nextId(),
          kind: "assistant",
          user: msg.user,
          text: msg.text,
          channel: msg.channel,
          ts,
          streaming: true,
        });
      });
      return;
    }
    if (msg.type === "control") {
      if (msg.name === "speak_enabled") {
        setSpeakEnabled(msg.value);
        return;
      }
      if (msg.name === "tts_voices") {
        setTtsVoices(msg.voices);
        setTtsEnabled(msg.enabled);
        setTtsSpeakerId(msg.current);
        const ws = wsRef.current;
        if (ws && ws.readyState === WebSocket.OPEN) {
          try {
            const stored = window.localStorage.getItem(TTS_SPEAKER_STORAGE_KEY);
            if (
              stored &&
              msg.voices.some((v) => v.id === stored) &&
              stored !== msg.current
            ) {
              ws.send(
                JSON.stringify({
                  type: "control",
                  name: "tts_speaker",
                  value: stored,
                }),
              );
            }
          } catch {
            /* ignore */
          }
        }
        return;
      }
      if (msg.name === "tts_speaker") {
        setTtsSpeakerId(msg.value);
        try {
          window.localStorage.setItem(TTS_SPEAKER_STORAGE_KEY, msg.value);
        } catch {
          /* ignore */
        }
        return;
      }
      if (msg.name === "avatar_emotion") {
        dispatchLipSyncAvatar(msg.avatar);
        window.dispatchEvent(
          new CustomEvent("luna-avatar-emotion", {
            detail: {
              emotion: msg.value,
              durationMs: msg.duration_ms,
              avatar: msg.avatar,
            },
          }),
        );
        return;
      }
      if (msg.name === "avatar_speaking") {
        dispatchLipSyncAvatar(msg.avatar);
        setAvatarSpeaking(msg.value);
        window.dispatchEvent(
          new CustomEvent("luna-avatar-speaking", {
            detail: { value: msg.value, avatar: msg.avatar },
          }),
        );
        return;
      }
      if (
        msg.name === "avatar_thinking" &&
        (msg.avatar === "luna" ||
          msg.avatar === "cohost" ||
          msg.avatar === "himari")
      ) {
        window.dispatchEvent(
          new CustomEvent("luna-avatar-thinking", {
            detail: { avatar: msg.avatar, active: msg.value },
          }),
        );
        return;
      }
      if (msg.name === "avatar_viseme") {
        dispatchLipSyncAvatar(msg.avatar);
        window.dispatchEvent(
          new CustomEvent("luna-avatar-viseme", {
            detail: {
              vowel: msg.value,
              intensity: msg.intensity ?? 1,
              holdMs: msg.hold_ms ?? 120,
              avatar: msg.avatar,
            },
          }),
        );
        return;
      }
      if (msg.name === "perf_config") {
        window.dispatchEvent(
          new CustomEvent("luna-perf-config", {
            detail: {
              screenCaptureIntervalMs: msg.screen_capture_interval_ms,
              screenContextIntervalSec: msg.screen_context_interval_sec,
              screenCaptureMaxWidth: msg.screen_capture_max_width,
              screenCaptureJpegQuality: msg.screen_capture_jpeg_quality,
              rendererMaxDpr: msg.renderer_max_dpr,
            },
          }),
        );
        return;
      }
      if (msg.name === "cohost_avatar") {
        const chatReply = msg.chat_reply === true;
        const solo = getCohostSoloMode();
        const activeSpeaker =
          !chatReply && solo && msg.active_speaker === "cohost"
            ? "luna"
            : msg.active_speaker;
        if (
          activeSpeaker === "luna" ||
          activeSpeaker === "cohost" ||
          activeSpeaker === "himari"
        ) {
          dispatchFocusAvatar(activeSpeaker);
        }
        window.dispatchEvent(
          new CustomEvent("luna-cohost-avatar", {
            detail: {
              dualLayout: chatReply ? msg.dual_layout === true : !solo && msg.dual_layout === true,
              trioLayout: msg.trio_layout === true,
              vrmUrl: msg.vrm_url?.trim() || "",
              himariVrmUrl: msg.himari_vrm_url?.trim() || "",
              activeSpeaker,
              chatReply,
            },
          }),
        );
        return;
      }
      if (msg.name === "stop_tts") {
        stopViewerTts();
        window.dispatchEvent(
          new CustomEvent("luna-avatar-speaking", { detail: false }),
        );
        const ws = wsRef.current;
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "viewer_tts_ended" }));
        }
        return;
      }
      if (msg.name === "tts_audio") {
        const chatReply = msg.chat_reply === true;
        const solo = getCohostSoloMode();
        const speaker: ViewerAvatarId = normalizeViewerAvatar(msg.avatar) ?? "luna";
        if (solo && speaker === "cohost" && !chatReply) {
          const ws = wsRef.current;
          if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "viewer_tts_ended" }));
          }
          return;
        }
        const driveAvatar = msg.drive_avatar !== false;
        dispatchLipSyncAvatar(speaker);
        if (speaker === "cohost" || speaker === "himari") {
          window.dispatchEvent(
            new CustomEvent("luna-cohost-avatar", {
              detail: {
                activeSpeaker: speaker,
                vrmUrl: "",
                chatReply,
              },
            }),
          );
        }
        if (driveAvatar) {
          setAvatarSpeaking(true);
          window.dispatchEvent(
            new CustomEvent("luna-avatar-speaking", {
              detail: { value: true, avatar: speaker },
            }),
          );
        }
        playViewerTts(
          {
            mime: msg.mime,
            data: msg.data,
            duration_ms: msg.duration_ms,
            visemes: msg.visemes,
            driveAvatar,
            avatar: speaker,
          },
          () => {
            const ws = wsRef.current;
            if (ws && ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: "viewer_tts_ended" }));
            }
            if (driveAvatar) {
              setAvatarSpeaking(false);
              window.dispatchEvent(
                new CustomEvent("luna-avatar-speaking", {
                  detail: { value: false, avatar: speaker },
                }),
              );
            }
            if (chatReply && (speaker === "cohost" || speaker === "himari")) {
              window.dispatchEvent(
                new CustomEvent("luna-cohost-chat-reply-end", {
                  detail: { avatar: speaker },
                }),
              );
            }
          },
        );
        return;
      }
      if (msg.name === "mic_ready") {
        const hint =
          typeof msg.hint === "string" && msg.hint.trim().length > 0
            ? msg.hint.trim()
            : "You can speak into the mic now.";
        setLines((p) =>
          append(p, {
            id: nextId(),
            kind: "status",
            text: `Mic ready — ${hint}`,
            ts: Date.now(),
          }),
        );
        return;
      }
      if (msg.name === "enroll_state") {
        setEnrollState({
          enabled: msg.enabled,
          enrolled: msg.enrolled,
          minSim: msg.min_sim,
          lastSim: msg.last_sim,
          samples: typeof msg.samples === "number" ? msg.samples : 0,
        });
        return;
      }
      if (msg.name === "youtube_live_prompt") {
        if (!msg.open) {
          setYoutubeLivePrompt((p) => ({ ...p, open: false }));
          return;
        }
        setYoutubeLivePrompt({
          open: true,
          title: msg.title?.trim() || "YouTube Live",
          hintUrl: msg.url?.trim() || "",
          streamId: msg.stream_id?.trim() || "",
        });
        return;
      }
      if (msg.name === "live_social_title_prompt") {
        if (!msg.open) {
          setLiveSocialTitlePrompt((p) => ({ ...p, open: false }));
          return;
        }
        setLiveSocialTitlePrompt({
          open: true,
          platform: msg.platform?.trim() || "twitch",
          suggestedTitle: msg.suggested_title?.trim() || "",
          url: msg.url?.trim() || "",
          streamId: msg.stream_id?.trim() || "",
        });
        return;
      }
      return;
    }
    setLines((p) => {
      const last = p[p.length - 1];
      if (
        last?.kind === "assistant" &&
        last.streaming &&
        last.user === msg.user &&
        last.channel === msg.channel
      ) {
        const next = [
          ...p.slice(0, -1),
          { ...last, text: msg.text, streaming: false as boolean | undefined, ts: msg.ts ?? ts },
        ];
        return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next;
      }
      return append(p, {
        id: nextId(),
        kind: "assistant",
        user: msg.user,
        text: msg.text,
        channel: msg.channel,
        ts: msg.ts ?? ts,
      });
    });
    window.dispatchEvent(
      new CustomEvent("luna-assistant-reply", {
        detail: msg.text,
      }),
    );
  }, []);

  useEffect(() => {
    if (!enabled) {
      setConn("closed");
      return;
    }

    let closed = false;

    const connect = () => {
      if (closed) return;
      setConn("connecting");
      const ws = new WebSocket(bridgeUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (closed) return;
        setConn("open");
        try {
          ws.send(
            JSON.stringify({
              type: "viewer_cohost_idle_full_script",
              full: readCohostFullScriptStored(),
            }),
          );
          ws.send(
            JSON.stringify({
              type: "viewer_cohost_scene",
              in_scene: !readCohostSoloModeStored(),
            }),
          );
        } catch {
          /* ignore */
        }
      };

      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(String(ev.data)) as unknown;
          const parsed = parseBridgeMessage(data);
          if (parsed) appendParsed(parsed);
        } catch {
          /* ignore malformed */
        }
      };

      ws.onerror = () => {
        if (!closed) setConn("closed");
      };

      ws.onclose = () => {
        if (wsRef.current === ws) {
          wsRef.current = null;
        }
        if (closed) return;
        setConn("closed");
        timerRef.current = window.setTimeout(connect, RECONNECT_MS);
      };
    };

    connect();

    return () => {
      closed = true;
      window.clearTimeout(timerRef.current);
      timerRef.current = 0;
      const w = wsRef.current;
      wsRef.current = null;
      w?.close();
    };
  }, [enabled, appendParsed, bridgeUrl]);

  useEffect(() => {
    const onSpeakingEvt = (ev: Event) => {
      const d = (ev as CustomEvent<boolean>).detail;
      if (typeof d === "boolean") setAvatarSpeaking(d);
    };
    window.addEventListener("luna-avatar-speaking", onSpeakingEvt);
    return () => window.removeEventListener("luna-avatar-speaking", onSpeakingEvt);
  }, []);

  // Debounce localStorage writes — streaming token deltas can fire 100+
  // setState calls per reply. Writing every one of those serialises the full
  // chat history (~250 entries) and pegs the main thread.
  const persistTimerRef = useRef<number>(0);
  useEffect(() => {
    if (persistTimerRef.current) {
      window.clearTimeout(persistTimerRef.current);
    }
    persistTimerRef.current = window.setTimeout(() => {
      try {
        window.localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(lines));
      } catch {
        // ignore storage quota/privacy failures
      }
    }, 300);
    return () => {
      if (persistTimerRef.current) {
        window.clearTimeout(persistTimerRef.current);
        persistTimerRef.current = 0;
      }
    };
  }, [lines]);

  const clear = useCallback(() => {
    setLines([]);
    try {
      window.localStorage.removeItem(CHAT_STORAGE_KEY);
    } catch {
      // ignore storage failures
    }
  }, []);

  const addStatusLine = useCallback((text: string) => {
    const ts = Date.now();
    setLines((p) => append(p, { id: nextId(), kind: "status", text, ts }));
  }, []);

  const setReplyTo = useCallback((target: ViewerAvatarId) => {
    replyToRef.current = target;
    setReplyToState(target);
    try {
      window.localStorage.setItem(REPLY_TO_STORAGE_KEY, target);
    } catch {
      /* ignore */
    }
    dispatchFocusAvatar(target);
  }, []);

  const setSpeak = useCallback((enabledValue: boolean) => {
    setSpeakEnabled(enabledValue);
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(
      JSON.stringify({
        type: "control",
        name: "speak_enabled",
        value: enabledValue,
      }),
    );
  }, []);

  const sendPrompt = useCallback(async (text: string) => {
    const message = text.trim();
    if (!message) return false;
    let ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      ws = (await waitForOpenWebSocket(wsRef, 5000)) ?? null;
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(
      JSON.stringify({
        type: "viewer_prompt",
        text: message,
        reply_to: replyToWireId(replyToRef.current),
      }),
    );
    return true;
  }, []);

  const sendVoiceBlob = useCallback(async (blob: Blob, mime: string) => {
    if (!blob.size) {
      return { ok: false as const, reason: "empty recording (0 bytes)" };
    }
    let ws: WebSocket | null = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      ws = await waitForOpenWebSocket(wsRef, 6000);
    }
    if (!ws) {
      return {
        ok: false as const,
        reason:
          "chat bridge offline — check bot is running and VITE_CHAT_WS_URL matches LUNA_CHAT_WS_PORT (e.g. ws://127.0.0.1:8765/ws)",
      };
    }
    if (ws.readyState !== WebSocket.OPEN) {
      const st = ws.readyState;
      const label = st === 0 ? "CONNECTING" : st === 2 ? "CLOSING" : st === 3 ? "CLOSED" : "?";
      return { ok: false as const, reason: `socket not ready (${label})` };
    }
    try {
      const buf = await blob.arrayBuffer();
      let binary = "";
      const bytes = new Uint8Array(buf);
      const chunk = 0x8000;
      for (let i = 0; i < bytes.length; i += chunk) {
        binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
      }
      const b64 = btoa(binary);
      const payload = JSON.stringify({
        type: "viewer_voice",
        mime: mime || blob.type || "audio/webm",
        data: b64,
        reply_to: replyToWireId(replyToRef.current),
      });
      ws.send(payload);
      return { ok: true as const };
    } catch (e) {
      console.error("sendVoiceBlob:", e);
      const msg = e instanceof Error ? e.message : String(e);
      return { ok: false as const, reason: msg || "send failed" };
    }
  }, []);

  const sendEnrollBlob = useCallback(async (blob: Blob, mime: string) => {
    if (!blob.size) return { ok: false as const, reason: "empty enroll recording" };
    let ws: WebSocket | null = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      ws = await waitForOpenWebSocket(wsRef, 6000);
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      return { ok: false as const, reason: "chat bridge offline" };
    }
    try {
      const buf = await blob.arrayBuffer();
      let binary = "";
      const bytes = new Uint8Array(buf);
      const chunk = 0x8000;
      for (let i = 0; i < bytes.length; i += chunk) {
        binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
      }
      const b64 = btoa(binary);
      ws.send(
        JSON.stringify({
          type: "viewer_enroll_voice",
          mime: mime || blob.type || "audio/webm",
          data: b64,
        }),
      );
      return { ok: true as const };
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      return { ok: false as const, reason: msg || "enroll send failed" };
    }
  }, []);

  const clearEnrollment = useCallback(() => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify({ type: "viewer_enroll_clear" }));
    return true;
  }, []);

  const requestEnrollState = useCallback(() => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: "control", name: "enroll_state_request" }));
  }, []);

  const sendPlayRequest = useCallback(async (query: string) => {
    const q = query.trim();
    if (!q) return false;
    let ws: WebSocket | null = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      ws = await waitForOpenWebSocket(wsRef, 4000);
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify({ type: "viewer_play", query: q }));
    return true;
  }, []);

  const sendYouTubeSummary = useCallback(async (url: string) => {
    const u = url.trim();
    if (!u) return false;
    let ws: WebSocket | null = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      ws = await waitForOpenWebSocket(wsRef, 4000);
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify({ type: "viewer_yt_summary", url: u }));
    return true;
  }, []);

  const sendYoutubeObserveCheck = useCallback(async () => {
    let ws: WebSocket | null = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      ws = await waitForOpenWebSocket(wsRef, 4000);
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    addStatusLine("YouTube: checking observe channels...");
    ws.send(JSON.stringify({ type: "viewer_youtube_observe_check" }));
    return true;
  }, [addStatusLine]);

  const sendYoutubeLiveCheck = useCallback(async () => {
    let ws: WebSocket | null = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      ws = await waitForOpenWebSocket(wsRef, 4000);
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    addStatusLine("YouTube + TikTok live: checking…");
    ws.send(JSON.stringify({ type: "viewer_youtube_live_check" }));
    return true;
  }, [addStatusLine]);

  const sendSocialInteractiveLogin = useCallback(async (site: string) => {
    const s = site.trim().toLowerCase();
    if (!s) return false;
    let ws: WebSocket | null = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      ws = await waitForOpenWebSocket(wsRef, 4000);
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    addStatusLine(`Social login (${s}): requesting browser from server...`);
    ws.send(JSON.stringify({ type: "viewer_social_interactive_login", site: s }));
    return true;
  }, [addStatusLine]);

  const sendSocialShareVideo = useCallback(async (url: string) => {
    const u = url.trim();
    if (!u) return false;
    let ws: WebSocket | null = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      ws = await waitForOpenWebSocket(wsRef, 4000);
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    addStatusLine("Social share: sending to server...");
    ws.send(JSON.stringify({ type: "viewer_social_share_video", url: u }));
    return true;
  }, [addStatusLine]);

  const sendYouTubeLiveUrl = useCallback(async (url: string) => {
    const u = url.trim();
    if (!u) return false;
    let ws: WebSocket | null = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      ws = await waitForOpenWebSocket(wsRef, 5000);
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify({ type: "viewer_youtube_live_url", url: u }));
    return true;
  }, []);

  const dismissYouTubeLivePrompt = useCallback((streamId: string) => {
    setYoutubeLivePrompt((p) => ({ ...p, open: false }));
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(
      JSON.stringify({
        type: "viewer_youtube_live_dismiss",
        stream_id: streamId || undefined,
      }),
    );
  }, []);

  const sendLiveSocialTitle = useCallback(
    async (payload: {
      title: string;
      platform: string;
      streamId: string;
      url: string;
    }) => {
      const t = payload.title.trim();
      if (!t) return false;
      let ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        ws = await waitForOpenWebSocket(wsRef, 5000);
      }
      if (!ws || ws.readyState !== WebSocket.OPEN) return false;
      ws.send(
        JSON.stringify({
          type: "viewer_live_social_title",
          title: t,
          platform: payload.platform,
          stream_id: payload.streamId,
          url: payload.url,
        }),
      );
      setLiveSocialTitlePrompt((p) => ({ ...p, open: false }));
      return true;
    },
    [],
  );

  const dismissLiveSocialTitlePrompt = useCallback((platform: string, streamId: string) => {
    setLiveSocialTitlePrompt((p) => ({ ...p, open: false }));
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(
      JSON.stringify({
        type: "viewer_live_social_title_dismiss",
        platform,
        stream_id: streamId || undefined,
      }),
    );
  }, []);

  const sendCohostBanterNow = useCallback(async (fullConversation: boolean) => {
    let ws: WebSocket | null = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      ws = await waitForOpenWebSocket(wsRef, 4000);
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify({ type: "viewer_cohost_banter", full: fullConversation }));
    return true;
  }, []);

  const sendViewerCohostScene = useCallback(
    async (cast: { viktor: boolean; himari: boolean }) => {
      let ws: WebSocket | null = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        ws = await waitForOpenWebSocket(wsRef, 4000);
      }
      if (!ws || ws.readyState !== WebSocket.OPEN) return false;
      ws.send(
        JSON.stringify({
          type: "viewer_cohost_scene",
          in_scene: cast.viktor || cast.himari,
          cast: { viktor: cast.viktor, himari: cast.himari },
        }),
      );
      return true;
    },
    [],
  );

  const sendCohostIdleFullScriptPreference = useCallback(async (full: boolean) => {
    let ws: WebSocket | null = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      ws = await waitForOpenWebSocket(wsRef, 4000);
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify({ type: "viewer_cohost_idle_full_script", full }));
    return true;
  }, []);

  const pickTtsVoice = useCallback((id: string) => {
    setTtsSpeakerId(id);
    try {
      window.localStorage.setItem(TTS_SPEAKER_STORAGE_KEY, id);
    } catch {
      /* ignore */
    }
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(
        JSON.stringify({
          type: "control",
          name: "tts_speaker",
          value: id,
        }),
      );
    }
  }, []);

  return {
    lines,
    conn,
    avatarSpeaking,
    wsUrl: wsUrl(),
    clear,
    speakEnabled,
    setSpeak,
    replyTo,
    setReplyTo,
    sendPrompt,
    sendVoiceBlob,
    addStatusLine,
    ttsVoices,
    ttsSpeakerId,
    ttsEnabled,
    pickTtsVoice,
    enrollState,
    sendEnrollBlob,
    clearEnrollment,
    requestEnrollState,
    sendPlayRequest,
    sendYouTubeSummary,
    sendYoutubeObserveCheck,
    sendYoutubeLiveCheck,
    sendSocialShareVideo,
    sendSocialInteractiveLogin,
    sendYouTubeLiveUrl,
    dismissYouTubeLivePrompt,
    youtubeLivePrompt,
    liveSocialTitlePrompt,
    sendLiveSocialTitle,
    dismissLiveSocialTitlePrompt,
    sendCohostBanterNow,
    sendCohostIdleFullScriptPreference,
    sendViewerCohostScene,
  };
}
