import type { SVGProps } from "react";

const base = {
  width: 18,
  height: 18,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true as const,
};

export function UploadIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" x2="12" y1="3" y2="15" />
    </svg>
  );
}

/** Calendar with a dot: today's uploads / manual YouTube observe check. */
export function YoutubeTodayCheckIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
      <line x1="16" y1="2" x2="16" y2="6" />
      <line x1="8" y1="2" x2="8" y2="6" />
      <line x1="3" y1="10" x2="21" y2="10" />
      <circle cx="12" cy="16" r="2" fill="currentColor" stroke="none" />
    </svg>
  );
}

/** Broadcast / go-live: manual check whether your YouTube channel is live (one URL from server). */
export function YoutubeLiveCheckIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <circle cx="12" cy="12" r="8" />
      <polygon points="10 9 10 15 16 12" fill="currentColor" stroke="none" />
    </svg>
  );
}

/** Play + chat bubble — Luna comments on a YouTube video you paste. */
export function YoutubeCommentIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <rect x="2" y="7" width="13" height="10" rx="2" />
      <polygon points="7 10 7 14 11 12" fill="currentColor" stroke="none" />
      <path d="M14 5c3.3 0 6 2.7 6 6s-2.7 6-6 6h-4l-3 3v-3h-1c-3.3 0-6-2.7-6-6s2.7-6 6-6h4" />
    </svg>
  );
}

/** Share / broadcast (manual social post for a YouTube URL). */
export function ShareVideoIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <circle cx="18" cy="5" r="3" />
      <circle cx="6" cy="12" r="3" />
      <circle cx="18" cy="19" r="3" />
      <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
      <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
    </svg>
  );
}

/** Key — open browser to log in to X/Facebook for Playwright (legacy / optional). */
export function SocialLoginKeyIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <circle cx="8" cy="16" r="5" />
      <path d="M10.5 11.5 21 2" />
      <path d="m13 9 3 3" />
    </svg>
  );
}

/** X — open Chrome to save session for X posting (server Playwright). */
export function SocialXLoginIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <line x1="5" y1="5" x2="19" y2="19" strokeWidth={2.4} />
      <line x1="19" y1="5" x2="5" y2="19" strokeWidth={2.4} />
    </svg>
  );
}

/** YouTube — open Chrome to save session for posting video comments. */
export function SocialYoutubeLoginIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <rect x="2" y="6" width="14" height="10" rx="2" />
      <polygon points="7 9 7 13 11 11" fill="currentColor" stroke="none" />
    </svg>
  );
}

/** TikTok — open Chrome to save session for TikTok login. */
export function SocialTiktokLoginIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <path d="M14 4v6.2a3.8 3.8 0 1 1-2.4-3.5V4h2.4Z" />
      <path d="M10 4v6.8a3.2 3.2 0 1 1-2-2.9" />
    </svg>
  );
}

/** Facebook — open Chrome to save session for Facebook posting. */
export function SocialFacebookLoginIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      width={18}
      height={18}
      viewBox="0 0 24 24"
      fill="currentColor"
      stroke="none"
      aria-hidden="true"
      {...props}
    >
      <path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3.5l.5-4H14V7a1 1 0 0 1 1-1h3V2z" />
    </svg>
  );
}

export function ScreenIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <rect x="2" y="3" width="20" height="14" rx="2" />
      <line x1="8" x2="16" y1="21" y2="21" />
      <line x1="12" x2="12" y1="17" y2="21" />
    </svg>
  );
}

export function MicIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" x2="12" y1="19" y2="22" />
    </svg>
  );
}

/** Dual figures — summon / dismiss co-host (e.g. Viktor). */
export function CohostSummonIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <circle cx="9" cy="8" r="2.5" />
      <path d="M5 19v-1.5a4 4 0 0 1 8 0V19" />
      <circle cx="16" cy="8" r="2.5" />
      <path d="M12 19v-1.5a4 4 0 0 1 8 0V19" />
    </svg>
  );
}

/** Viktor + Himari co-host banter pair (both on stage, Luna off). */
export function ViktorHimariDuoIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <circle cx="7.5" cy="9" r="2.2" />
      <path d="M3.5 18.5v-1.4a4 4 0 0 1 8 0V18.5" />
      <path d="M11.5 7.5V6h5v1.5" />
      <path d="M10 7.5h8" />
      <circle cx="17" cy="11.5" r="2" />
      <path d="M13 18.5v-1.3a3.5 3.5 0 0 1 8 0V18.5" />
      <path d="M12 12h2" strokeWidth={2.5} />
    </svg>
  );
}

/** Shrine maiden co-host (Himari) — torii + figure. */
export function HimariSummonIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <path d="M6 8V6h12v2" />
      <path d="M4 8h16" />
      <path d="M12 8v3" />
      <circle cx="12" cy="14" r="2.2" />
      <path d="M8.5 20v-1.8a3.5 3.5 0 0 1 7 0V20" />
    </svg>
  );
}

export function ChatIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  );
}

export function SettingsIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6 1.65 1.65 0 0 0 10 3.09V3a2 2 0 0 1 4 0v.09A1.65 1.65 0 0 0 15 4.6a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.13.31.21.65.21 1z" />
    </svg>
  );
}

export function MinimizeIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <line x1="5" x2="19" y1="12" y2="12" />
    </svg>
  );
}

export function CloseIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <line x1="6" x2="18" y1="6" y2="18" />
      <line x1="6" x2="18" y1="18" y2="6" />
    </svg>
  );
}

export function SendIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...props}>
      <line x1="22" x2="11" y1="2" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  );
}

export function VoiceIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} width={14} height={14} {...props}>
      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" x2="12" y1="19" y2="22" />
    </svg>
  );
}
