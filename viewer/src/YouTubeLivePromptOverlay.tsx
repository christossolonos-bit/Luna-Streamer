import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useBridge } from "./chatBridgeContext";
import { CloseIcon } from "./icons";

type Props = {
  open: boolean;
  title: string;
  hintUrl: string;
  streamId: string;
};

/** Modal when Luna detects YouTube go-live and needs the watch URL for pytchat. */
export function YouTubeLivePromptOverlay({ open, title, hintUrl, streamId }: Props) {
  const { sendYouTubeLiveUrl, dismissYouTubeLivePrompt } = useBridge();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setUrl(hintUrl.trim());
    setError(null);
    setBusy(false);
  }, [open, hintUrl, streamId]);

  const onDismiss = useCallback(() => {
    dismissYouTubeLivePrompt(streamId);
  }, [dismissYouTubeLivePrompt, streamId]);

  const onSubmit = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      const u = url.trim();
      if (!u) {
        setError("Paste your live watch URL.");
        return;
      }
      setBusy(true);
      setError(null);
      const ok = await sendYouTubeLiveUrl(u);
      setBusy(false);
      if (!ok) {
        setError("Could not reach Luna — check the chat bridge is online.");
      }
    },
    [sendYouTubeLiveUrl, url],
  );

  if (!open) return null;

  return (
    <div
      className="overlay-card overlay-card--center youtube-live-prompt"
      role="dialog"
      aria-label="YouTube Live URL"
      aria-modal="true"
    >
      <div className="overlay-card-header">
        <span className="overlay-card-title">YouTube Live detected</span>
        <button
          type="button"
          className="chat-card-icon-btn"
          onClick={onDismiss}
          aria-label="Dismiss"
          title="Dismiss"
        >
          <CloseIcon />
        </button>
      </div>
      <div className="overlay-card-body">
        <p className="settings-hint">
          Luna sees you may be live on YouTube. Paste the <strong>watch URL</strong> so she can
          connect <strong>pytchat</strong> to read live chat in the viewer (replies stay here /
          TTS only — not posted to YouTube).
        </p>
        {title ? (
          <p className="youtube-live-prompt-title" title={title}>
            {title}
          </p>
        ) : null}
        <form onSubmit={(e) => void onSubmit(e)}>
          <label className="settings-label" htmlFor="yt-live-url">
            Live watch URL
          </label>
          <input
            id="yt-live-url"
            className="settings-input"
            type="url"
            inputMode="url"
            autoComplete="off"
            placeholder="https://www.youtube.com/watch?v=…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={busy}
            autoFocus
          />
          {error ? <p className="settings-hint settings-hint--err">{error}</p> : null}
          <div className="settings-row youtube-live-prompt-actions">
            <button type="submit" className="settings-btn settings-btn--on" disabled={busy}>
              {busy ? "Starting pytchat…" : "Connect pytchat"}
            </button>
            <button type="button" className="settings-btn" onClick={onDismiss} disabled={busy}>
              Not now
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
