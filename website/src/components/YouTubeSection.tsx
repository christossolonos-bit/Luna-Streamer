import { useState } from "react";
import {
  CHANNEL_SHORTS,
  CHANNEL_VIDEOS,
  YOUTUBE_CHANNEL_HANDLE,
  YOUTUBE_CHANNEL_TITLE,
  type ChannelVideo,
  youtubeEmbedUrl,
  youtubeShortsUrl,
  youtubeThumbnailUrl,
  youtubeWatchUrl,
} from "../youtube";

type WatchTab = "videos" | "shorts";

function Playlist({
  items,
  activeId,
  onSelect,
  heading,
  verticalThumb,
}: {
  items: ChannelVideo[];
  activeId: string;
  onSelect: (id: string) => void;
  heading: string;
  verticalThumb?: boolean;
}) {
  return (
    <aside className="youtube__playlist" aria-label={heading}>
      <p className="youtube__playlist-heading">
        {heading} ({items.length})
      </p>
      <ul className="youtube__playlist-list">
        {items.map((item, index) => {
          const selected = item.id === activeId;
          return (
            <li key={item.id}>
              <button
                type="button"
                className={`youtube__playlist-item ${selected ? "youtube__playlist-item--active" : ""}`}
                onClick={() => onSelect(item.id)}
                aria-current={selected ? "true" : undefined}
              >
                <img
                  src={youtubeThumbnailUrl(item.id, verticalThumb)}
                  alt=""
                  className={`youtube__thumb ${verticalThumb ? "youtube__thumb--vertical" : ""}`}
                  loading="lazy"
                />
                <span className="youtube__playlist-meta">
                  <span className="youtube__playlist-index">{index + 1}</span>
                  <span className="youtube__playlist-title">{item.title}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}

export function YouTubeSection() {
  const hasVideos = CHANNEL_VIDEOS.length > 0;
  const hasShorts = CHANNEL_SHORTS.length > 0;
  const defaultTab: WatchTab = hasVideos ? "videos" : "shorts";

  const [tab, setTab] = useState<WatchTab>(defaultTab);
  const [activeVideoId, setActiveVideoId] = useState(CHANNEL_VIDEOS[0]?.id ?? "");
  const [activeShortId, setActiveShortId] = useState(CHANNEL_SHORTS[0]?.id ?? "");

  if (!hasVideos && !hasShorts) {
    return (
      <section className="youtube" id="watch" aria-labelledby="watch-heading">
        <h2 id="watch-heading" className="section-title">
          Watch Luna
        </h2>
        <p className="youtube__lead">Videos will appear here after the channel list is refreshed.</p>
      </section>
    );
  }

  const isShorts = tab === "shorts";
  const items = isShorts ? CHANNEL_SHORTS : CHANNEL_VIDEOS;
  const activeId = isShorts ? activeShortId : activeVideoId;
  const setActiveId = isShorts ? setActiveShortId : setActiveVideoId;
  const active = items.find((v) => v.id === activeId) ?? items[0];
  const activeIndex = items.findIndex((v) => v.id === active.id);

  return (
    <section className="youtube" id="watch" aria-labelledby="watch-heading">
      <h2 id="watch-heading" className="section-title">
        Watch Luna
      </h2>
      <p className="youtube__lead">
        {YOUTUBE_CHANNEL_TITLE} ({YOUTUBE_CHANNEL_HANDLE}) — pick a video or short below.
        Plays right here; no app required.
      </p>

      {hasVideos && hasShorts && (
        <div className="youtube__tabs" role="tablist" aria-label="Watch category">
          <button
            type="button"
            role="tab"
            id="watch-tab-videos"
            aria-selected={!isShorts}
            aria-controls="watch-panel"
            className={`youtube__tab ${!isShorts ? "youtube__tab--active" : ""}`}
            onClick={() => setTab("videos")}
          >
            Videos ({CHANNEL_VIDEOS.length})
          </button>
          <button
            type="button"
            role="tab"
            id="watch-tab-shorts"
            aria-selected={isShorts}
            aria-controls="watch-panel"
            className={`youtube__tab ${isShorts ? "youtube__tab--active" : ""}`}
            onClick={() => setTab("shorts")}
          >
            Shorts ({CHANNEL_SHORTS.length})
          </button>
        </div>
      )}

      <div
        id="watch-panel"
        role="tabpanel"
        aria-labelledby={isShorts ? "watch-tab-shorts" : "watch-tab-videos"}
        className={`youtube__player-layout ${isShorts ? "youtube__player-layout--shorts" : ""}`}
      >
        <div className="youtube__main">
          <div
            className={`youtube__player-wrap ${isShorts ? "youtube__player-wrap--shorts" : ""}`}
          >
            <iframe
              key={active.id}
              src={youtubeEmbedUrl(active.id)}
              title={active.title}
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
              allowFullScreen
              referrerPolicy="strict-origin-when-cross-origin"
            />
          </div>
          <div className="youtube__now-playing">
            <span className="youtube__now-playing-label">Now playing</span>
            <h3 className="youtube__now-playing-title">{active.title}</h3>
            <a
              className="youtube__open-yt"
              href={isShorts ? youtubeShortsUrl(active.id) : youtubeWatchUrl(active.id)}
              target="_blank"
              rel="noopener noreferrer"
            >
              Open on YouTube
            </a>
          </div>
        </div>

        <Playlist
          items={items}
          activeId={active.id}
          onSelect={setActiveId}
          heading={isShorts ? "Shorts" : "Videos"}
          verticalThumb={isShorts}
        />
      </div>

      <div className="youtube__nav">
        <button
          type="button"
          className="youtube__nav-btn"
          disabled={activeIndex <= 0}
          onClick={() => setActiveId(items[activeIndex - 1].id)}
        >
          Previous
        </button>
        <button
          type="button"
          className="youtube__nav-btn"
          disabled={activeIndex >= items.length - 1}
          onClick={() => setActiveId(items[activeIndex + 1].id)}
        >
          Next
        </button>
      </div>
    </section>
  );
}
