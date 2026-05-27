import type { CastId } from "./characters";
import {
  type CannedBucket,
  REPLIES,
  LUNA_BUCKETS,
  HIMARI_BUCKETS,
  VIKTOR_BUCKETS,
} from "./cannedResponses";

type BucketDef = {
  bucket: CannedBucket;
  keywords: string[];
  weight?: number;
};

const BUCKETS_BY_CAST: Record<CastId, BucketDef[]> = {
  luna: LUNA_BUCKETS,
  himari: HIMARI_BUCKETS,
  viktor: VIKTOR_BUCKETS,
};

const recentByCast: Record<CastId, string[]> = {
  luna: [],
  himari: [],
  viktor: [],
};

const RECENT_CAP = 6;

function normalize(text: string): string {
  return text.toLowerCase().replace(/\s+/g, " ").trim();
}

function scoreBucket(def: BucketDef, msg: string): number {
  if (def.bucket === "fallback") return 0;
  let score = 0;
  for (const kw of def.keywords) {
    if (kw && msg.includes(kw)) {
      score += def.weight ?? 1;
    }
  }
  return score;
}

function pickFromList(cast: CastId, bucket: CannedBucket): string {
  const pool = REPLIES[cast][bucket];
  if (!pool.length) {
    return REPLIES[cast].fallback[0] ?? "…";
  }
  const recent = recentByCast[cast];
  const candidates = pool.filter((line: string) => !recent.includes(line));
  const choice =
    candidates.length > 0
      ? candidates[Math.floor(Math.random() * candidates.length)]
      : pool[Math.floor(Math.random() * pool.length)];
  recent.push(choice);
  if (recent.length > RECENT_CAP) {
    recent.splice(0, recent.length - RECENT_CAP);
  }
  return choice;
}

/** Pick an in-character canned line (no network, no PC). */
export function pickCannedReply(cast: CastId, userText: string): string {
  const msg = normalize(userText);
  if (!msg) {
    return pickFromList(cast, "greeting");
  }

  const defs = BUCKETS_BY_CAST[cast];
  let best: CannedBucket = "fallback";
  let bestScore = 0;

  for (const def of defs) {
    const s = scoreBucket(def, msg);
    if (s > bestScore) {
      bestScore = s;
      best = def.bucket;
    }
  }

  if (bestScore === 0) {
    best = "fallback";
  }

  return pickFromList(cast, best);
}

/** Human-ish delay before showing a canned reply (ms). */
export function cannedReplyDelayMs(text: string): number {
  const base = 500 + Math.min(1400, text.length * 18);
  const jitter = Math.floor(Math.random() * 280);
  return base + jitter;
}
