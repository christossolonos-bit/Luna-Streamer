import {
  YOUTUBE_CHANNEL_HANDLE,
  YOUTUBE_CHANNEL_TITLE,
  YOUTUBE_CHANNEL_URL,
  YOUTUBE_FEATURED_VIDEO_IDS,
  youtubeEmbedUrl,
  youtubeWatchUrl,
} from "../youtube";

export function YouTubeSection() {
  const hasEmbeds = YOUTUBE_FEATURED_VIDEO_IDS.length > 0;

  return (
    <section className="youtube" id="watch" aria-labelledby="watch-heading">
      <h2 id="watch-heading" className="section-title">
        Watch on YouTube
      </h2>
      <p className="youtube__lead">
        Clips and streams from {YOUTUBE_CHANNEL_TITLE} — always on YouTube, no setup
        on your side. Luna doesn&apos;t need to be running on my PC for these.
      </p>

      <div className="youtube__channel-card">
        <div className="youtube__channel-icon" aria-hidden>
          ▶
        </div>
        <div className="youtube__channel-text">
          <h3>{YOUTUBE_CHANNEL_TITLE}</h3>
          <p>{YOUTUBE_CHANNEL_HANDLE}</p>
        </div>
        <a
          className="youtube__cta"
          href={YOUTUBE_CHANNEL_URL}
          target="_blank"
          rel="noopener noreferrer"
        >
          Open channel
        </a>
        <a
          className="youtube__cta youtube__cta--secondary"
          href={`${YOUTUBE_CHANNEL_URL.replace(/\/$/, "")}/videos`}
          target="_blank"
          rel="noopener noreferrer"
        >
          All videos
        </a>
      </div>

      {hasEmbeds ? (
        <div className="youtube__grid">
          {YOUTUBE_FEATURED_VIDEO_IDS.map((id) => (
            <div key={id} className="youtube__embed-wrap">
              <iframe
                src={youtubeEmbedUrl(id)}
                title={`YouTube video ${id}`}
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                allowFullScreen
                loading="lazy"
                referrerPolicy="strict-origin-when-cross-origin"
              />
              <a
                className="youtube__embed-link"
                href={youtubeWatchUrl(id)}
                target="_blank"
                rel="noopener noreferrer"
              >
                Watch on YouTube
              </a>
            </div>
          ))}
        </div>
      ) : (
        <div className="youtube__placeholder">
          <p>
            Subscribe on YouTube for Luna streams, banter with the cast, and VRM
            highlights. New uploads appear on the channel — no Luna bot required to
            watch.
          </p>
          <p className="youtube__placeholder-hint">
            Tip: add video IDs to <code>VITE_YOUTUBE_VIDEO_IDS</code> in{" "}
            <code>website/.env</code> to feature embeds here (comma-separated).
          </p>
        </div>
      )}
    </section>
  );
}
