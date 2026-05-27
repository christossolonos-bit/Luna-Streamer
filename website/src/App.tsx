import type { CSSProperties } from "react";
import { CAST } from "./characters";
import { DiscordSection } from "./components/DiscordSection";
import { YouTubeSection } from "./components/YouTubeSection";
import { DISCORD_INVITE_URL } from "./youtube";

const FEATURES = [
  {
    title: "Live everywhere",
    body: "Twitch, YouTube Live, TikTok, and Discord — Luna reads the room and answers in character.",
  },
  {
    title: "Full cast on stage",
    body: "Summon Viktor and Himari for banter, trio layouts, and per-character voices in the VRM viewer.",
  },
  {
    title: "Voice & memory",
    body: "Creator mic, TTS replies, community engagement, and themed daily posts in your server.",
  },
  {
    title: "3D presence",
    body: "VRM avatars with expressions, lip-sync, and idle motion — built for OBS and browser sources.",
  },
];

export default function App() {
  const luna = CAST[0];

  return (
    <div className="page">
      <div className="page__stars" aria-hidden />
      <header className="hero">
        <p className="hero__eyebrow">AI stream companion</p>
        <h1 className="hero__title">
          Hi, I&apos;m <span className="hero__name">{luna.name}</span>
        </h1>
        <p className="hero__lead">{luna.intro}</p>
        <div className="hero__traits">
          {luna.traits.map((t) => (
            <span key={t} className="hero__trait">
              {t}
            </span>
          ))}
        </div>
        <div className="hero__actions">
          <a className="hero__btn hero__btn--primary" href="#watch">
            Watch videos
          </a>
          <a
            className="hero__btn hero__btn--discord"
            href={DISCORD_INVITE_URL}
            target="_blank"
            rel="noopener noreferrer"
          >
            Join Discord
          </a>
          <a className="hero__btn hero__btn--ghost" href="#cast">
            Meet the cast
          </a>
        </div>
      </header>

      <YouTubeSection />

      <DiscordSection />

      <section className="cast-row" id="cast" aria-labelledby="cast-heading">
        <h2 id="cast-heading" className="section-title">
          Meet the cast
        </h2>
        <div className="cast-row__grid">
          {CAST.map((c) => (
            <div
              key={c.id}
              className="cast-tile"
              style={{ "--cast-accent": c.accent } as CSSProperties}
            >
              <h3>{c.name}</h3>
              <p className="cast-tile__tag">{c.tagline}</p>
              <p className="cast-tile__intro">{c.intro}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="features" aria-labelledby="features-heading">
        <h2 id="features-heading" className="section-title">
          What Luna can do
        </h2>
        <ul className="features__grid">
          {FEATURES.map((f) => (
            <li key={f.title}>
              <h3>{f.title}</h3>
              <p>{f.body}</p>
            </li>
          ))}
        </ul>
      </section>

      <footer className="footer">
        <p>
          <a href={DISCORD_INVITE_URL} target="_blank" rel="noopener noreferrer">
            Discord
          </a>
          {" · "}
          Luna Streamer
        </p>
      </footer>
    </div>
  );
}
