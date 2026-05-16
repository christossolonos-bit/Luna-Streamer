import { useEffect, useRef, useState, type MouseEventHandler } from "react";
import {
  ChatIcon,
  CohostOptionsIcon,
  CohostSummonIcon,
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
  /** Co-host VRM configured (URL in page query); button summons/dismisses. */
  cohostAvailable?: boolean;
  cohostInScene?: boolean;
  cohostName?: string;
  cohostBusy?: boolean;
  onToggleCohost?: () => void;
  /** Banter triggers need an open WS to the bot. */
  banterWsDisabled?: boolean;
  /** When true, idle + manual use open-ended full banter (short mode uses ``LUNA_COHOST_EXCHANGE_LINES``). */
  cohostFullConversation?: boolean;
  onCohostFullConversationChange?: (enabled: boolean) => void;
  /** Fire server-side Luna↔cohost banter; ``full`` matches the long-script checkbox. */
  onCohostBanterNow?: (fullConversation: boolean) => void;
};

type DockBtnProps = {
  label: string;
  active?: boolean;
  disabled?: boolean;
  className?: string;
  ariaExpanded?: boolean;
  onClick: MouseEventHandler<HTMLButtonElement>;
  children: React.ReactNode;
};

function DockBtn({
  label,
  active,
  disabled,
  className = "",
  ariaExpanded,
  onClick,
  children,
}: DockBtnProps) {
  return (
    <button
      type="button"
      className={`dock-btn ${active ? "dock-btn--active" : ""} ${className}`}
      aria-pressed={active ? true : undefined}
      aria-expanded={ariaExpanded}
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
 *
 * Each button either toggles an overlay panel (upload / screen / settings),
 * toggles continuous mic listening, or toggles the chat overlay. The mic
 * button gets a teal glow while listening so it's obvious on stream.
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
  banterWsDisabled = true,
  cohostFullConversation = false,
  onCohostFullConversationChange,
  onCohostBanterNow,
}: Props) {
  const [cohostPanelOpen, setCohostPanelOpen] = useState(false);
  const cohostClusterRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!cohostPanelOpen) return;
    const handler = (e: PointerEvent) => {
      if (
        cohostClusterRef.current &&
        !cohostClusterRef.current.contains(e.target as Node)
      ) {
        setCohostPanelOpen(false);
      }
    };
    const id = window.setTimeout(
      () => document.addEventListener("pointerdown", handler, true),
      0,
    );
    return () => {
      window.clearTimeout(id);
      document.removeEventListener("pointerdown", handler, true);
    };
  }, [cohostPanelOpen]);

  const showBanterControls =
    cohostAvailable &&
    Boolean(onToggleCohost) &&
    Boolean(onCohostBanterNow) &&
    Boolean(onCohostFullConversationChange);

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
          label="Check YouTube live (one channel URL from server; opens pytchat URL prompt if live)"
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
      {showBanterControls ? (
        <div
          className={`dock-cohost-cluster ${cohostPanelOpen ? "dock-cohost-cluster--open" : ""}`}
          ref={cohostClusterRef}
        >
          <div className="dock-cohost-cluster-row">
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
              onClick={() => {
                setCohostPanelOpen(false);
                onToggleCohost?.();
              }}
            >
              <CohostSummonIcon />
            </DockBtn>
            <DockBtn
              label={`${cohostName} banter options`}
              ariaExpanded={cohostPanelOpen}
              disabled={cohostBusy}
              className="dock-btn--cohost-opts"
              onClick={(e) => {
                e.stopPropagation();
                setCohostPanelOpen((v) => !v);
              }}
            >
              <CohostOptionsIcon />
            </DockBtn>
          </div>
          {cohostPanelOpen ? (
            <div
              className="dock-cohost-panel"
              role="dialog"
              aria-label={`${cohostName} banter`}
              onPointerDown={(e) => e.stopPropagation()}
            >
              <div className="dock-cohost-panel-title">{cohostName} banter</div>
              <label className="dock-cohost-check">
                <input
                  type="checkbox"
                  checked={cohostFullConversation}
                  onChange={(e) => onCohostFullConversationChange?.(e.target.checked)}
                />
                <span>
                  Open-ended full conversation (idle + manual; not the short exchange cap)
                </span>
              </label>
              <button
                type="button"
                className="dock-cohost-run"
                disabled={banterWsDisabled || cohostBusy}
                onClick={() => {
                  onCohostBanterNow?.(cohostFullConversation);
                  setCohostPanelOpen(false);
                }}
              >
                Run banter now
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
      {!showBanterControls && cohostAvailable && onToggleCohost ? (
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
