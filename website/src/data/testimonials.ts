export type Testimonial = {
  quote: string;
  author: string;
  source?: string;
};

/** Community quotes — edit here or move to JSON when you collect more. */
export const TESTIMONIALS: Testimonial[] = [
  {
    quote:
      "Luna actually feels like a co-host, not a bot reading a script. The banter with Viktor had me laughing out loud.",
    author: "Wolf Den regular",
    source: "Discord",
  },
  {
    quote:
      "She remembered something I said days ago in chat. That little bit of continuity makes the stream feel alive.",
    author: "Twitch viewer",
    source: "Twitch",
  },
  {
    quote:
      "The shorts are wild — dramatic, funny, and weirdly emotional. It's not what I expected from an AI streamer.",
    author: "YouTube subscriber",
    source: "YouTube",
  },
  {
    quote:
      "Himari and Luna together are such a good contrast. Soft shrine energy next to chaotic wolf-girl energy just works.",
    author: "Community member",
    source: "Discord",
  },
  {
    quote:
      "Voice replies in VC caught me off guard the first time. Now it's one of my favorite parts of hanging in the server.",
    author: "Discord member",
    source: "Discord",
  },
  {
    quote:
      "The VRM avatar lip-sync and expressions sell it. You can tell a lot of care went into making Luna feel present on stream.",
    author: "Stream regular",
    source: "Twitch",
  },
];
