export type CastId = "luna" | "himari" | "viktor";

export type CastProfile = {
  id: CastId;
  name: string;
  title: string;
  tagline: string;
  intro: string;
  accent: string;
  glow: string;
  traits: string[];
};

const lunaName = (import.meta.env.VITE_LUNA_NAME || "Luna").trim();
const himariName = (import.meta.env.VITE_HIMARI_NAME || "Himari").trim();
const viktorName = (import.meta.env.VITE_VIKTOR_NAME || "Viktor").trim();

export const CAST: CastProfile[] = [
  {
    id: "luna",
    name: lunaName,
    title: "Wolf-girl co-host",
    tagline: "Sharp wit, warm heart, a little chaos.",
    intro:
      "Hey — I'm Luna. I'm the wolf-girl co-host on stream: Twitch, Discord, banter with Viktor and Himari, TTS replies, and a VRM avatar that actually moves. Watch the channel below or catch a live when we're on.",
    accent: "#c9a6ff",
    glow: "rgba(201, 166, 255, 0.35)",
    traits: ["Live chat & DMs", "Voice replies", "Cast banter", "Community memory"],
  },
  {
    id: "himari",
    name: himariName,
    title: "Shrine maiden co-host",
    tagline: "Soft-spoken, curious, quietly fierce.",
    intro:
      `Kon'nichiwa — I'm ${himariName}. I join Luna on stream when chat wants something gentler or nerdier — games, anime, shrine lore, all of it in my own voice.`,
    accent: "#ffb4d0",
    glow: "rgba(255, 180, 208, 0.32)",
    traits: ["Unique TTS voice", "Shrine maiden vibe", "On-stage banter", "Co-host with Luna"],
  },
  {
    id: "viktor",
    name: viktorName,
    title: "Vampire gentleman",
    tagline: "Dry humor, old-world charm, zero patience for nonsense.",
    intro:
      `Good evening. ${viktorName} — Luna's… associate. I appear when summoned, trade barbs with the wolf-girl, and answer viewers who address me on stream. Wit with bite, when you're lucky.`,
    accent: "#8ec5ff",
    glow: "rgba(142, 197, 255, 0.28)",
    traits: ["Co-host banter", "Dual & trio layouts", "Mention routing", "Separate voice"],
  },
];

export function castById(id: CastId): CastProfile {
  const row = CAST.find((c) => c.id === id);
  if (!row) throw new Error(`Unknown cast: ${id}`);
  return row;
}

/** Match assistant `user` field from the bridge to a cast lane. */