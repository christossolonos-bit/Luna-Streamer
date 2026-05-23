import { type MouseEventHandler } from "react";
import {
  ChatIcon,
  CohostSummonIcon,
  HimariSummonIcon,
  MicIcon,
  ScreenIcon,
  SettingsIcon,
  ShareVideoIcon,
  UploadIcon,
  YoutubeCommentIcon,
  YoutubeLiveCheckIcon,
  YoutubeTodayCheckIcon,
} from "./icons";

export type DockOverlay = "upload" | "screen" | "settings" | null;

type Props = {
  activeOverlay: DockOverlay;
  onToggleOverlay: (id: Exclude<DockOverlay, null>) => void;
  micListening: boolean;
  micDisabled: boolean;
  /** Mic is armed but Luna is playing TTS — VAD is frozen. */
  micHoldForTts?: boolean;
  onToggleMic: () => void;
  chatOpen: boolean;
  onToggleChat: () => void;
  /** Manual: probe one YouTube /live URL for go-live (pytchat prompt). */
  ytLiveCheckDisabled?: boolean;
  onYoutubeLiveCheck?: () => void;
  /** Manual poll: today's uploads on YouTube observe channels (server). */
  ytObserveCheckDisabled?: boolean;
  onYoutubeObserveCheck?: () => void;
  /** Share any YouTube URL to X/Facebook via Playwright (server; separate from today's check). */
  socialShareDisabled?: boolean;
  onSocialShareVideo?: () => void;
  /** Luna reacts to a YouTube video (transcript + TTS). */
  ytCommentDisabled?: boolean;
  onYoutubeComment?: () => void;
  /** Viktor VRM configured (URL in page query). */
  cohostAvailable?: boolean;
  cohostInScene?: boolean;
  cohostName?: string;
  cohostBusy?: boolean;
  onToggleCohost?: () => void;
  /** Himari VRM configured. */
  himariAvailable?: boolean;
  himariInScene?: boolean;
  himariName?: string;
  himariBusy?: boolean;
  onToggleHimari?: () => void;
};

type DockBtnProps = {
  label: string;
  active?: boolean;
  disabled?: boolean;
  className?: string;
  onClick: MouseEventHandler<HTMLButtonElement>;
  children: React.ReactNode;
};

function DockBtn({
  label,
  active,
  disabled,
  className = "",
  onClick,
  children,
}: DockBtnProps) {
  return (
    <button
      type="button"
      className={`dock-btn ${active ? "dock-btn--active" : ""} ${className}`}
      aria-pressed={active ? true : undefined}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

/**
 * Always-visible icon dock pinned to the bottom-center of the viewport.
 */
export function FloatingDock({
  activeOverlay,
  onToggleOverlay,
  micListening,
  micDisabled,
  micHoldForTts = false,
  onToggleMic,
  chatOpen,
  onToggleChat,
  ytObserveCheckDisabled = true,
  onYoutubeObserveCheck,
  ytLiveCheckDisabled = true,
  onYoutubeLiveCheck,
  socialShareDisabled = true,
  onSocialShareVideo,
  ytCommentDisabled = true,
  onYoutubeComment,
  cohostAvailable = false,
  cohostInScene = false,
  cohostName = "Co-host",
  cohostBusy = false,
  onToggleCohost,
  himariAvailable = false,
  himariInScene = false,
  himariName = "Himari",
  himariBusy = false,
  onToggleHimari,
}: Props) {
  const showCohostRow =
    (cohostAvailable && onToggleCohost) || (himariAvailable && onToggleHimari);

  return (
    <div className="dock" role="toolbar" aria-label="Luna controls">
      <DockBtn
        label="Upload avatar"
        active={activeOverlay === "upload"}
        onClick={() => onToggleOverlay("upload")}
      >
        <UploadIcon />
      </DockBtn>
      {onYoutubeLiveCheck ? (
        <DockBtn
          label="Check YouTube + TikTok live (YouTube opens pytchat URL prompt; TikTok connects chat when live)"
          disabled={ytLiveCheckDisabled}
          onClick={onYoutubeLiveCheck}
        >
          <YoutubeLiveCheckIcon />
        </DockBtn>
      ) : null}
      {onYoutubeObserveCheck ? (
        <DockBtn
          label="Check today's YouTube uploads (observe channels)"
          disabled={ytObserveCheckDisabled}
          onClick={onYoutubeObserveCheck}
        >
          <YoutubeTodayCheckIcon />
        </DockBtn>
      ) : null}
      {onSocialShareVideo ? (
        <DockBtn
          label="Share a YouTube video to X and Facebook (paste URL)"
          disabled={socialShareDisabled}
          onClick={onSocialShareVideo}
        >
          <ShareVideoIcon />
        </DockBtn>
      ) : null}
      {onYoutubeComment ? (
        <DockBtn
          label="Luna comments on a YouTube video (paste URL; posts publicly when YouTube session is configured)"
          disabled={ytCommentDisabled}
          className="dock-btn--yt-comment"
          onClick={onYoutubeComment}
        >
          <YoutubeCommentIcon />
        </DockBtn>
      ) : null}
      {showCohostRow ? (
        <div className="dock-cohost-cluster-row">
          {cohostAvailable && onToggleCohost ? (
            <DockBtn
              label={
                cohostBusy
                  ? `Loading ${cohostName}…`
                  : cohostInScene
                    ? `Dismiss ${cohostName} from scene`
                    : `Summon ${cohostName} into scene`
              }
              active={cohostInScene}
              disabled={cohostBusy}
              className="dock-btn--cohost"
              onClick={onToggleCohost}
            >
              <CohostSummonIcon />
            </DockBtn>
          ) : null}
          {himariAvailable && onToggleHimari ? (
            <DockBtn
              label={
                himariBusy
                  ? `Loading ${himariName}…`
                  : himariInScene
                    ? `Dismiss ${himariName} from scene`
                    : `Summon ${himariName} into scene`
              }
              active={himariInScene}
              disabled={himariBusy}
              className="dock-btn--himari"
              onClick={onToggleHimari}
            >
              <HimariSummonIcon />
            </DockBtn>
          ) : null}
        </div>
      ) : null}
      <DockBtn
        label="Share screen"
        active={activeOverlay === "screen"}
        onClick={() => onToggleOverlay("screen")}
      >
        <ScreenIcon />
      </DockBtn>
      <DockBtn
        label={
          micHoldForTts
            ? "Mic on — paused while Luna speaks (TTS)"
            : micListening
              ? "Stop listening"
              : "Listen with mic"
        }
        active={micListening}
        disabled={micDisabled}
        className={`dock-btn--mic ${micHoldForTts ? "dock-btn--mic-hold" : ""}`}
        onClick={onToggleMic}
      >
        <MicIcon />
      </DockBtn>
      <DockBtn
        label={chatOpen ? "Close chat" : "Open chat"}
        active={chatOpen}
        onClick={onToggleChat}
      >
        <ChatIcon />
      </DockBtn>
      <DockBtn
        label="Settings"
        active={activeOverlay === "settings"}
        onClick={() => onToggleOverlay("settings")}
      >
        <SettingsIcon />
      </DockBtn>
    </div>
  );
}
