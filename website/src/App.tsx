import type { CSSProperties } from "react";
import { CAST } from "./characters";
import { CharacterChat } from "./components/CharacterChat";
import { ChatAvailability } from "./components/ChatAvailability";
import { YouTubeSection } from "./components/YouTubeSection";
import { YOUTUBE_CHANNEL_URL } from "./youtube";
import { useWebsiteChat } from "./useWebsiteChat";

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
  const { conn, chatMode, messages, thinking, sendPrompt, clearCast } =
    useWebsiteChat();

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
            Watch on YouTube
          </a>
          <a
            className="hero__btn hero__btn--ghost"
            href={YOUTUBE_CHANNEL_URL}
            target="_blank"
            rel="noopener noreferrer"
          >
            @lunawolfsolo
          </a>
          <a className="hero__btn hero__btn--ghost" href="#chat">
            Try the cast chat
          </a>
        </div>
      </header>

      <YouTubeSection />

      <section className="cast-row" aria-labelledby="cast-heading">
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

      <section className="chat-section" id="chat" aria-labelledby="chat-heading">
        <h2 id="chat-heading" className="section-title">
          Talk to us
        </h2>
        <ChatAvailability conn={conn} chatMode={chatMode} />
        <p className="chat-section__note">
          Three separate chats — pick Luna, Himari, or Viktor. On GitHub Pages you
          get in-character demo replies; full AI when the stream bridge is connected.
        </p>
        <div className="chat-grid">
          {CAST.map((c) => (
            <CharacterChat
              key={c.id}
              cast={c}
              lines={messages[c.id]}
              thinking={thinking[c.id]}
              conn={conn}
              chatMode={chatMode}
              onSend={(text) => sendPrompt(c.id, text)}
              onClear={() => clearCast(c.id)}
            />
          ))}
        </div>
      </section>

      <footer className="footer">
        <p>
          <a href={YOUTUBE_CHANNEL_URL} target="_blank" rel="noopener noreferrer">
            YouTube @lunawolfsolo
          </a>
          {" · "}
          Luna Streamer
        </p>
      </footer>
    </div>
  );
}
