import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useBridge } from "./chatBridgeContext";
import { CloseIcon } from "./icons";

type Props = {
  open: boolean;
  platform: string;
  suggestedTitle: string;
  url: string;
  streamId: string;
};

/** Modal before Luna posts go-live to X / Facebook — streamer confirms the title. */
export function LiveSocialTitlePromptOverlay({
  open,
  platform,
  suggestedTitle,
  url,
  streamId,
}: Props) {
  const { sendLiveSocialTitle, dismissLiveSocialTitlePrompt } = useBridge();
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setTitle(suggestedTitle.trim());
    setError(null);
    setBusy(false);
  }, [open, suggestedTitle, streamId, platform]);

  const onDismiss = useCallback(() => {
    dismissLiveSocialTitlePrompt(platform, streamId);
  }, [dismissLiveSocialTitlePrompt, platform, streamId]);

  const onSubmit = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      const t = title.trim();
      if (!t) {
        setError("Enter the stream title for X and Facebook.");
        return;
      }
      setBusy(true);
      setError(null);
      const ok = await sendLiveSocialTitle({
        title: t,
        platform,
        streamId,
        url,
      });
      setBusy(false);
      if (!ok) {
        setError("Could not reach Luna — check the chat bridge is online.");
      }
    },
    [sendLiveSocialTitle, title, platform, streamId, url],
  );

  if (!open) return null;

  const platLabel =
    platform === "youtube"
      ? "YouTube"
      : platform === "tiktok"
        ? "TikTok"
        : platform === "twitch"
          ? "Twitch"
          : platform || "Live";

  return (
    <div
      className="overlay-card overlay-card--center youtube-live-prompt live-social-title-prompt"
      role="dialog"
      aria-label="Stream title for social post"
      aria-modal="true"
    >
      <div className="overlay-card-header">
        <span className="overlay-card-title">Go live on {platLabel}</span>
        <button
          type="button"
          className="chat-card-icon-btn"
          onClick={onDismiss}
          aria-label="Dismiss"
          title="Skip X/Facebook post"
        >
          <CloseIcon />
        </button>
      </div>
      <div className="overlay-card-body">
        <p className="settings-hint">
          Luna posted to <strong>Discord</strong> already. Confirm the <strong>stream title</strong> for
          the invitation post on <strong>X</strong> and <strong>Facebook</strong> (with your promo image).
        </p>
        <form onSubmit={(e) => void onSubmit(e)}>
          <label className="settings-label" htmlFor="live-social-title">
            Stream title
          </label>
          <input
            id="live-social-title"
            className="settings-input"
            type="text"
            autoComplete="off"
            placeholder="Tonight: Luna & Viktor chaos hour"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={busy}
            autoFocus
          />
          {error ? <p className="settings-hint settings-hint--err">{error}</p> : null}
          <div className="settings-row youtube-live-prompt-actions">
            <button type="submit" className="settings-btn settings-btn--on" disabled={busy}>
              {busy ? "Posting…" : "Post to X & Facebook"}
            </button>
            <button type="button" className="settings-btn" onClick={onDismiss} disabled={busy}>
              Skip social
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
