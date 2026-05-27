import { useState } from "react";
import {
  CHANNEL_VIDEOS,
  YOUTUBE_CHANNEL_HANDLE,
  YOUTUBE_CHANNEL_TITLE,
  youtubeEmbedUrl,
  youtubeThumbnailUrl,
  youtubeWatchUrl,
} from "../youtube";

export function YouTubeSection() {
  const videos = CHANNEL_VIDEOS;
  const [activeId, setActiveId] = useState(videos[0]?.id ?? "");

  if (videos.length === 0) {
    return (
      <section className="youtube" id="watch" aria-labelledby="watch-heading">
        <h2 id="watch-heading" className="section-title">
          Watch Luna
        </h2>
        <p className="youtube__lead">Videos will appear here after the channel list is refreshed.</p>
      </section>
    );
  }

  const active = videos.find((v) => v.id === activeId) ?? videos[0];
  const activeIndex = videos.findIndex((v) => v.id === active.id);

  return (
    <section className="youtube" id="watch" aria-labelledby="watch-heading">
      <h2 id="watch-heading" className="section-title">
        Watch Luna
      </h2>
      <p className="youtube__lead">
        {YOUTUBE_CHANNEL_TITLE} ({YOUTUBE_CHANNEL_HANDLE}) — pick a video below or use the
        playlist. Plays right here; no app required.
      </p>

      <div className="youtube__player-layout">
        <div className="youtube__main">
          <div className="youtube__player-wrap">
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
              href={youtubeWatchUrl(active.id)}
              target="_blank"
              rel="noopener noreferrer"
            >
              Open on YouTube
            </a>
          </div>
        </div>

        <aside className="youtube__playlist" aria-label="Video playlist">
          <p className="youtube__playlist-heading">
            Videos ({videos.length})
          </p>
          <ul className="youtube__playlist-list">
            {videos.map((video, index) => {
              const selected = video.id === active.id;
              return (
                <li key={video.id}>
                  <button
                    type="button"
                    className={`youtube__playlist-item ${selected ? "youtube__playlist-item--active" : ""}`}
                    onClick={() => setActiveId(video.id)}
                    aria-current={selected ? "true" : undefined}
                  >
                    <img
                      src={youtubeThumbnailUrl(video.id)}
                      alt=""
                      className="youtube__thumb"
                      loading="lazy"
                    />
                    <span className="youtube__playlist-meta">
                      <span className="youtube__playlist-index">{index + 1}</span>
                      <span className="youtube__playlist-title">{video.title}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </aside>
      </div>

      <div className="youtube__nav">
        <button
          type="button"
          className="youtube__nav-btn"
          disabled={activeIndex <= 0}
          onClick={() => setActiveId(videos[activeIndex - 1].id)}
        >
          Previous
        </button>
        <button
          type="button"
          className="youtube__nav-btn"
          disabled={activeIndex >= videos.length - 1}
          onClick={() => setActiveId(videos[activeIndex + 1].id)}
        >
          Next
        </button>
      </div>
    </section>
  );
}
