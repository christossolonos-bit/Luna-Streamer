import { useCallback, useEffect, useRef, useState } from "react";
import { useChatBridge, wsUrl } from "./useChatBridge";

/** After this much silence (ms) following speech, audio is sent for transcription. */
const MIC_SILENCE_MS = 3000;
/** Normalized RMS above this counts as “speech” (tune if auto-send is early/late). */
const MIC_SPEECH_THRESHOLD = 0.017;

function rmsLevel(analyser: AnalyserNode): number {
  const buf = new Uint8Array(analyser.fftSize);
  analyser.getByteTimeDomainData(buf);
  let sum = 0;
  for (let i = 0; i < buf.length; i++) {
    const d = buf[i]! - 128;
    sum += d * d;
  }
  return Math.sqrt(sum / buf.length) / 128;
}

function pickRecorderMime(): string {
  if (typeof MediaRecorder === "undefined") return "";
  const cands = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  for (const c of cands) {
    if (MediaRecorder.isTypeSupported(c)) return c;
  }
  return "";
}

function VoiceIcon() {
  return (
    <svg
      className="chat-voice-icon-svg"
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" x2="12" y1="19" y2="22" />
    </svg>
  );
}

type TwitchChatPanelProps = {
  visible?: boolean;
};

/** Length of an enrollment clip (steady speech for accuracy). */
const ENROLL_RECORD_MS = 4000;

export function TwitchChatPanel({ visible = true }: TwitchChatPanelProps) {
  const {
    lines,
    conn,
    clear,
    speakEnabled,
    setSpeak,
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
    sendPlayRequest,
    sendYouTubeSummary,
  } = useChatBridge(true);
  const [enrollRecording, setEnrollRecording] = useState(false);
  const enrollMrRef = useRef<MediaRecorder | null>(null);
  const enrollStreamRef = useRef<MediaStream | null>(null);
  const enrollChunksRef = useRef<BlobPart[]>([]);
  const enrollTimerRef = useRef<number>(0);
  const [ytInput, setYtInput] = useState("");
  const [ytBusy, setYtBusy] = useState(false);
  const url = wsUrl();
  const endRef = useRef<HTMLDivElement>(null);
  const voiceWrapRef = useRef<HTMLDivElement>(null);
  const [prompt, setPrompt] = useState("");
  const [voiceMenuOpen, setVoiceMenuOpen] = useState(false);
  /** Mic armed: Luna is listening until you turn Mic off. Utterances flush on ~3s silence. */
  const [micListening, setMicListening] = useState(false);
  const voiceChunksRef = useRef<BlobPart[]>([]);
  const voiceMimeRef = useRef("");
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const micArmedRef = useRef(false);
  const lastSoundMsRef = useRef(0);
  const utteranceHadSpeechRef = useRef(false);
  const rafIdRef = useRef(0);
  const sendVoiceBlobRef = useRef(sendVoiceBlob);
  const addStatusLineRef = useRef(addStatusLine);

  sendVoiceBlobRef.current = sendVoiceBlob;
  addStatusLineRef.current = addStatusLine;

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines]);

  useEffect(() => {
    if (!voiceMenuOpen) return;
    const onDoc = (ev: MouseEvent) => {
      const el = voiceWrapRef.current;
      if (el && !el.contains(ev.target as Node)) setVoiceMenuOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [voiceMenuOpen]);

  const stopRaf = useCallback(() => {
    if (rafIdRef.current) {
      cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = 0;
    }
  }, []);

  const cleanupMicSession = useCallback(() => {
    stopRaf();
    micArmedRef.current = false;
    const mr = mediaRecorderRef.current;
    mediaRecorderRef.current = null;
    if (mr && mr.state !== "inactive") {
      try {
        mr.stop();
      } catch {
        /* ignore */
      }
    }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    analyserRef.current = null;
    void audioContextRef.current?.close().catch(() => {});
    audioContextRef.current = null;
    voiceChunksRef.current = [];
    utteranceHadSpeechRef.current = false;
    setMicListening(false);
  }, [stopRaf]);

  const flushRecorderAndSend = useCallback(
    (afterSend: "restart" | "shutdown") => {
      const mr = mediaRecorderRef.current;
      if (!mr || mr.state === "inactive") {
        if (afterSend === "shutdown") cleanupMicSession();
        return;
      }
      const mime = voiceMimeRef.current;
      const onStop = () => {
        mr.removeEventListener("stop", onStop);
        void (async () => {
          /* Spec: final dataavailable is delivered before stop; read chunks immediately. */
          const parts = [...voiceChunksRef.current];
          voiceChunksRef.current = [];
          utteranceHadSpeechRef.current = false;
          lastSoundMsRef.current = performance.now();

          if (parts.length > 0) {
            const blob = new Blob(parts, { type: mime });
            if (blob.size >= 256) {
              const result = await sendVoiceBlobRef.current(blob, mime);
              if (!result.ok) {
                addStatusLineRef.current(`Mic: ${result.reason}`);
              }
            }
          }

          if (afterSend === "shutdown" || !micArmedRef.current) {
            cleanupMicSession();
            return;
          }

          const stream = streamRef.current;
          if (!stream || !micArmedRef.current) {
            cleanupMicSession();
            return;
          }
          try {
            const mimePick = pickRecorderMime();
            const next = mimePick
              ? new MediaRecorder(stream, { mimeType: mimePick })
              : new MediaRecorder(stream);
            voiceMimeRef.current = next.mimeType || mimePick || "audio/webm";
            next.ondataavailable = (e) => {
              if (e.data.size > 0) voiceChunksRef.current.push(e.data);
            };
            next.onstop = () => {
              /* replaced on next flush */
            };
            mediaRecorderRef.current = next;
            /* No timeslice: one full WebM/Matroska per utterance so ffmpeg always sees a valid EBML header. */
            next.start();
          } catch {
            addStatusLineRef.current("Mic: could not restart recorder after silence.");
            cleanupMicSession();
          }
        })();
      };
      mr.addEventListener("stop", onStop);
      try {
        mr.stop();
      } catch {
        /* ignore */
      }
    },
    [cleanupMicSession],
  );

  const runVadLoop = useCallback(() => {
    const tick = () => {
      if (!micArmedRef.current || !analyserRef.current) {
        rafIdRef.current = 0;
        return;
      }
      const mr = mediaRecorderRef.current;
      if (!mr || mr.state !== "recording") {
        rafIdRef.current = requestAnimationFrame(tick);
        return;
      }
      const level = rmsLevel(analyserRef.current);
      const now = performance.now();
      if (level >= MIC_SPEECH_THRESHOLD) {
        lastSoundMsRef.current = now;
        utteranceHadSpeechRef.current = true;
      } else if (
        utteranceHadSpeechRef.current &&
        now - lastSoundMsRef.current >= MIC_SILENCE_MS
      ) {
        flushRecorderAndSend("restart");
      }
      rafIdRef.current = requestAnimationFrame(tick);
    };
    rafIdRef.current = requestAnimationFrame(tick);
  }, [flushRecorderAndSend]);

  useEffect(() => {
    return () => {
      stopRaf();
      micArmedRef.current = false;
      const mr = mediaRecorderRef.current;
      mediaRecorderRef.current = null;
      if (mr && mr.state !== "inactive") {
        try {
          mr.stop();
        } catch {
          /* ignore */
        }
      }
      streamRef.current?.getTracks().forEach((t) => t.stop());
      void audioContextRef.current?.close().catch(() => {});
    };
  }, [stopRaf]);

  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const trimmed = prompt.trim();
    if (trimmed.toLowerCase().startsWith("/play ")) {
      const q = trimmed.slice("/play ".length).trim();
      const ok = await sendPlayRequest(q);
      if (ok) setPrompt("");
      else addStatusLine("!play failed: chat bridge socket not ready.");
      return;
    }
    if (
      trimmed.toLowerCase().startsWith("/explain ") ||
      trimmed.toLowerCase().startsWith("/yt ")
    ) {
      const u = trimmed.replace(/^\/(explain|yt)\s+/i, "").trim();
      const ok = await sendYouTubeSummary(u);
      if (ok) setPrompt("");
      else addStatusLine("!explain failed: chat bridge socket not ready.");
      return;
    }
    const ok = await sendPrompt(prompt);
    if (ok) {
      setPrompt("");
    } else {
      addStatusLine(
        "Send failed: chat bridge socket not ready. Wait for ● live, or refresh if this persists.",
      );
    }
  };

  const submitYtAction = useCallback(
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

  const toggleMicSession = async () => {
    if (micListening) {
      micArmedRef.current = false;
      flushRecorderAndSend("shutdown");
      return;
    }
    if (conn !== "open") return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const ctx = new AudioContext();
      audioContextRef.current = ctx;
      await ctx.resume().catch(() => {});
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.5;
      source.connect(analyser);
      analyserRef.current = analyser;

      const mimePick = pickRecorderMime();
      const mr = mimePick
        ? new MediaRecorder(stream, { mimeType: mimePick })
        : new MediaRecorder(stream);
      voiceMimeRef.current = mr.mimeType || mimePick || "audio/webm";
      voiceChunksRef.current = [];
      mr.ondataavailable = (e) => {
        if (e.data.size > 0) voiceChunksRef.current.push(e.data);
      };
      mr.onstop = () => {
        /* flushRecorderAndSend attaches per-segment handler */
      };
      mediaRecorderRef.current = mr;
      micArmedRef.current = true;
      lastSoundMsRef.current = performance.now();
      utteranceHadSpeechRef.current = false;
      setMicListening(true);
      mr.start();
      runVadLoop();
    } catch (err) {
      console.error("Microphone:", err);
      cleanupMicSession();
      addStatusLine("Mic: permission or recorder error — check browser permissions.");
    }
  };

  return (
    <div className={`chat-panel ${visible ? "" : "chat-panel--hidden"}`}>
      <div className="chat-toolbar">
        <span className={`chat-conn chat-conn--${conn}`}>
          {conn === "open" ? "● live" : conn === "connecting" ? "◌ connecting…" : "○ offline"}
        </span>
        <span className="chat-ws-url" title="Set VITE_CHAT_WS_URL to override">
          {url}
        </span>
        <button type="button" className="chat-clear" onClick={clear}>
          Clear
        </button>
        <button
          type="button"
          className={`chat-clear ${speakEnabled ? "chat-speak-on" : "chat-speak-off"}`}
          onClick={() => setSpeak(!speakEnabled)}
          title="Toggle whether Luna sends replies to Twitch chat"
        >
          {speakEnabled ? "Speak: On" : "Speak: Off"}
        </button>
        {conn === "open" && ttsVoices.length > 0 ? (
          <div className="chat-voice-wrap" ref={voiceWrapRef}>
            <button
              type="button"
              className={`chat-voice-btn ${!ttsEnabled ? "chat-voice-btn--idle" : ""} ${voiceMenuOpen ? "chat-voice-btn--open" : ""}`}
              onClick={() => setVoiceMenuOpen((o) => !o)}
              title={
                ttsEnabled
                  ? "Choose TTS voice (CSM speaker id or Fish reference id)"
                  : "Choose TTS voice — enable LUNA_TTS=1 on the bot to synthesize"
              }
              aria-expanded={voiceMenuOpen}
              aria-haspopup="listbox"
            >
              <VoiceIcon />
            </button>
            {voiceMenuOpen ? (
              <ul className="chat-voice-menu" role="listbox" aria-label="TTS voices">
                {ttsVoices.map((v) => (
                  <li key={v.id} role="option" aria-selected={v.id === ttsSpeakerId}>
                    <button
                      type="button"
                      className={`chat-voice-option ${v.id === ttsSpeakerId ? "chat-voice-option--active" : ""}`}
                      onClick={() => {
                        pickTtsVoice(v.id);
                        setVoiceMenuOpen(false);
                      }}
                    >
                      <span className="chat-voice-option-label">{v.label}</span>
                      <span className="chat-voice-option-id">{v.id}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </div>
      <div className="chat-enroll-row">
        <button
          type="button"
          className={`chat-clear ${enrollRecording ? "chat-mic-on" : ""}`}
          onClick={() => void startEnrollRecording()}
          disabled={conn !== "open"}
          title="Record ~4 seconds of speech so Luna recognizes your voice"
        >
          {enrollRecording
            ? "Recording…"
            : enrollState.enrolled
            ? "Re-record voice"
            : "Enroll my voice"}
        </button>
        {enrollState.enrolled ? (
          <button
            type="button"
            className="chat-clear"
            onClick={handleClearEnroll}
            disabled={conn !== "open"}
            title="Forget the enrolled voice (any speaker may then be heard)"
          >
            Clear enrollment
          </button>
        ) : null}
        <span className="chat-enroll-status">
          {enrollState.enabled ? "Speaker-only: on" : "Speaker-only: off"}
          {enrollState.enrolled
            ? ` · enrolled · threshold ${enrollState.minSim.toFixed(2)}`
            : " · not enrolled"}
          {typeof enrollState.lastSim === "number"
            ? ` · last sim ${enrollState.lastSim.toFixed(2)}`
            : ""}
        </span>
      </div>
      <div className="chat-yt-row">
        <input
          className="chat-input chat-yt-input"
          value={ytInput}
          onChange={(e) => setYtInput(e.target.value)}
          placeholder="YouTube URL or search…"
          disabled={conn !== "open" || ytBusy}
        />
        <button
          type="button"
          className="chat-clear"
          onClick={() => void submitYtAction("play")}
          disabled={conn !== "open" || ytBusy || ytInput.trim().length === 0}
          title="Resolve and (optionally) download audio with yt-dlp"
        >
          Play
        </button>
        <button
          type="button"
          className="chat-clear"
          onClick={() => void submitYtAction("explain")}
          disabled={conn !== "open" || ytBusy || ytInput.trim().length === 0}
          title="Fetch the transcript and let Luna react on stream"
        >
          Explain
        </button>
      </div>
      <p className="chat-hint">
        Run <code className="chat-code">python twitch_bot.py</code> with the bridge (port{" "}
        <code className="chat-code">8765</code> by default). Tips: type{" "}
        <code className="chat-code">/play &lt;query&gt;</code> or{" "}
        <code className="chat-code">/explain &lt;url&gt;</code> in the chat input as a shortcut.
      </p>
      <p className="chat-hint chat-hint--mic">
        <strong>Mic: On</strong> lets Luna listen continuously. After you stop talking, about{" "}
        <strong>{Math.round(MIC_SILENCE_MS / 1000)}s</strong> of silence sends that line for transcription.
        Turn <strong>Mic: Off</strong> when you are done talking to Luna.
      </p>
      <div className="chat-feed" role="log" aria-live="polite" aria-relevant="additions">
        {lines.length === 0 && (
          <div className="chat-empty">Waiting for Twitch messages…</div>
        )}
        {lines.map((row) => (
          <div key={row.id} className={`chat-line chat-line--${row.kind}`}>
            {row.kind === "status" && <span className="chat-status">{row.text}</span>}
            {row.kind === "chat" && (
              <>
                <span className="chat-user">{row.user}</span>
                {row.channel ? (
                  <span className="chat-channel"> #{row.channel}</span>
                ) : null}
                <span className="chat-sep">: </span>
                <span className="chat-text">{row.text}</span>
              </>
            )}
            {row.kind === "assistant" && (
              <>
                <span className="chat-assistant-label">{row.user}</span>
                <span className="chat-assistant-body">{row.text}</span>
              </>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>
      <form className="chat-input-row" onSubmit={onSubmit}>
        <button
          type="button"
          className={`chat-clear ${micListening ? "chat-mic-on" : "chat-mic-off"}`}
          disabled={conn !== "open"}
          onClick={() => void toggleMicSession()}
          aria-pressed={micListening}
          title={
            micListening
              ? `Mic on — Luna listens; each phrase sends after ~${Math.round(MIC_SILENCE_MS / 1000)}s silence. Click to stop.`
              : "Mic off — click so Luna can hear you (panel must be connected)."
          }
        >
          {micListening ? "Mic: On" : "Mic: Off"}
        </button>
        <input
          className="chat-input"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Talk to Luna here..."
        />
        <button
          type="submit"
          className="chat-clear"
          disabled={conn !== "open" || prompt.trim().length === 0}
        >
          Send
        </button>
      </form>
    </div>
  );
}
