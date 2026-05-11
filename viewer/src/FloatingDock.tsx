import {
  ChatIcon,
  MicIcon,
  ScreenIcon,
  SettingsIcon,
  UploadIcon,
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
};

type DockBtnProps = {
  label: string;
  active?: boolean;
  disabled?: boolean;
  className?: string;
  onClick: () => void;
  children: React.ReactNode;
};

function DockBtn({ label, active, disabled, className = "", onClick, children }: DockBtnProps) {
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
}: Props) {
  return (
    <div className="dock" role="toolbar" aria-label="Luna controls">
      <DockBtn
        label="Upload avatar"
        active={activeOverlay === "upload"}
        onClick={() => onToggleOverlay("upload")}
      >
        <UploadIcon />
      </DockBtn>
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
