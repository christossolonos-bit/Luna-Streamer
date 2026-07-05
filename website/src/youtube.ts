import channelData from "./data/channelVideos.json";

export type ChannelVideo = {
  id: string;
  title: string;
};

export const YOUTUBE_CHANNEL_URL =
  (import.meta.env.VITE_YOUTUBE_CHANNEL_URL || channelData.channel_url).trim();

export const YOUTUBE_CHANNEL_HANDLE =
  (import.meta.env.VITE_YOUTUBE_CHANNEL_HANDLE || "@lunawolfsolo").trim();

export const YOUTUBE_CHANNEL_TITLE =
  (import.meta.env.VITE_YOUTUBE_CHANNEL_TITLE || channelData.channel_title).trim();

export const DISCORD_INVITE_URL =
  (import.meta.env.VITE_DISCORD_INVITE_URL || "https://discord.gg/t3DpY3EP").trim();

export const DISCORD_SERVER_NAME =
  (import.meta.env.VITE_DISCORD_SERVER_NAME || "Luna's Wolf Den").trim();

function parseVideoIds(raw: string | undefined): string[] {
  if (!raw?.trim()) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const part of raw.split(/[\s,]+/)) {
    const id = part.trim();
    if (/^[a-zA-Z0-9_-]{11}$/.test(id) && !seen.has(id)) {
      seen.add(id);
      out.push(id);
    }
  }
  return out;
}

function videosFromEnv(): ChannelVideo[] {
  const ids = parseVideoIds(import.meta.env.VITE_YOUTUBE_VIDEO_IDS);
  return ids.map((id, i) => ({ id, title: `Video ${i + 1}` }));
}

function shortsFromEnv(): ChannelVideo[] {
  const ids = parseVideoIds(import.meta.env.VITE_YOUTUBE_SHORT_IDS);
  return ids.map((id, i) => ({ id, title: `Short ${i + 1}` }));
}

/** Channel uploads baked into the site (refresh via scripts/fetch_youtube_videos.py). */
export const CHANNEL_VIDEOS: ChannelVideo[] =
  videosFromEnv().length > 0
    ? videosFromEnv()
    : (channelData.videos as ChannelVideo[]).filter((v) => v?.id);

/** Channel shorts baked into the site (refresh via scripts/fetch_youtube_videos.py). */
export const CHANNEL_SHORTS: ChannelVideo[] =
  shortsFromEnv().length > 0
    ? shortsFromEnv()
    : ((channelData as { shorts?: ChannelVideo[] }).shorts ?? []).filter((v) => v?.id);

export function youtubeWatchUrl(videoId: string): string {
  return `https://www.youtube.com/watch?v=${videoId}`;
}

export function youtubeShortsUrl(videoId: string): string {
  return `https://www.youtube.com/shorts/${videoId}`;
}

export function youtubeEmbedUrl(videoId: string): string {
  return `https://www.youtube-nocookie.com/embed/${videoId}?rel=0&modestbranding=1&playsinline=1`;
}

export function youtubeThumbnailUrl(videoId: string, vertical = false): string {
  if (vertical) {
    return `https://i.ytimg.com/vi/${videoId}/oardefault.jpg`;
  }
  return `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`;
}
