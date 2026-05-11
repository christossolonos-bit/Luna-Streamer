import { useCallback, useEffect, useRef, useState } from "react";
import { useBridge } from "./chatBridgeContext";

/** Silence (ms) after speech before an utterance is sent for transcription. */
export const MIC_SILENCE_MS = 3000;
/** Normalized RMS above this counts as speech. Tune if auto-send is early/late. */
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

/**
 * Single-instance microphone listening hook.
 *
 * Manages getUserMedia + MediaRecorder + an RMS-based VAD. Each utterance is
 * flushed and sent through the chat bridge after ~3s of silence; the recorder
 * is then restarted so Luna keeps listening until the caller toggles off.
 *
 * While ``avatarSpeaking`` from the bridge is true (Luna is playing TTS on
 * the streamer's machine), VAD is frozen: no silence flush and no RMS updates,
 * so headphone bleed does not trigger transcription. When TTS starts, any
 * in-flight recording segment is discarded without upload; when TTS ends, the
 * silence clock resets so Luna does not immediately ship stale audio.
 *
 * Returns ``listening``, ``toggle``, ``disabled`` (no WS), and ``holdForTts``
 * (mic armed but paused for TTS — for UI affordance).
 */
export function useMicSession() {
  const { sendVoiceBlob, addStatusLine, conn, avatarSpeaking } = useBridge();
  const [listening, setListening] = useState(false);
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
  const avatarSpeakingRef = useRef(avatarSpeaking);
  const sendVoiceBlobRef = useRef(sendVoiceBlob);
  const addStatusLineRef = useRef(addStatusLine);

  avatarSpeakingRef.current = avatarSpeaking;
  sendVoiceBlobRef.current = sendVoiceBlob;
  addStatusLineRef.current = addStatusLine;

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
    setListening(false);
  }, [stopRaf]);

  /** Stop the current MediaRecorder segment, drop buffered audio, restart — no WebSocket send. */
  const discardSegmentAndRestart = useCallback(() => {
    const mr = mediaRecorderRef.current;
    if (!mr || mr.state === "inactive") return;
    const onStop = () => {
      mr.removeEventListener("stop", onStop);
      voiceChunksRef.current = [];
      utteranceHadSpeechRef.current = false;
      lastSoundMsRef.current = performance.now();

      if (!micArmedRef.current) {
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
        next.start();
      } catch {
        addStatusLineRef.current("Mic: could not restart recorder after TTS.");
        cleanupMicSession();
      }
    };
    mr.addEventListener("stop", onStop);
    try {
      mr.stop();
    } catch {
      /* ignore */
    }
  }, [cleanupMicSession]);

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
      // Do not evaluate silence / speech while Luna's TTS is playing — avoids
      // picking up her voice from headphones and auto-sending junk audio.
      if (avatarSpeakingRef.current) {
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

  // When TTS starts: drop any partial utterance so it is never sent. When TTS
  // ends: reset the silence clock so we do not flush immediately on stale VAD.
  useEffect(() => {
    if (avatarSpeaking) {
      if (micArmedRef.current && listening) {
        discardSegmentAndRestart();
      }
      return;
    }
    lastSoundMsRef.current = performance.now();
    utteranceHadSpeechRef.current = false;
  }, [avatarSpeaking, discardSegmentAndRestart, listening]);

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

  const toggle = useCallback(async () => {
    if (listening) {
      micArmedRef.current = false;
      flushRecorderAndSend("shutdown");
      return;
    }
    if (conn !== "open") {
      addStatusLineRef.current("Mic: chat bridge not connected.");
      return;
    }
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
      setListening(true);
      mr.start();
      runVadLoop();
    } catch (err) {
      console.error("Microphone:", err);
      cleanupMicSession();
      addStatusLineRef.current(
        "Mic: permission or recorder error — check browser permissions.",
      );
    }
  }, [cleanupMicSession, conn, flushRecorderAndSend, listening, runVadLoop]);

  const holdForTts = listening && avatarSpeaking;

  return {
    listening,
    toggle,
    disabled: conn !== "open",
    holdForTts,
  } as const;
}
