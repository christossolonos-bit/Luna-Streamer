/** Canonical face presets the bot may send as ``avatar_emotion`` (VRM 0.x presets). */
export type AvatarFaceExpressionId = "happy" | "sad" | "angry" | "surprised" | "relaxed";

export type AvatarFaceExpression = {
  id: AvatarFaceExpressionId;
  label: string;
  hint: string;
};

export const AVATAR_FACE_EXPRESSIONS: readonly AvatarFaceExpression[] = [
  { id: "relaxed", label: "Neutral / relaxed", hint: "Calm, default resting mood" },
  { id: "happy", label: "Happy", hint: "Joy, thanks, excitement, laughter" },
  { id: "sad", label: "Sad", hint: "Sorry, loss, disappointment, sympathy" },
  { id: "angry", label: "Angry", hint: "Frustration, annoyance, stern tone" },
  { id: "surprised", label: "Surprised", hint: "Wow, shock, fear, sudden news" },
] as const;

export function isAvatarFaceExpressionId(v: string): v is AvatarFaceExpressionId {
  return v === "happy" || v === "sad" || v === "angry" || v === "surprised" || v === "relaxed";
}
