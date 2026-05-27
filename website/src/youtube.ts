/** YouTube channel + optional featured video IDs (comma-separated in .env). */

export const YOUTUBE_CHANNEL_URL =
  (import.meta.env.VITE_YOUTUBE_CHANNEL_URL || "https://www.youtube.com/@lunawolfsolo").trim();

export const YOUTUBE_CHANNEL_HANDLE =
  (import.meta.env.VITE_YOUTUBE_CHANNEL_HANDLE || "@lunawolfsolo").trim();

export const YOUTUBE_CHANNEL_TITLE =
  (import.meta.env.VITE_YOUTUBE_CHANNEL_TITLE || "Luna wolf").trim();

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

export const YOUTUBE_FEATURED_VIDEO_IDS = parseVideoIds(
  import.meta.env.VITE_YOUTUBE_VIDEO_IDS,
);

export function youtubeWatchUrl(videoId: string): string {
  return `https://www.youtube.com/watch?v=${videoId}`;
}

export function youtubeEmbedUrl(videoId: string): string {
  return `https://www.youtube-nocookie.com/embed/${videoId}?rel=0&modestbranding=1`;
}

export function youtubeThumbnailUrl(videoId: string): string {
  return `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`;
}
