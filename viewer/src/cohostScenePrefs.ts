/** User chose Luna-only on screen until they summon the co-host again. */

const COHOST_SOLO_STORAGE_KEY = "luna.cohostSoloMode.v1";

let soloMode = readCohostSoloModeStored();
let viktorOnStage = false;
let himariOnStage = false;

export function readCohostSoloModeStored(): boolean {
  try {
    return window.localStorage.getItem(COHOST_SOLO_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function getCohostSoloMode(): boolean {
  return soloMode;
}

export function setCohostSoloMode(solo: boolean): void {
  soloMode = solo;
  try {
    window.localStorage.setItem(COHOST_SOLO_STORAGE_KEY, solo ? "1" : "0");
  } catch {
    /* ignore */
  }
}

/** Viewer dock: who is currently summoned (clears solo mode when any co-host is on stage). */
export function setCastStageFlags(viktor: boolean, himari: boolean): void {
  viktorOnStage = viktor;
  himariOnStage = himari;
  if (viktor || himari) {
    setCohostSoloMode(false);
  }
}

export function isViktorOnStage(): boolean {
  return viktorOnStage;
}

export function isHimariOnStage(): boolean {
  return himariOnStage;
}
