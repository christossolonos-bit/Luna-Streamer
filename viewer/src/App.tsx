import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
} from "react";
import "./App.css";
import { TwitchChatPanel } from "./TwitchChatPanel";
import { VrmRuntime, type ChromaKeyMode } from "./vrmRuntime";
import { wsUrl } from "./useChatBridge";

type TabId = "upload" | "screen" | "chat" | "settings";

const CHROMA_STORAGE_KEY = "luna.chromaKey.v1";

function readStoredChromaKey(): ChromaKeyMode {
  try {
    const v = window.localStorage.getItem(CHROMA_STORAGE_KEY);
    if (v === "green" || v === "blue" || v === "off") return v;
  } catch {
    /* ignore */
  }
  return "off";
}

function randomHex(seed: number) {
  const x = Math.floor(Math.abs(Math.sin(seed) * 1e9));
  return `0x${x.toString(16).toUpperCase().slice(0, 6)}`;
}

export default function App() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const runtimeRef = useRef<VrmRuntime | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const motionInputRef = useRef<HTMLInputElement>(null);
  const screenVideoRef = useRef<HTMLVideoElement>(null);

  const [tab, setTab] = useState<TabId>("upload");
  const [fps, setFps] = useState(0);
  const [bootPct, setBootPct] = useState(0);
  const [bufferLine, setBufferLine] = useState(">> Loading Avatar BUFFER: 0% / 100%");
  const [streamHex, setStreamHex] = useState(() => randomHex(1));
  const [sceneLine, setSceneLine] = useState("Initializing scene…");
  const [loadPct, setLoadPct] = useState(0);
  const [drag, setDrag] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);
  const [motionUrl, setMotionUrl] = useState(
    "/@fs/D:/Luna streamer/expressions/motion_1777320820578.vrma",
  );
  const [motionBusy, setMotionBusy] = useState(false);
  const [screenStream, setScreenStream] = useState<MediaStream | null>(null);
  const [screenBusy, setScreenBusy] = useState(false);
  const [chromaKey, setChromaKey] = useState<ChromaKeyMode>(() => readStoredChromaKey());

  useEffect(() => {
    let t = 0;
    const id = window.setInterval(() => {
      t += 1;
      const pct = Math.min(100, Math.round((t / 45) * 100));
      setBootPct(pct);
      setBufferLine(`>> Loading Avatar BUFFER: ${pct}% / 100%`);
      if (pct >= 100) window.clearInterval(id);
    }, 40);
    return () => window.clearInterval(id);
  }, []);

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

  useEffect(() => {
    try {
      window.localStorage.setItem(CHROMA_STORAGE_KEY, chromaKey);
    } catch {
      /* ignore */
    }
    runtimeRef.current?.setChromaKeyMode(chromaKey);
  }, [chromaKey]);

  useEffect(() => {
    const onEmotion = (ev: Event) => {
      const ce = ev as CustomEvent<string>;
      runtimeRef.current?.triggerEmotion(String(ce.detail || ""));
    };
    const onReply = (ev: Event) => {
      const ce = ev as CustomEvent<string>;
      runtimeRef.current?.triggerTalk(String(ce.detail || ""));
    };
    const onSpeaking = (ev: Event) => {
      const ce = ev as CustomEvent<boolean>;
      runtimeRef.current?.setSpeaking(Boolean(ce.detail));
    };
    window.addEventListener("luna-avatar-emotion", onEmotion);
    window.addEventListener("luna-assistant-reply", onReply);
    window.addEventListener("luna-avatar-speaking", onSpeaking);
    return () => {
      window.removeEventListener("luna-avatar-emotion", onEmotion);
      window.removeEventListener("luna-assistant-reply", onReply);
      window.removeEventListener("luna-avatar-speaking", onSpeaking);
    };
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => {
      setStreamHex(randomHex(Date.now()));
    }, 4200);
    return () => window.clearInterval(id);
  }, []);

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
    const vrmUrl = params.get("vrm");
    const idleUrls = params.getAll("idle").filter((v) => v.trim().length > 0);
    if (vrmUrl) {
      setLoadPct(0);
      setLastError(null);
      setSceneLine("> Trying startup avatar…");
      void runtime
        .loadVrmFromUrl(vrmUrl, vrmUrl.split("/").pop() || "startup.vrm")
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

  const onPickMotion = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    const rt = runtimeRef.current;
    if (!rt) return;
    setMotionBusy(true);
    setLastError(null);
    void rt
      .loadVrmaFile(f)
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : String(err);
        setLastError(msg);
        setSceneLine(`Motion error: ${msg}`);
      })
      .finally(() => setMotionBusy(false));
  };

  const loadMotionFromUrl = () => {
    const rt = runtimeRef.current;
    if (!rt) return;
    const url = motionUrl.trim();
    if (!url) return;
    setMotionBusy(true);
    setLastError(null);
    void rt
      .loadVrmaFromUrl(url, url.split("/").pop() || "motion")
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : String(err);
        setLastError(msg);
        setSceneLine(`Motion error: ${msg}`);
      })
      .finally(() => setMotionBusy(false));
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

  const standby =
    bootPct >= 100
      ? "System Standby — drop a .vrm or open Upload"
      : "System boot…";

  return (
    <div className={`app ${chromaKey !== "off" ? "app--chroma" : ""}`}>
      <div className="canvas-wrap">
        <canvas ref={canvasRef} />
      </div>
      <div className="scanlines" aria-hidden />
      <div className="vignette" aria-hidden />

      <div className="hud">
        <div className="hud-top">
          <div className="brand-block">
            <h1>Luna | VRM</h1>
            <p className="sub">NEURAL SYNC</p>
            <div className="terminal" aria-live="polite">
              <p className="line">
                <span className="prompt">&gt;&gt;</span> {bufferLine}
              </p>
              <p className="line">
                <span className="prompt">&gt;</span> {sceneLine}
              </p>
              <p className="line">
                <span className="prompt">&gt;</span> D.STREAM: {streamHex} // SECURE
              </p>
              <p className="line">{standby}</p>
              <p className="line" style={{ opacity: 0.75 }}>
                Connect Luna backend for voice + vision tools (Twitch / Ollama).
              </p>
            </div>
          </div>
          <div className="stats">
            <div>
              <div className="label">RENDER FPS</div>
              <div className={`value ${fps < 30 && fps > 0 ? "warn" : ""}`}>{fps.toFixed(0)}</div>
            </div>
            <div style={{ marginTop: "0.55rem" }}>
              <div className="label">MODEL BUFFER</div>
              <div className="value">{loadPct}%</div>
            </div>
          </div>
        </div>

        <div className="hud-bottom">
          <div className="tabs" role="tablist" aria-label="Control panels">
            {(
              [
                ["upload", "Upload"],
                ["screen", "Screen"],
                ["chat", "Chat"],
                ["settings", "Settings"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                className={`tab ${tab === id ? "active" : ""}`}
                onClick={() => setTab(id)}
                role="tab"
                aria-selected={tab === id}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="panel">
            {tab === "upload" && (
              <>
                <p>
                  Local VRM preview. Style inspired by{" "}
                  <a
                    href="https://vmrchat.vercel.app/"
                    target="_blank"
                    rel="noreferrer"
                    style={{ color: "#00f0ff" }}
                  >
                    vmrchat.vercel.app
                  </a>
                  .
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
                {lastError && (
                  <p style={{ color: "#ff6b8a", marginTop: "0.5rem" }}>{lastError}</p>
                )}
                <p className="mono-note">Orbit: drag · zoom: scroll · pan: right-drag</p>
              </>
            )}
            {tab === "screen" && (
              <>
                <p>Share your desktop/window for live reactions in this viewer session.</p>
                <div className="motion-row">
                  <button
                    type="button"
                    className="chat-clear"
                    onClick={() => void startScreenShare()}
                    disabled={screenBusy || !!screenStream}
                  >
                    {screenBusy ? "Starting…" : screenStream ? "Sharing" : "Start Share"}
                  </button>
                  <button
                    type="button"
                    className="chat-clear"
                    onClick={stopScreenShare}
                    disabled={!screenStream}
                  >
                    Stop Share
                  </button>
                </div>
                <div className="screen-preview-wrap">
                  {screenStream ? (
                    <video ref={screenVideoRef} className="screen-preview" muted playsInline autoPlay />
                  ) : (
                    <p className="mono-note">No active screen share.</p>
                  )}
                </div>
              </>
            )}
            <TwitchChatPanel visible={tab === "chat"} />
            {tab === "settings" && (
              <>
                <p>Ollama host, model name, and Twitch token stay in your Python <code className="inline-code">.env</code>.</p>
                <p>Chroma key background (OBS / browser source):</p>
                <div className="chroma-key-row" role="group" aria-label="Chroma key background">
                  {(
                    [
                      ["off", "Off"],
                      ["green", "Green"],
                      ["blue", "Blue"],
                    ] as const
                  ).map(([id, label]) => (
                    <button
                      key={id}
                      type="button"
                      className={`chat-clear chroma-key-btn ${chromaKey === id ? "chroma-key-btn--active" : ""}`}
                      onClick={() => setChromaKey(id)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <p className="mono-note">
                  Uses a flat screen (#00ff00 / #0047bb), hides fog and floor grid, and removes scanlines for a cleaner key.
                </p>
                <p>Load VRMA motion for your avatar:</p>
                <div className="motion-row">
                  <input
                    className="motion-input"
                    value={motionUrl}
                    onChange={(e) => setMotionUrl(e.target.value)}
                    placeholder="/@fs/D:/Luna streamer/expressions/your_motion.vrma"
                  />
                  <button
                    type="button"
                    className="chat-clear"
                    onClick={loadMotionFromUrl}
                    disabled={motionBusy}
                  >
                    {motionBusy ? "Loading…" : "Load URL"}
                  </button>
                </div>
                <div className="motion-row">
                  <button
                    type="button"
                    className="chat-clear"
                    onClick={() => motionInputRef.current?.click()}
                    disabled={motionBusy}
                  >
                    {motionBusy ? "Loading…" : "Pick .vrma file"}
                  </button>
                  <input
                    ref={motionInputRef}
                    className="hidden-input"
                    type="file"
                    accept=".vrma,model/vrma"
                    onChange={onPickMotion}
                  />
                </div>
                <p className="mono-note">
                  Viewer WebSocket URL: set{" "}
                  <code className="inline-code">VITE_CHAT_WS_URL</code> in{" "}
                  <code className="inline-code">viewer/.env</code> if the bridge is not on{" "}
                  <code className="inline-code">ws://127.0.0.1:8765/ws</code>. Bot:{" "}
                  <code className="inline-code">LUNA_CHAT_WS_HOST</code> /{" "}
                  <code className="inline-code">LUNA_CHAT_WS_PORT</code> (use{" "}
                  <code className="inline-code">0</code> to disable).
                </p>
                <p className="mono-note">
                  For local files in Vite dev, absolute paths use{" "}
                  <code className="inline-code">/@fs/...</code> URLs.
                </p>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
