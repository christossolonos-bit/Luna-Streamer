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
  replyTo: string;
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
      "Hey — I'm Luna. I'm the one on stream who actually answers back: I chat on Twitch and Discord, banter with my cast, remember the room, and speak my lines out loud. Stick around and I'll show you what I can do.",
    accent: "#c9a6ff",
    glow: "rgba(201, 166, 255, 0.35)",
    traits: ["Live chat & DMs", "Voice replies", "Cast banter", "Community memory"],
    replyTo: "luna",
  },
  {
    id: "himari",
    name: himariName,
    title: "Shrine maiden co-host",
    tagline: "Soft-spoken, curious, quietly fierce.",
    intro:
      `Kon'nichiwa — I'm ${himariName}. I join Luna on stream when the chat calls for something gentler or stranger. Ask me about lore, games, or how your day went; I'll answer in my own voice.`,
    accent: "#ffb4d0",
    glow: "rgba(255, 180, 208, 0.32)",
    traits: ["Dedicated chat lane", "Unique TTS voice", "Creator panel routing", "On-stage banter"],
    replyTo: "himari",
  },
  {
    id: "viktor",
    name: viktorName,
    title: "Vampire gentleman",
    tagline: "Dry humor, old-world charm, zero patience for nonsense.",
    intro:
      `Good evening. ${viktorName} — Luna's… associate. I appear when summoned, trade barbs with the wolf-girl, and answer viewers who address me directly. Try me if you want wit with bite.`,
    accent: "#8ec5ff",
    glow: "rgba(142, 197, 255, 0.28)",
    traits: ["Co-host banter", "Dual & trio layouts", "Mention routing", "Separate voice"],
    replyTo: "viktor",
  },
];

export function castById(id: CastId): CastProfile {
  const row = CAST.find((c) => c.id === id);
  if (!row) throw new Error(`Unknown cast: ${id}`);
  return row;
}

/** Match assistant `user` field from the bridge to a cast lane. */
export function matchAssistantToCast(assistantUser: string): CastId | null {
  const u = assistantUser.trim().toLowerCase();
  if (!u) return null;
  for (const c of CAST) {
    if (u === c.name.toLowerCase()) return c.id;
  }
  if (u.includes("luna")) return "luna";
  if (u.includes(himariName.toLowerCase())) return "himari";
  if (u.includes(viktorName.toLowerCase()) || u.includes("cohost")) return "viktor";
  return null;
}
