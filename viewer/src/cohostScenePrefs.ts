/** User chose Luna-only on screen until they summon the co-host again. */

const COHOST_SOLO_STORAGE_KEY = "luna.cohostSoloMode.v1";

let soloMode = readCohostSoloModeStored();

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
