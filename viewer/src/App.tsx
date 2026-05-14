import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
} from "react";
import "./App.css";
import { ChatBridgeProvider, useBridge } from "./chatBridgeContext";
import { ChatOverlay } from "./ChatOverlay";
import { CaptionsOverlay } from "./CaptionsOverlay";
import { FloatingDock, type DockOverlay } from "./FloatingDock";
import { SettingsOverlay } from "./SettingsOverlay";
import { YouTubeLivePromptOverlay } from "./YouTubeLivePromptOverlay";
import { CloseIcon } from "./icons";
import { useMicSession } from "./useMicSession";
import { VrmRuntime, type ChromaKeyMode } from "./vrmRuntime";
import { wsUrl } from "./useChatBridge";

const CHROMA_STORAGE_KEY = "luna.chromaKey.v1";
const CAPTIONS_STORAGE_KEY = "luna.captions.v1";

function readStoredChromaKey(): ChromaKeyMode {
  try {
    const v = window.localStorage.getItem(CHROMA_STORAGE_KEY);
    if (v === "green" || v === "blue" || v === "off") return v;
  } catch {
    /* ignore */
  }
  return "off";
}

function readStoredCaptionsEnabled(): boolean {
  try {
    const v = window.localStorage.getItem(CAPTIONS_STORAGE_KEY);
    if (v === "1") return true;
    if (v === "0") return false;
  } catch {
    /* ignore */
  }
  return true;
}

export default function App() {
  return (
    <ChatBridgeProvider>
      <AppInner />
    </ChatBridgeProvider>
  );
}

function AppInner() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const runtimeRef = useRef<VrmRuntime | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const screenVideoRef = useRef<HTMLVideoElement>(null);

  const {
    conn,
    ttsEnabled,
    avatarSpeaking,
    sendYoutubeObserveCheck,
    sendYoutubeLiveCheck,
    sendSocialShareVideo,
    youtubeLivePrompt,
  } = useBridge();
  const mic = useMicSession();

  const [activeOverlay, setActiveOverlay] = useState<DockOverlay>(null);
  const [chatOpen, setChatOpen] = useState(true);
  const [captionsEnabled, setCaptionsEnabled] = useState(() =>
    readStoredCaptionsEnabled(),
  );

  const [fps, setFps] = useState(0);
  const [sceneLine, setSceneLine] = useState("Initializing scene…");
  const [loadPct, setLoadPct] = useState(0);
  const [drag, setDrag] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);
  const [motionUrl, setMotionUrl] = useState(
    "/@fs/D:/Luna streamer/expressions/motion_1777320820578.vrma",
  );
  const [screenStream, setScreenStream] = useState<MediaStream | null>(null);
  const [screenBusy, setScreenBusy] = useState(false);
  const [chromaKey, setChromaKeyState] = useState<ChromaKeyMode>(() =>
    readStoredChromaKey(),
  );

  const setChromaKey = useCallback((mode: ChromaKeyMode) => {
    setChromaKeyState(mode);
    try {
      window.localStorage.setItem(CHROMA_STORAGE_KEY, mode);
    } catch {
      /* ignore */
    }
    runtimeRef.current?.setChromaKeyMode(mode);
  }, []);

  const onSocialShareVideoClick = useCallback(() => {
    const raw = window.prompt(
      "Paste a YouTube video URL to share on X and Facebook (works for older uploads too). Server needs LUNA_SOCIAL_PLAYWRIGHT and storage JSON paths.",
    );
    const u = raw?.trim();
    if (u) void sendSocialShareVideo(u);
  }, [sendSocialShareVideo]);

  useEffect(() => {
    try {
      window.localStorage.setItem(CAPTIONS_STORAGE_KEY, captionsEnabled ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [captionsEnabled]);

  useEffect(() => {
    runtimeRef.current?.setChromaKeyMode(chromaKey);
  }, [chromaKey]);

  // Screen-share preview hookup.
  useEffect(() => {
    const v = screenVideoRef.current;
    if (!v) return;
    v.srcObject = screenStream;
    if (screenStream) {
      void v.play().catch(() => {
        /* ignore autoplay blocks */
      });
    }
  }, [screenStream]);

  useEffect(() => {
    return () => {
      if (!screenStream) return;
      for (const t of screenStream.getTracks()) t.stop();
    };
  }, [screenStream]);

  // Periodic JPEG frame upload while screen-sharing.
  useEffect(() => {
    if (!screenStream) return;

    const intervalMsRaw = import.meta.env.VITE_SCREEN_CONTEXT_INTERVAL_MS;
    const intervalMs =
      typeof intervalMsRaw === "string" && intervalMsRaw.trim()
        ? Math.max(3000, Number(intervalMsRaw) || 15000)
        : 15000;

    let ws: WebSocket | null = null;
    let closed = false;
    let reconnectTimer: number | undefined;
    let frameTimer: number | undefined;

    const connect = () => {
      if (closed) return;
      try {
        ws = new WebSocket(wsUrl());
      } catch {
        scheduleReconnect();
        return;
      }
      ws.onclose = () => {
        ws = null;
        if (!closed) scheduleReconnect();
      };
      ws.onerror = () => {
        try {
          ws?.close();
        } catch {
          /* ignore */
        }
      };
    };

    const scheduleReconnect = () => {
      if (closed) return;
      if (reconnectTimer !== undefined) return;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = undefined;
        connect();
      }, 2000);
    };

    const sendFrame = () => {
      const v = screenVideoRef.current;
      const socket = ws;
      if (!v || !socket || socket.readyState !== WebSocket.OPEN) return;
      const w = v.videoWidth;
      const h = v.videoHeight;
      if (w < 2 || h < 2) return;

      const maxW = 960;
      const scale = Math.min(1, maxW / w);
      const tw = Math.max(2, Math.round(w * scale));
      const th = Math.max(2, Math.round(h * scale));

      const c = document.createElement("canvas");
      c.width = tw;
      c.height = th;
      const ctx = c.getContext("2d");
      if (!ctx) return;
      ctx.drawImage(v, 0, 0, tw, th);
      const jpeg = c.toDataURL("image/jpeg", 0.68);
      const comma = jpeg.indexOf(",");
      const b64 = comma >= 0 ? jpeg.slice(comma + 1) : "";
      if (!b64) return;

      try {
        socket.send(
          JSON.stringify({
            type: "viewer_screen_frame",
            data: b64,
            mime: "image/jpeg",
          }),
        );
      } catch {
        /* ignore */
      }
    };

    connect();
    frameTimer = window.setInterval(sendFrame, intervalMs);
    window.setTimeout(sendFrame, 900);

    return () => {
      closed = true;
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
      if (frameTimer !== undefined) window.clearInterval(frameTimer);
      try {
        ws?.close();
      } catch {
        /* ignore */
      }
    };
  }, [screenStream]);

  // Bridge → avatar event listeners.
  useEffect(() => {
    const onEmotion = (ev: Event) => {
      const ce = ev as CustomEvent<
        string | { emotion?: string; durationMs?: number }
      >;
      const d = ce.detail;
      const id =
        typeof d === "string"
          ? d
          : typeof d === "object" && d && typeof d.emotion === "string"
            ? d.emotion
            : "";
      const ms =
        typeof d === "object" &&
        d &&
        typeof d.durationMs === "number" &&
        Number.isFinite(d.durationMs)
          ? d.durationMs
          : undefined;
      runtimeRef.current?.triggerEmotion(String(id || "relaxed"), ms);
    };
    const onReply = (ev: Event) => {
      const ce = ev as CustomEvent<string>;
      // If TTS is enabled, drive lips from actual playback state instead of
      // text arrival timing (which often starts earlier than audio).
      if (ttsEnabled || avatarSpeaking) return;
      runtimeRef.current?.triggerTalk(String(ce.detail || ""));
    };
    const onSpeaking = (ev: Event) => {
      const ce = ev as CustomEvent<boolean>;
      runtimeRef.current?.setSpeaking(Boolean(ce.detail));
    };
    const onViseme = (ev: Event) => {
      const ce = ev as CustomEvent<{ vowel?: string; intensity?: number; holdMs?: number }>;
      const d = ce.detail || {};
      runtimeRef.current?.setViseme(
        String(d.vowel || ""),
        Number.isFinite(d.intensity) ? Number(d.intensity) : 1,
        Number.isFinite(d.holdMs) ? Number(d.holdMs) : 120,
      );
    };
    window.addEventListener("luna-avatar-emotion", onEmotion);
    window.addEventListener("luna-assistant-reply", onReply);
    window.addEventListener("luna-avatar-speaking", onSpeaking);
    window.addEventListener("luna-avatar-viseme", onViseme);
    return () => {
      window.removeEventListener("luna-avatar-emotion", onEmotion);
      window.removeEventListener("luna-assistant-reply", onReply);
      window.removeEventListener("luna-avatar-speaking", onSpeaking);
      window.removeEventListener("luna-avatar-viseme", onViseme);
    };
  }, [avatarSpeaking, ttsEnabled]);

  // VRM runtime boot.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const runtime = new VrmRuntime(canvas, {
      onFps: setFps,
      onSceneStatus: setSceneLine,
      onLoadProgress: (loaded, total) => {
        const p = total > 0 ? Math.round((100 * loaded) / total) : 0;
        setLoadPct(p);
      },
    });
    runtimeRef.current = runtime;
    runtime.setChromaKeyMode(readStoredChromaKey());

    const params = new URLSearchParams(window.location.search);
    const vrmParam = params.get("vrm");
    const idleUrls = params.getAll("idle").filter((v) => v.trim().length > 0);
    if (vrmParam) {
      setLoadPct(0);
      setLastError(null);
      setSceneLine("> Trying startup avatar…");
      void runtime
        .loadVrmFromUrl(vrmParam, vrmParam.split("/").pop() || "startup.vrm")
        .then(async () => {
          setLoadPct(100);
          if (idleUrls.length > 0) {
            await runtime.setIdleMotionUrls(idleUrls);
          }
        })
        .catch((err: unknown) => {
          const msg = err instanceof Error ? err.message : String(err);
          setLastError(msg);
          setSceneLine(`Startup avatar error: ${msg}`);
        });
    }

    const onResize = () => runtime.resize();
    window.addEventListener("resize", onResize);
    onResize();
    const ro = new ResizeObserver(onResize);
    ro.observe(canvas.parentElement!);

    return () => {
      ro.disconnect();
      window.removeEventListener("resize", onResize);
      runtime.dispose();
      runtimeRef.current = null;
    };
  }, []);

  const loadFile = useCallback(async (file: File) => {
    setLastError(null);
    if (!file.name.toLowerCase().endsWith(".vrm")) {
      setLastError("Expected a .vrm file.");
      return;
    }
    const rt = runtimeRef.current;
    if (!rt) return;
    setLoadPct(0);
    setSceneLine("> Trying local model asset…");
    try {
      await rt.loadVrmFile(file);
      setLoadPct(100);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setLastError(msg);
      setSceneLine(`Load error: ${msg}`);
    }
  }, []);

  const onPick = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) void loadFile(f);
    e.target.value = "";
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    const f = e.dataTransfer.files?.[0];
    if (f) void loadFile(f);
  };

  const stopScreenShare = useCallback(() => {
    setScreenStream((prev) => {
      if (prev) {
        for (const t of prev.getTracks()) t.stop();
      }
      return null;
    });
  }, []);

  const startScreenShare = useCallback(async () => {
    if (screenBusy) return;
    if (!navigator.mediaDevices?.getDisplayMedia) {
      setLastError("Screen capture is not supported in this browser.");
      return;
    }
    setScreenBusy(true);
    setLastError(null);
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: 30 },
        audio: false,
      });
      const track = stream.getVideoTracks()[0];
      if (track) {
        track.addEventListener(
          "ended",
          () => {
            setScreenStream(null);
          },
          { once: true },
        );
      }
      setScreenStream((prev) => {
        if (prev) {
          for (const t of prev.getTracks()) t.stop();
        }
        return stream;
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (!/aborted|denied|permission/i.test(msg)) {
        setLastError(`Screen share error: ${msg}`);
      }
    } finally {
      setScreenBusy(false);
    }
  }, [screenBusy]);

  const toggleOverlay = useCallback((id: Exclude<DockOverlay, null>) => {
    setActiveOverlay((current) => (current === id ? null : id));
  }, []);

  const connLabel =
    conn === "open" ? "● live" : conn === "connecting" ? "◌ connecting…" : "○ offline";

  return (
    <div className={`app ${chromaKey !== "off" ? "app--chroma" : ""}`}>
      <div className="canvas-wrap">
        <canvas ref={canvasRef} />
      </div>
      <div className="scanlines" aria-hidden />
      <div className="vignette" aria-hidden />

      <div className="status-badge" role="status">
        <div className="status-badge-title">
          LUNA <span className="status-badge-dot">●</span>
        </div>
        <div className={`status-badge-sub status-badge-sub--${conn}`}>{connLabel}</div>
        <div className="status-badge-scene" title={sceneLine}>
          {sceneLine}
        </div>
      </div>

      <div className="stats-hud" aria-hidden>
        <div className="stats-hud-row">
          <span className="stats-hud-label">FPS</span>
          <span className={`stats-hud-value ${fps < 30 && fps > 0 ? "warn" : ""}`}>
            {fps.toFixed(0)}
          </span>
        </div>
        <div className="stats-hud-row">
          <span className="stats-hud-label">Model</span>
          <span className="stats-hud-value">{loadPct}%</span>
        </div>
      </div>

      <CaptionsOverlay enabled={captionsEnabled} />

      <YouTubeLivePromptOverlay
        open={youtubeLivePrompt.open}
        title={youtubeLivePrompt.title}
        hintUrl={youtubeLivePrompt.hintUrl}
        streamId={youtubeLivePrompt.streamId}
      />

      {activeOverlay === "upload" && (
        <div className="overlay-card overlay-card--center" role="dialog" aria-label="Upload avatar">
          <div className="overlay-card-header">
            <span className="overlay-card-title">Upload avatar</span>
            <button
              type="button"
              className="chat-card-icon-btn"
              onClick={() => setActiveOverlay(null)}
              aria-label="Close upload"
              title="Close"
            >
              <CloseIcon />
            </button>
          </div>
          <div className="overlay-card-body">
            <p className="settings-hint">
              Local VRM preview — drop a <code className="chat-code">.vrm</code> or
              click to browse.
            </p>
            <div
              className={`drop ${drag ? "drag" : ""}`}
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => {
                e.preventDefault();
                setDrag(true);
              }}
              onDragLeave={() => setDrag(false)}
              onDrop={onDrop}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") fileInputRef.current?.click();
              }}
            >
              <strong>Drop .vrm</strong> or click to browse
            </div>
            <input
              ref={fileInputRef}
              className="hidden-input"
              type="file"
              accept=".vrm,model/vrm,.glb"
              onChange={onPick}
            />
            <div className="progress-wrap" aria-hidden>
              <div className="progress-bar" style={{ width: `${loadPct}%` }} />
            </div>
            {lastError && <p className="settings-hint settings-hint--err">{lastError}</p>}
            <p className="settings-hint">Orbit: drag · zoom: scroll · pan: right-drag</p>
          </div>
        </div>
      )}

      {activeOverlay === "screen" && (
        <div className="overlay-card overlay-card--center" role="dialog" aria-label="Share screen">
          <div className="overlay-card-header">
            <span className="overlay-card-title">Share screen</span>
            <button
              type="button"
              className="chat-card-icon-btn"
              onClick={() => setActiveOverlay(null)}
              aria-label="Close screen"
              title="Close"
            >
              <CloseIcon />
            </button>
          </div>
          <div className="overlay-card-body">
            <p className="settings-hint">
              Share your desktop or window — Luna can react to what's on screen.
            </p>
            <div className="settings-row">
              <button
                type="button"
                className={`settings-btn ${screenStream ? "settings-btn--on" : ""}`}
                onClick={() => void startScreenShare()}
                disabled={screenBusy || !!screenStream}
              >
                {screenBusy ? "Starting…" : screenStream ? "Sharing" : "Start Share"}
              </button>
              <button
                type="button"
                className="settings-btn"
                onClick={stopScreenShare}
                disabled={!screenStream}
              >
                Stop Share
              </button>
            </div>
            <div className="screen-preview-wrap">
              {screenStream ? (
                <video
                  ref={screenVideoRef}
                  className="screen-preview"
                  muted
                  playsInline
                  autoPlay
                />
              ) : (
                <p className="settings-hint">No active screen share.</p>
              )}
            </div>
          </div>
        </div>
      )}

      {activeOverlay === "settings" && (
        <SettingsOverlay
          onClose={() => setActiveOverlay(null)}
          runtimeRef={runtimeRef}
          chromaKey={chromaKey}
          setChromaKey={setChromaKey}
          motionUrl={motionUrl}
          setMotionUrl={setMotionUrl}
          captionsEnabled={captionsEnabled}
          setCaptionsEnabled={setCaptionsEnabled}
        />
      )}

      {chatOpen && <ChatOverlay onClose={() => setChatOpen(false)} />}

      <FloatingDock
        activeOverlay={activeOverlay}
        onToggleOverlay={toggleOverlay}
        micListening={mic.listening}
        micDisabled={mic.disabled}
        micHoldForTts={mic.holdForTts}
        onToggleMic={() => void mic.toggle()}
        chatOpen={chatOpen}
        onToggleChat={() => setChatOpen((v) => !v)}
        ytObserveCheckDisabled={conn !== "open"}
        onYoutubeObserveCheck={() => void sendYoutubeObserveCheck()}
        ytLiveCheckDisabled={conn !== "open"}
        onYoutubeLiveCheck={() => void sendYoutubeLiveCheck()}
        socialShareDisabled={conn !== "open"}
        onSocialShareVideo={onSocialShareVideoClick}
      />
    </div>
  );
}
