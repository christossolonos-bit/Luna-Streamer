import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";
import { useBridge } from "./chatBridgeContext";
import {
  CloseIcon,
  SocialFacebookLoginIcon,
  SocialTiktokLoginIcon,
  SocialXLoginIcon,
  SocialYoutubeLoginIcon,
  VoiceIcon,
} from "./icons";
import type { VrmRuntime, ChromaKeyMode } from "./vrmRuntime";
import { AVATAR_FACE_EXPRESSIONS, type AvatarFaceExpressionId } from "./avatarExpressions";

/** Length of an enrollment clip (steady speech for accuracy). */
const ENROLL_RECORD_MS = 4000;

const EXPRESSION_PREVIEW_STORAGE_KEY = "luna.avatar.expression.preview.v1";

function readStoredExpressionPreview(): AvatarFaceExpressionId {
  try {
    const v = window.localStorage.getItem(EXPRESSION_PREVIEW_STORAGE_KEY);
    if (v && AVATAR_FACE_EXPRESSIONS.some((x) => x.id === v)) {
      return v as AvatarFaceExpressionId;
    }
  } catch {
    /* ignore */
  }
  return "relaxed";
}

function pickRecorderMime(): string {
  if (typeof MediaRecorder === "undefined") return "";
  const cands = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  for (const c of cands) {
    if (MediaRecorder.isTypeSupported(c)) return c;
  }
  return "";
}

type Props = {
  onClose: () => void;
  runtimeRef: React.MutableRefObject<VrmRuntime | null>;
  chromaKey: ChromaKeyMode;
  setChromaKey: (mode: ChromaKeyMode) => void;
  motionUrl: string;
  setMotionUrl: (v: string) => void;
  captionsEnabled: boolean;
  setCaptionsEnabled: (v: boolean) => void;
};

/**
 * Side-drawer overlay for everything that isn't the live chat: TTS voice,
 * Twitch speak toggle, speaker enrollment, YouTube quick-actions, chroma key,
 * VRMA motion, and caption toggle. Scrolls internally so it never escapes the
 * viewport regardless of how tall the browser window is.
 */
export function SettingsOverlay({
  onClose,
  runtimeRef,
  chromaKey,
  setChromaKey,
  motionUrl,
  setMotionUrl,
  captionsEnabled,
  setCaptionsEnabled,
}: Props) {
  const {
    conn,
    speakEnabled,
    setSpeak,
    ttsVoices,
    ttsSpeakerId,
    ttsEnabled,
    pickTtsVoice,
    enrollState,
    sendEnrollBlob,
    clearEnrollment,
    sendPlayRequest,
    sendYouTubeSummary,
    sendSocialInteractiveLogin,
    sendSocialRecoverLogin,
    addStatusLine,
  } = useBridge();

  const [ytInput, setYtInput] = useState("");
  const [ytBusy, setYtBusy] = useState(false);
  const [motionBusy, setMotionBusy] = useState(false);
  const [enrollRecording, setEnrollRecording] = useState(false);
  const [motionError, setMotionError] = useState<string | null>(null);
  const [previewExpression, setPreviewExpression] = useState<AvatarFaceExpressionId>(() =>
    readStoredExpressionPreview(),
  );

  const motionInputRef = useRef<HTMLInputElement>(null);
  const enrollMrRef = useRef<MediaRecorder | null>(null);
  const enrollStreamRef = useRef<MediaStream | null>(null);
  const enrollChunksRef = useRef<BlobPart[]>([]);
  const enrollTimerRef = useRef<number>(0);

  // YouTube quick-action submit (Play / Explain).
  const submitYt = useCallback(
    async (action: "play" | "explain") => {
      const value = ytInput.trim();
      if (!value || ytBusy) return;
      setYtBusy(true);
      try {
        const ok =
          action === "play"
            ? await sendPlayRequest(value)
            : await sendYouTubeSummary(value);
        if (!ok) {
          addStatusLine(
            action === "play"
              ? "!play failed: chat bridge socket not ready."
              : "!explain failed: chat bridge socket not ready.",
          );
        } else {
          setYtInput("");
        }
      } finally {
        setYtBusy(false);
      }
    },
    [addStatusLine, sendPlayRequest, sendYouTubeSummary, ytBusy, ytInput],
  );

  const stopEnrollRecording = useCallback(() => {
    window.clearTimeout(enrollTimerRef.current);
    enrollTimerRef.current = 0;
    const mr = enrollMrRef.current;
    if (mr && mr.state !== "inactive") {
      try {
        mr.stop();
      } catch {
        /* ignore */
      }
    }
    enrollStreamRef.current?.getTracks().forEach((t) => t.stop());
    enrollStreamRef.current = null;
    enrollMrRef.current = null;
  }, []);

  useEffect(() => () => stopEnrollRecording(), [stopEnrollRecording]);

  const startEnrollRecording = useCallback(async () => {
    if (enrollRecording) {
      stopEnrollRecording();
      setEnrollRecording(false);
      return;
    }
    if (conn !== "open") {
      addStatusLine("Enroll: chat bridge not connected.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      enrollStreamRef.current = stream;
      const mimePick = pickRecorderMime();
      const mr = mimePick
        ? new MediaRecorder(stream, { mimeType: mimePick })
        : new MediaRecorder(stream);
      const mime = mr.mimeType || mimePick || "audio/webm";
      enrollChunksRef.current = [];
      mr.ondataavailable = (e) => {
        if (e.data.size > 0) enrollChunksRef.current.push(e.data);
      };
      mr.onstop = () => {
        const parts = [...enrollChunksRef.current];
        enrollChunksRef.current = [];
        enrollStreamRef.current?.getTracks().forEach((t) => t.stop());
        enrollStreamRef.current = null;
        enrollMrRef.current = null;
        setEnrollRecording(false);
        if (parts.length === 0) {
          addStatusLine("Enroll: no audio captured.");
          return;
        }
        const blob = new Blob(parts, { type: mime });
        if (blob.size < 4096) {
          addStatusLine("Enroll: clip too short — speak for ~4 seconds.");
          return;
        }
        void (async () => {
          const res = await sendEnrollBlob(blob, mime);
          if (!res.ok) addStatusLine(`Enroll: ${res.reason}`);
        })();
      };
      enrollMrRef.current = mr;
      mr.start();
      setEnrollRecording(true);
      enrollTimerRef.current = window.setTimeout(() => {
        const cur = enrollMrRef.current;
        if (cur && cur.state !== "inactive") {
          try {
            cur.stop();
          } catch {
            /* ignore */
          }
        }
      }, ENROLL_RECORD_MS);
    } catch (err) {
      console.error("Enroll mic:", err);
      stopEnrollRecording();
      setEnrollRecording(false);
      addStatusLine("Enroll: mic permission denied or recorder error.");
    }
  }, [addStatusLine, conn, enrollRecording, sendEnrollBlob, stopEnrollRecording]);

  const handleClearEnroll = useCallback(() => {
    const ok = clearEnrollment();
    if (!ok) addStatusLine("Enroll: clear failed (socket not ready).");
  }, [addStatusLine, clearEnrollment]);

  // VRMA motion controls.
  const loadMotionUrl = useCallback(() => {
    const rt = runtimeRef.current;
    if (!rt) return;
    const url = motionUrl.trim();
    if (!url) return;
    setMotionBusy(true);
    setMotionError(null);
    void rt
      .loadVrmaFromUrl(url, url.split("/").pop() || "motion")
      .catch((err: unknown) => {
        setMotionError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => setMotionBusy(false));
  }, [motionUrl, runtimeRef]);

  const onPickMotion = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    const rt = runtimeRef.current;
    if (!rt) return;
    setMotionBusy(true);
    setMotionError(null);
    void rt
      .loadVrmaFile(f)
      .catch((err: unknown) => {
        setMotionError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => setMotionBusy(false));
  };

  const setExpressionPreview = useCallback((id: AvatarFaceExpressionId) => {
    setPreviewExpression(id);
    try {
      window.localStorage.setItem(EXPRESSION_PREVIEW_STORAGE_KEY, id);
    } catch {
      /* ignore */
    }
  }, []);

  const applyExpressionPreview = useCallback(() => {
    runtimeRef.current?.triggerEmotion(previewExpression);
  }, [previewExpression, runtimeRef]);

  return (
    <div className="overlay-card overlay-card--settings" role="dialog" aria-label="Settings">
      <div className="overlay-card-header">
        <span className="overlay-card-title">Settings</span>
        <button
          type="button"
          className="chat-card-icon-btn"
          onClick={onClose}
          aria-label="Close settings"
          title="Close"
        >
          <CloseIcon />
        </button>
      </div>
      <div className="overlay-card-body">
        <section className="settings-section">
          <h3 className="settings-section-title">Voice</h3>
          <div className="settings-row">
            <button
              type="button"
              className={`settings-btn ${speakEnabled ? "settings-btn--on" : ""}`}
              onClick={() => setSpeak(!speakEnabled)}
              title="Whether Luna posts replies in Twitch chat"
            >
              Twitch reply: {speakEnabled ? "On" : "Off"}
            </button>
            <button
              type="button"
              className={`settings-btn ${captionsEnabled ? "settings-btn--on" : ""}`}
              onClick={() => setCaptionsEnabled(!captionsEnabled)}
              title="Show captions of Luna's reply over the avatar"
            >
              Captions: {captionsEnabled ? "On" : "Off"}
            </button>
          </div>
          {conn === "open" && ttsVoices.length > 0 ? (
            <div className="settings-voice">
              <span className="settings-label">
                <VoiceIcon /> TTS voice {ttsEnabled ? "" : "(LUNA_TTS off on bot)"}
              </span>
              <select
                className="settings-select"
                value={ttsSpeakerId}
                onChange={(e) => pickTtsVoice(e.target.value)}
              >
                {ttsVoices.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label} — {v.id}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <p className="settings-hint">
              Connect the chat bridge to choose a TTS voice.
            </p>
          )}
        </section>

        <section className="settings-section">
          <h3 className="settings-section-title">Face expression</h3>
          <p className="settings-hint">
            Luna picks an expression from this set from each reply (tone keywords). Preview on
            the avatar anytime.
          </p>
          <div className="settings-row settings-row--yt">
            <select
              className="settings-select"
              value={previewExpression}
              onChange={(e) =>
                setExpressionPreview(e.target.value as AvatarFaceExpressionId)
              }
              aria-label="Face expression preview"
            >
              {AVATAR_FACE_EXPRESSIONS.map((ex) => (
                <option key={ex.id} value={ex.id} title={ex.hint}>
                  {ex.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="settings-btn"
              onClick={applyExpressionPreview}
              title="Fire this expression on the VRM now"
            >
              Preview on avatar
            </button>
          </div>
        </section>

        <section className="settings-section">
          <h3 className="settings-section-title">Speaker enrollment</h3>
          <div className="settings-row">
            <button
              type="button"
              className={`settings-btn ${enrollRecording ? "settings-btn--rec" : ""}`}
              onClick={() => void startEnrollRecording()}
              disabled={conn !== "open"}
              title="Record ~4s of speech. Click again later to add more samples."
            >
              {enrollRecording
                ? "Recording…"
                : enrollState.enrolled
                ? "Add another sample"
                : "Enroll my voice"}
            </button>
            {enrollState.enrolled ? (
              <button
                type="button"
                className="settings-btn"
                onClick={handleClearEnroll}
                disabled={conn !== "open"}
                title="Forget every enrolled sample"
              >
                Clear enrollment
              </button>
            ) : null}
          </div>
          <p className="settings-hint">
            {enrollState.enabled ? "Speaker-only: on" : "Speaker-only: off"}
            {enrollState.enrolled
              ? ` · ${enrollState.samples || 1} sample${
                  (enrollState.samples || 1) === 1 ? "" : "s"
                } · threshold ${enrollState.minSim.toFixed(2)}`
              : " · not enrolled"}
            {typeof enrollState.lastSim === "number"
              ? ` · last sim ${enrollState.lastSim.toFixed(2)}`
              : ""}
          </p>
        </section>

        <section className="settings-section">
          <h3 className="settings-section-title">YouTube</h3>
          <div className="settings-row settings-row--yt">
            <input
              className="settings-input"
              value={ytInput}
              onChange={(e) => setYtInput(e.target.value)}
              placeholder="YouTube URL or search…"
              disabled={conn !== "open" || ytBusy}
            />
            <button
              type="button"
              className="settings-btn"
              onClick={() => void submitYt("play")}
              disabled={conn !== "open" || ytBusy || ytInput.trim().length === 0}
              title="Resolve and (optionally) play with yt-dlp"
            >
              Play
            </button>
            <button
              type="button"
              className="settings-btn"
              onClick={() => void submitYt("explain")}
              disabled={conn !== "open" || ytBusy || ytInput.trim().length === 0}
              title="Fetch transcript, react on stream, and post a YouTube comment when configured"
            >
              Explain
            </button>
          </div>
          <p className="settings-hint">
            In chat you can also type{" "}
            <code className="chat-code">/play &lt;query&gt;</code> or{" "}
            <code className="chat-code">/explain &lt;url&gt;</code>.
          </p>
        </section>

        <section className="settings-section">
          <h3 className="settings-section-title">Social login</h3>
          <p className="settings-hint">
            One-time setup for Playwright sharing, YouTube comments, and TikTok login.{" "}
            <strong>TikTok and X</strong> open <strong>your real Chrome</strong> (not Playwright) so Google sign-in
            works. Sign in, then <strong>close only the login tab</strong> (not the Chrome window X). If saving
            failed, use <strong>Export login</strong>.
          </p>
          <div className="settings-row">
            <button
              type="button"
              className="settings-btn settings-btn--social-x"
              disabled={conn !== "open"}
              onClick={() => void sendSocialInteractiveLogin("x")}
              title="Set up X (Twitter) login for social sharing"
            >
              <SocialXLoginIcon />
              X login
            </button>
            <button
              type="button"
              className="settings-btn settings-btn--social-fb"
              disabled={conn !== "open"}
              onClick={() => void sendSocialInteractiveLogin("facebook")}
              title="Set up Facebook login for social sharing"
            >
              <SocialFacebookLoginIcon />
              Facebook login
            </button>
            <button
              type="button"
              className="settings-btn settings-btn--social-yt"
              disabled={conn !== "open"}
              onClick={() => void sendSocialInteractiveLogin("youtube")}
              title="Set up YouTube login for posting video comments"
            >
              <SocialYoutubeLoginIcon />
              YouTube login
            </button>
            <button
              type="button"
              className="settings-btn settings-btn--social-tiktok"
              disabled={conn !== "open"}
              onClick={() => void sendSocialInteractiveLogin("tiktok")}
              title="Set up TikTok login (same stealth Chrome profile as X/Facebook)"
            >
              <SocialTiktokLoginIcon />
              TikTok login
            </button>
          </div>
          <div className="settings-row">
            <button
              type="button"
              className="settings-btn"
              disabled={conn !== "open"}
              onClick={() => void sendSocialRecoverLogin("all")}
              title="Export cookies from Chrome profiles to JSON (if you logged in but saving failed)"
            >
              Export X + Facebook + TikTok login
            </button>
          </div>
        </section>

        <section className="settings-section">
          <h3 className="settings-section-title">OBS background</h3>
          <div className="settings-row">
            {(
              [
                ["off", "Off"],
                ["transparent", "Transparent"],
                ["green", "Green"],
                ["blue", "Blue"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                className={`settings-btn ${chromaKey === id ? "settings-btn--on" : ""}`}
                onClick={() => setChromaKey(id)}
              >
                {label}
              </button>
            ))}
          </div>
          <p className="settings-hint">
            <strong>Transparent</strong>: real alpha for OBS (no chroma filter). Green/blue: classic
            color key. Scanlines hidden in all capture modes.
          </p>
        </section>

        <section className="settings-section">
          <h3 className="settings-section-title">VRMA motion</h3>
          <div className="settings-row settings-row--yt">
            <input
              className="settings-input"
              value={motionUrl}
              onChange={(e) => setMotionUrl(e.target.value)}
              placeholder="/@fs/D:/Luna streamer/expressions/your_motion.vrma"
            />
            <button
              type="button"
              className="settings-btn"
              onClick={loadMotionUrl}
              disabled={motionBusy}
            >
              {motionBusy ? "Loading…" : "Load URL"}
            </button>
          </div>
          <div className="settings-row">
            <button
              type="button"
              className="settings-btn"
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
          {motionError ? (
            <p className="settings-hint settings-hint--err">{motionError}</p>
          ) : null}
        </section>

        <section className="settings-section">
          <h3 className="settings-section-title">Bridge</h3>
          <p className="settings-hint">
            Run <code className="chat-code">python twitch_bot.py</code> with the
            chat bridge enabled. Override URL via{" "}
            <code className="chat-code">VITE_CHAT_WS_URL</code> in{" "}
            <code className="chat-code">viewer/.env</code> if the bridge isn't on{" "}
            <code className="chat-code">ws://127.0.0.1:8765/ws</code>.
          </p>
        </section>
      </div>
    </div>
  );
}
