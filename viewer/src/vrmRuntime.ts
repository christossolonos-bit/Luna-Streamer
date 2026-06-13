import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import type { VRM } from "@pixiv/three-vrm";
import { VRMLoaderPlugin, VRMUtils, VRMHumanBoneName, type VRMExpressionManager } from "@pixiv/three-vrm";
import {
  VRMAnimationLoaderPlugin,
  createVRMAnimationClip,
} from "@pixiv/three-vrm-animation";
import type { VRMAnimation } from "@pixiv/three-vrm-animation";
import { getCohostSoloMode, setCohostSoloMode } from "./cohostScenePrefs";
import { stopViewerTts } from "./viewerTtsPlayer";

function disposeObject(root: THREE.Object3D) {
  root.traverse((obj) => {
    const mesh = obj as THREE.Mesh;
    if (mesh.isMesh) {
      mesh.geometry?.dispose();
      const mats = mesh.material;
      if (Array.isArray(mats)) {
        for (const m of mats) m.dispose();
      } else {
        mats.dispose();
      }
    }
  });
}

export type VrmRuntimeCallbacks = {
  onFps: (fps: number) => void;
  onSceneStatus: (line: string) => void;
  onLoadProgress: (loaded: number, total: number) => void;
};

export type ChromaKeyMode = "off" | "transparent" | "green" | "blue";

export class VrmRuntime {
  private renderer: THREE.WebGLRenderer;
  private scene: THREE.Scene;
  private readonly sceneFog: THREE.FogExp2;
  private floorGrid: THREE.GridHelper;
  private readonly defaultBackground = 0x030308;
  private camera: THREE.PerspectiveCamera;
  private controls: OrbitControls;
  private readonly clock = new THREE.Clock();
  private vrm: VRM | null = null;
  /** Scene root pivot at belly/waist — pitch/yaw rotate here; VRM mesh is offset downward. */
  private lunaPivot: THREE.Group | null = null;
  private cohostVrm: VRM | null = null;
  private cohostPivot: THREE.Group | null = null;
  private himariVrm: VRM | null = null;
  private himariPivot: THREE.Group | null = null;
  private readonly _bellyPivotScratch = new THREE.Vector3();
  private readonly _stageCenterScratch = new THREE.Vector3();
  private himariInScene = false;
  private activeAvatar: "luna" | "cohost" | "himari" = "luna";
  /** Viktor summoned from the dock (on stage for cast / banter). */
  private cohostInScene = false;
  /** Bot banter trio: Luna + Viktor + Himari (not Viktor+Himari dock pair). */
  private castTrioWithLuna = false;
  private static readonly COHOST_SIDE_GAP = 0.18;
  /** At dismiss: co-host root minus Luna root (world), so re-summon can place Viktor without moving Luna. */
  private readonly _savedCohostOffsetFromLuna = new THREE.Vector3();
  private _haveSavedCohostRelativePlacement = false;
  private readonly _savedHimariOffsetFromLuna = new THREE.Vector3();
  private _haveSavedHimariRelativePlacement = false;
  /** Viktor answering Twitch/YouTube while Luna solo — temporary on-screen takeover. */
  private _chatReplyTakeover = false;
  private _himariChatReplyTakeover = false;
  /** Creator panel Luna / Himari / Viktor tab — solo view of who you are talking to. */
  private _creatorPanelFocus: "luna" | "cohost" | "himari" | null = null;
  private static readonly AVATAR_ROT_YAW_PER_PX = 0.008;
  private static readonly AVATAR_ROT_PITCH_PER_PX = 0.005;
  private static readonly AVATAR_ROT_PITCH_MIN = -0.75;
  private static readonly AVATAR_ROT_PITCH_MAX = 0.75;
  private static readonly AVATAR_DRAG_HORIZ_PER_PX = 0.0022;
  private static readonly AVATAR_DRAG_VERT_PER_PX = 0.0022;
  private readonly _layoutBox = new THREE.Box3();
  private readonly raycaster = new THREE.Raycaster();
  private readonly pointerNdc = new THREE.Vector2();
  /** Left-drag on body: yaw (horizontal) + pitch (vertical) for the picked VRM only. */
  private avatarRotateDrag: "luna" | "cohost" | "himari" | null = null;
  /** Avatars manually rotated — skip auto face-camera on these. */
  private readonly manualAvatarFacing = new Set<"luna" | "cohost" | "himari">();
  /** Right-drag reposition (horizontal on floor + vertical in world Y). */
  private avatarDragMove: "luna" | "cohost" | "himari" | null = null;
  private rotatePointerX = 0;
  private rotatePointerY = 0;
  private dragMovePointerX = 0;
  private dragMovePointerY = 0;
  private interactionPointerId: number | null = null;
  private readonly _dragCamRight = new THREE.Vector3();
  private loader = new GLTFLoader();
  private animationLoader = new GLTFLoader();
  private mixer: THREE.AnimationMixer | null = null;
  private action: THREE.AnimationAction | null = null;
  private idleClips: THREE.AnimationClip[] = [];
  private idleClipIndex = 0;
  private idleModeEnabled = false;
  private idleSourceUrls: string[] = [];
  /** Skip leading seconds on Luna VRMA idles (avoids bind/T-pose at t=0). */
  private lunaIdleSkipSec = 2;
  private lunaThinkingClip: THREE.AnimationClip | null = null;
  private lunaThinkingAction: THREE.AnimationAction | null = null;
  private lunaThinkingActive = false;
  private lunaThinkingUrl = "";
  private cohostMixer: THREE.AnimationMixer | null = null;
  private cohostIdleAction: THREE.AnimationAction | null = null;
  private cohostIdleClips: THREE.AnimationClip[] = [];
  private cohostIdleClipIndex = 0;
  private cohostIdleModeEnabled = false;
  private cohostIdleSourceUrls: string[] = [];
  /** Skip leading seconds on co-host VRMA idles (avoids bind/T-pose at t=0). */
  private cohostIdleSkipSec = 2;
  private cohostThinkingAction: THREE.AnimationAction | null = null;
  private cohostThinkingClip: THREE.AnimationClip | null = null;
  private cohostThinkingActive = false;
  private cohostThinkingUrl = "";
  private himariMixer: THREE.AnimationMixer | null = null;
  private himariIdleAction: THREE.AnimationAction | null = null;
  private himariThinkingAction: THREE.AnimationAction | null = null;
  private himariIdleClips: THREE.AnimationClip[] = [];
  private himariThinkingClip: THREE.AnimationClip | null = null;
  private himariIdleClipIndex = 0;
  private himariIdleModeEnabled = false;
  private himariThinkingActive = false;
  private himariIdleSourceUrls: string[] = [];
  private himariThinkingUrl = "";
  private himariIdleSkipSec = 2;
  /** Per-avatar 0–1 phase so idle/thinking VRMA do not stay in sync on stage. */
  private readonly lunaAnimPhase = Math.random();
  private readonly cohostAnimPhase = Math.random();
  private readonly himariAnimPhase = Math.random();
  /** Minimum seconds to play each one-shot idle clip before advancing (avoids rapid clip cycling). */
  private static readonly MIN_IDLE_PLAY_SEC = 2.75;
  /** Blend time for co-host / Himari idle ↔ idle and thinking handoffs. */
  private static readonly ANIM_CROSSFADE_SEC = (() => {
    const raw = import.meta.env.VITE_ANIM_CROSSFADE_SEC;
    if (typeof raw === "string" && raw.trim()) {
      const n = Number(raw);
      if (Number.isFinite(n) && n >= 0) return Math.min(3, n);
    }
    return 1;
  })();
  /** Luna idle transitions (slower default — readable on stream). */
  private static readonly LUNA_ANIM_CROSSFADE_SEC = (() => {
    const raw =
      import.meta.env.VITE_LUNA_ANIM_CROSSFADE_SEC ??
      import.meta.env.VITE_ANIM_CROSSFADE_SEC;
    if (typeof raw === "string" && raw.trim()) {
      const n = Number(raw);
      if (Number.isFinite(n) && n >= 0) return Math.min(4, n);
    }
    return 1.5;
  })();

  private _crossfadeSecFor(avatar: "luna" | "cohost" | "himari"): number {
    // Viktor uses the same idle loop timing as Luna.
    return avatar === "luna" || avatar === "cohost"
      ? VrmRuntime.LUNA_ANIM_CROSSFADE_SEC
      : VrmRuntime.ANIM_CROSSFADE_SEC;
  }

  private _idleActionActive(action: THREE.AnimationAction | null): boolean {
    return !!(
      action?.isRunning() &&
      action.getEffectiveWeight() >= 0.85 &&
      !action.paused
    );
  }
  private raf = 0;
  private lastFrame = performance.now();
  private fpsAccum = 0;
  private fpsFrames = 0;
  private disposed = false;
  private _disposePerfListener: (() => void) | null = null;
  private emotionTimer = 0;
  private talkTimer = 0;
  private talkRaf = 0;
  private talkUntil = 0;
  private _forceSpeaking = false;
  private _visemeUntil = 0;
  private _visemeVowel = "";
  private _visemeAmp = 0;
  /** 0–1 mouth-open drive for jaw bone (set by lip-sync loop). */
  private _lipJawTarget = 0;
  private _lipJawSmoothed = 0;
  private _jawRestQuat: THREE.Quaternion | null = null;
  private readonly _jawWorkEuler = new THREE.Euler();
  private readonly _jawWorkQuat = new THREE.Quaternion();
  /** Max jaw rotation (rad) around local X on normalized jaw — many VRMs open this way. */
  private static readonly JAW_OPEN_MAX_RAD = 0.42;
  /** World point the camera looks at — model bbox center is placed here. */
  private static readonly STAGE_TARGET_Y = 1.05;
  private static readonly STAGE_CAMERA_Z_MIN = 1.7;
  private static readonly STAGE_CAMERA_Z_MAX = 3.6;
  private readonly onCanvasContextMenu = (e: Event) => {
    e.preventDefault();
  };

  private readonly onPointerDown = (e: PointerEvent) => {
    if (e.button === 0) {
      const picked = this._pickAvatar(e.clientX, e.clientY);
      if (!picked) return;
      e.preventDefault();
      e.stopPropagation();
      this.avatarRotateDrag = picked;
      this.manualAvatarFacing.add(picked);
      this.rotatePointerX = e.clientX;
      this.rotatePointerY = e.clientY;
      this.interactionPointerId = e.pointerId;
      this.controls.enabled = false;
      this.canvas.setPointerCapture(e.pointerId);
      return;
    }

    if (e.button === 2) {
      const picked = this._pickAvatar(e.clientX, e.clientY);
      if (!picked) return;
      e.preventDefault();
      e.stopPropagation();
      this.avatarDragMove = picked;
      this.dragMovePointerX = e.clientX;
      this.dragMovePointerY = e.clientY;
      this.interactionPointerId = e.pointerId;
      this.controls.enabled = false;
      this.canvas.setPointerCapture(e.pointerId);
    }
  };

  private readonly onPointerMove = (e: PointerEvent) => {
    if (this.interactionPointerId !== null && e.pointerId !== this.interactionPointerId) {
      return;
    }
    if (this.avatarRotateDrag) {
      const dx = e.clientX - this.rotatePointerX;
      const dy = e.clientY - this.rotatePointerY;
      this.rotatePointerX = e.clientX;
      this.rotatePointerY = e.clientY;
      const root = this._sceneRootForAvatar(this.avatarRotateDrag);
      if (!root) return;
      root.rotation.y -= dx * VrmRuntime.AVATAR_ROT_YAW_PER_PX;
      root.rotation.x = THREE.MathUtils.clamp(
        root.rotation.x - dy * VrmRuntime.AVATAR_ROT_PITCH_PER_PX,
        VrmRuntime.AVATAR_ROT_PITCH_MIN,
        VrmRuntime.AVATAR_ROT_PITCH_MAX,
      );
      root.updateMatrixWorld(true);
      return;
    }

    if (this.avatarDragMove) {
      const dx = e.clientX - this.dragMovePointerX;
      const dy = e.clientY - this.dragMovePointerY;
      this.dragMovePointerX = e.clientX;
      this.dragMovePointerY = e.clientY;
      const root = this._sceneRootForAvatar(this.avatarDragMove);
      if (!root) return;
      this._dragCamRight.setFromMatrixColumn(this.camera.matrixWorld, 0).normalize();
      this._dragCamRight.y = 0;
      if (this._dragCamRight.lengthSq() < 1e-8) {
        this._dragCamRight.set(1, 0, 0);
      } else {
        this._dragCamRight.normalize();
      }
      const h = VrmRuntime.AVATAR_DRAG_HORIZ_PER_PX;
      root.position.x += dx * h * this._dragCamRight.x;
      root.position.z += dx * h * this._dragCamRight.z;
      root.position.y -= dy * VrmRuntime.AVATAR_DRAG_VERT_PER_PX;
      root.updateMatrixWorld(true);
    }
  };

  private readonly onPointerUp = (e: PointerEvent) => {
    if (
      this.interactionPointerId === null ||
      e.pointerId !== this.interactionPointerId
    ) {
      return;
    }
    this.avatarRotateDrag = null;
    this.avatarDragMove = null;
    this.interactionPointerId = null;
    this.controls.enabled = true;
    try {
      this.canvas.releasePointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
  };

  private _trySetExpression(mgr: VRMExpressionManager, names: readonly string[], value: number): boolean {
    for (const name of names) {
      if (mgr.getExpression(name)) {
        mgr.setValue(name, value);
        return true;
      }
    }
    return false;
  }

  private _pivotForAvatar(
    avatar: "luna" | "cohost" | "himari",
  ): THREE.Group | null {
    if (avatar === "luna") return this.lunaPivot;
    if (avatar === "himari") return this.himariPivot;
    return this.cohostPivot;
  }

  private _sceneRootForAvatar(
    avatar: "luna" | "cohost" | "himari",
  ): THREE.Object3D | null {
    return this._pivotForAvatar(avatar);
  }

  /** Local Y of waist so pivot origin sits at the belly (bbox-based — stable across VRM1 rigs). */
  private _computeBellyPivotLocalY(vrm: VRM): number {
    vrm.scene.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(vrm.scene);
    if (!box.isEmpty()) {
      const h = box.max.y - box.min.y;
      if (h > 0.2) {
        return box.min.y + h * 0.48;
      }
    }
    const hips = vrm.humanoid?.getNormalizedBoneNode(VRMHumanBoneName.Hips);
    if (hips) {
      hips.getWorldPosition(this._bellyPivotScratch);
      vrm.scene.worldToLocal(this._bellyPivotScratch);
      if (this._bellyPivotScratch.y > 0.05) {
        const h = box.isEmpty() ? 1.6 : box.max.y - box.min.y;
        const maxWaist = box.isEmpty()
          ? this._bellyPivotScratch.y
          : box.min.y + h * 0.62;
        return Math.min(this._bellyPivotScratch.y, maxWaist);
      }
    }
    return 0.9;
  }

  /** Place model bbox center on the orbit target (screen center). */
  private _applyDefaultStageFraming(pivot: THREE.Group, vrm: VRM): void {
    pivot.position.set(0, 0, 0);
    pivot.rotation.set(0, 0, 0);
    vrm.scene.updateMatrixWorld(true);
    pivot.updateMatrixWorld(true);
    const box = this._layoutBox.setFromObject(vrm.scene);
    if (box.isEmpty()) return;
    const h = box.max.y - box.min.y;
    if (h < 0.25) return;

    box.getCenter(this._stageCenterScratch);
    pivot.position.x = -this._stageCenterScratch.x;
    pivot.position.y = VrmRuntime.STAGE_TARGET_Y - this._stageCenterScratch.y;
    pivot.position.z = -this._stageCenterScratch.z;

    const fovRad = (this.camera.fov * Math.PI) / 180;
    const fitZ = (h * 0.52) / Math.tan(fovRad / 2);
    const z = THREE.MathUtils.clamp(
      fitZ,
      VrmRuntime.STAGE_CAMERA_Z_MIN,
      VrmRuntime.STAGE_CAMERA_Z_MAX,
    );
    this.controls.target.set(0, VrmRuntime.STAGE_TARGET_Y, 0);
    this.camera.position.set(0, VrmRuntime.STAGE_TARGET_Y, z);
    this.controls.update();
  }

  private _createAvatarPivot(vrm: VRM, frameOnStage = true): THREE.Group {
    const pivot = new THREE.Group();
    const bellyY = this._computeBellyPivotLocalY(vrm);
    vrm.scene.position.set(0, -bellyY, 0);
    vrm.scene.rotation.set(0, 0, 0);
    pivot.add(vrm.scene);
    if (frameOnStage) {
      this._applyDefaultStageFraming(pivot, vrm);
    }
    return pivot;
  }

  private _addVrmToScene(vrm: VRM, pivot: THREE.Group) {
    this.scene.add(pivot);
    vrm.scene.updateMatrixWorld(true);
  }

  private activeVrm(): VRM | null {
    if (this.activeAvatar === "cohost") return this.cohostVrm;
    if (this.activeAvatar === "himari") return this.himariVrm;
    return this.vrm;
  }

  private _captureJawRestPose() {
    this._jawRestQuat = null;
    const model = this.activeVrm();
    if (!model) return;
    const jaw = model.humanoid.getNormalizedBoneNode(VRMHumanBoneName.Jaw);
    if (jaw) {
      this._jawRestQuat = jaw.quaternion.clone();
    }
  }

  private _applyJawBeforeHumanoidUpdate() {
    // Called after vrm.update so idle/body animation does not overwrite jaw quaternions.
    // Viktor/Himari: jaw bone rotation fights VRMA neck/head and causes visible shaking.
    if (this.activeAvatar !== "luna") return;
    const model = this.activeVrm();
    if (!model || !this._jawRestQuat) return;
    const jaw = model.humanoid.getNormalizedBoneNode(VRMHumanBoneName.Jaw);
    if (!jaw) return;
    const open = this._lipJawSmoothed;
    if (open <= 0.001) {
      jaw.quaternion.copy(this._jawRestQuat);
      return;
    }
    this._jawWorkEuler.set(open * VrmRuntime.JAW_OPEN_MAX_RAD, 0, 0, "XYZ");
    this._jawWorkQuat.setFromEuler(this._jawWorkEuler);
    jaw.quaternion.copy(this._jawRestQuat).multiply(this._jawWorkQuat);
  }

  /** Re-apply TTS viseme morphs after VRMA + humanoid update (VRMA can stomp blend shapes). */
  private _reapplyActiveLipMorphs() {
    const now = performance.now();
    if (this._visemeUntil > now && this._visemeVowel) {
      this._setVowelExpressions(this._visemeVowel, this._visemeAmp);
    }
  }

  private _animPhase(avatar: "luna" | "cohost" | "himari"): number {
    if (avatar === "cohost") return this.cohostAnimPhase;
    if (avatar === "himari") return this.himariAnimPhase;
    return this.lunaAnimPhase;
  }

  /**
   * Where to begin a one-shot idle (after skipSec bind-pose lead-in).
   * Ensures at least ~85% of the clip (or MIN_IDLE_PLAY_SEC) plays before the end.
   */
  private _idleStartTime(
    clip: THREE.AnimationClip,
    skipSec: number,
    avatar: "luna" | "cohost" | "himari",
  ): number {
    const dur = clip.duration;
    if (dur <= 0) return 0;
    const endPad = 0.05;
    const minPlay = Math.min(
      dur - endPad,
      Math.max(
        Math.max(0.35, VrmRuntime.MIN_IDLE_PLAY_SEC),
        dur * 0.85,
      ),
    );
    const maxStart = Math.max(0, dur - minPlay);
    const skip = Math.min(Math.max(0, skipSec), maxStart);
    const span = Math.max(0, maxStart - skip);
    const t = skip + (this._animPhase(avatar) % 1) * span;
    return Math.min(Math.max(0, t), Math.max(0, dur - endPad));
  }

  /** Ignore mixer ``finished`` if the action has not reached the clip tail yet. */
  private _idleReachedClipEnd(action: THREE.AnimationAction): boolean {
    const clip = action.getClip();
    if (!clip || clip.duration <= 0) return true;
    return action.time >= clip.duration - 0.12;
  }

  /** Offset within a repeating thinking clip (full period — avoids a tiny first cycle then repeat). */
  private _thinkingStartTime(
    clip: THREE.AnimationClip,
    avatar: "luna" | "cohost" | "himari",
  ): number {
    const dur = clip.duration;
    if (dur <= 0) return 0;
    return (this._animPhase(avatar) % 1) * dur;
  }

  private _initialIdleClipIndex(clipCount: number, avatar: "luna" | "cohost" | "himari"): number {
    if (clipCount <= 0) return 0;
    return Math.floor((this._animPhase(avatar) % 1) * clipCount) % clipCount;
  }

  /** Stop a faded-out action after the blend completes (prevents stray ``finished`` events). */
  private _stopActionAfterFade(action: THREE.AnimationAction, fadeSec: number): void {
    if (fadeSec <= 0) {
      action.stop();
      return;
    }
    window.setTimeout(() => {
      action.stop();
    }, fadeSec * 1000 + 90);
  }

  /**
   * Blend idle → idle after ``previous`` finished (held on last frame).
   * ``crossFadeTo`` from a finished LoopOnce action drops weights and flashes bind T-pose;
   * parallel fadeOut / fadeIn keeps at least one clip driving bones.
   */
  private _handoffFromFinishedIdle(
    previous: THREE.AnimationAction,
    next: THREE.AnimationAction,
    fadeSec = VrmRuntime.ANIM_CROSSFADE_SEC,
  ): void {
    if (fadeSec <= 0) {
      previous.stop();
      this._startFreshIdleAction(next);
      return;
    }
    previous.fadeOut(fadeSec);
    next.enabled = true;
    next.paused = false;
    next.play();
    next.fadeIn(fadeSec);
    this._stopActionAfterFade(previous, fadeSec);
    window.setTimeout(() => {
      if (next.getEffectiveWeight() < 0.99) {
        next.setEffectiveWeight(1);
      }
    }, fadeSec * 1000 + 50);
  }

  /** Gentle fade-in when no prior clip (manual VRMA load, etc.). */
  private _fadeInAction(
    action: THREE.AnimationAction,
    fadeSec = VrmRuntime.ANIM_CROSSFADE_SEC,
  ): void {
    action.enabled = true;
    if (fadeSec <= 0) {
      action.setEffectiveWeight(1);
      action.play();
      return;
    }
    action.setEffectiveWeight(0);
    action.play();
    action.fadeIn(fadeSec);
  }

  /** First idle on load — weight must be 1 immediately or VRM stays in bind T-pose. */
  private _startFreshIdleAction(action: THREE.AnimationAction): void {
    action.enabled = true;
    action.setEffectiveWeight(1);
    action.paused = false;
    action.play();
  }

  /** Interrupt blend (e.g. idle ↔ thinking while a clip is still moving). */
  private _crossfadeInterrupt(
    previous: THREE.AnimationAction | null,
    next: THREE.AnimationAction,
    fadeSec = VrmRuntime.ANIM_CROSSFADE_SEC,
  ): void {
    if (!previous || previous === next) {
      this._fadeInAction(next, fadeSec);
      return;
    }
    if (fadeSec <= 0) {
      previous.stop();
      this._startFreshIdleAction(next);
      return;
    }
    previous.fadeOut(fadeSec);
    next.enabled = true;
    next.paused = false;
    next.play();
    next.fadeIn(fadeSec);
    this._stopActionAfterFade(previous, fadeSec);
    window.setTimeout(() => {
      if (next.getEffectiveWeight() < 0.99) {
        next.setEffectiveWeight(1);
      }
    }, fadeSec * 1000 + 50);
  }

  /** Start a one-shot idle clip; holds last frame until the next clip (no bind-pose flash). */
  private _beginIdleClipAction(
    mixer: THREE.AnimationMixer,
    clip: THREE.AnimationClip,
    previous: THREE.AnimationAction | null,
    skipSec: number,
    avatar: "luna" | "cohost" | "himari",
    blend: "finished" | "interrupt" | "fresh" = "fresh",
  ): THREE.AnimationAction {
    const action = mixer.clipAction(clip);
    // reset() snaps to t=0 bind pose; after a finished clip use stop() + seek instead.
    if (blend === "finished") {
      action.stop();
    } else {
      action.reset();
    }
    action.setLoop(THREE.LoopOnce, 1);
    action.clampWhenFinished = true;
    if (clip.duration > 0) {
      action.time = this._idleStartTime(clip, skipSec, avatar);
    }
    const fadeSec = this._crossfadeSecFor(avatar);
    if (previous && previous !== action) {
      if (blend === "finished") {
        this._handoffFromFinishedIdle(previous, action, fadeSec);
      } else {
        this._crossfadeInterrupt(previous, action, fadeSec);
      }
    } else if (previous === action) {
      // mixer.clipAction() returns the same instance for a clip — restart in place.
      this._startFreshIdleAction(action);
    } else {
      this._startFreshIdleAction(action);
    }
    return action;
  }

  private _beginThinkingClipAction(
    mixer: THREE.AnimationMixer,
    clip: THREE.AnimationClip,
    previous: THREE.AnimationAction | null,
    avatar: "luna" | "cohost" | "himari",
  ): THREE.AnimationAction {
    const action = mixer.clipAction(clip);
    action.reset();
    action.setLoop(THREE.LoopRepeat, Infinity);
    if (clip.duration > 0) {
      action.time = this._thinkingStartTime(clip, avatar);
    }
    this._crossfadeInterrupt(previous, action, this._crossfadeSecFor(avatar));
    return action;
  }

  private _orientAvatarTowardCamera(vrm: VRM) {
    const pivot =
      vrm === this.vrm
        ? this.lunaPivot
        : vrm === this.cohostVrm
          ? this.cohostPivot
          : vrm === this.himariVrm
            ? this.himariPivot
            : null;
    if (pivot) {
      this._faceSceneRootTowardCamera(pivot);
      pivot.updateMatrixWorld(true);
    }
  }

  private _resetMouth(model: VRM | null) {
    if (!model?.expressionManager) return;
    const mgr = model.expressionManager;
    for (const aliases of [["aa", "a"], ["ih", "i"], ["ou", "u"], ["ee", "e"], ["oh", "o"]] as const) {
      this._trySetExpression(mgr, aliases, 0);
    }
  }

  private _setPointerNdc(clientX: number, clientY: number) {
    const rect = this.canvas.getBoundingClientRect();
    this.pointerNdc.x = ((clientX - rect.left) / rect.width) * 2 - 1;
    this.pointerNdc.y = -((clientY - rect.top) / rect.height) * 2 + 1;
  }

  private _pickAvatar(clientX: number, clientY: number): "luna" | "cohost" | "himari" | null {
    this._setPointerNdc(clientX, clientY);
    this.raycaster.setFromCamera(this.pointerNdc, this.camera);
    const roots: THREE.Object3D[] = [];
    if (this.vrm?.scene) roots.push(this.vrm.scene);
    if (this.cohostVrm?.scene.visible && this.cohostVrm.scene) {
      roots.push(this.cohostVrm.scene);
    }
    if (this.himariVrm?.scene.visible && this.himariVrm.scene) {
      roots.push(this.himariVrm.scene);
    }
    if (!roots.length) return null;
    const hits = this.raycaster.intersectObjects(roots, true);
    if (!hits.length) return null;
    let node: THREE.Object3D | null = hits[0].object;
    while (node) {
      if (this.cohostVrm && node === this.cohostVrm.scene) return "cohost";
      if (this.himariVrm && node === this.himariVrm.scene) return "himari";
      if (this.vrm && node === this.vrm.scene) return "luna";
      node = node.parent;
    }
    return null;
  }

  private _worldBounds(vrm: VRM, pivot?: THREE.Group | null): THREE.Box3 {
    pivot?.updateMatrixWorld(true);
    vrm.scene.updateMatrixWorld(true);
    return this._layoutBox.setFromObject(vrm.scene);
  }

  private _faceSceneRootTowardCamera(root: THREE.Object3D) {
    const cam = this.camera.position;
    const dx = cam.x - root.position.x;
    const dz = cam.z - root.position.z;
    if (dx * dx + dz * dz < 1e-10) return;
    root.rotation.y = Math.atan2(dx, dz) + Math.PI;
  }

  private _faceVisibleAvatarsTowardCamera() {
    if (this.vrm?.scene.visible && this.lunaPivot && !this.manualAvatarFacing.has("luna")) {
      this._faceSceneRootTowardCamera(this.lunaPivot);
    }
    if (
      this.cohostVrm?.scene.visible &&
      this.cohostPivot &&
      !this.manualAvatarFacing.has("cohost")
    ) {
      this._faceSceneRootTowardCamera(this.cohostPivot);
    }
    if (
      this.himariVrm?.scene.visible &&
      this.himariPivot &&
      !this.manualAvatarFacing.has("himari")
    ) {
      this._faceSceneRootTowardCamera(this.himariPivot);
    }
  }

  private _layoutCastMemberBesideAnchor(
    anchorVrm: VRM,
    anchorPivot: THREE.Group,
    partnerVrm: VRM,
    partnerPivot: THREE.Group,
    side: "left" | "right",
  ): void {
    anchorPivot.updateMatrixWorld(true);
    const anchorBox = this._worldBounds(anchorVrm, anchorPivot).clone();

    partnerPivot.position.copy(anchorPivot.position);
    partnerPivot.rotation.set(0, 0, 0);
    partnerPivot.updateMatrixWorld(true);
    const partnerAtAnchor = this._worldBounds(partnerVrm, partnerPivot).clone();

    const gap = VrmRuntime.COHOST_SIDE_GAP;
    const offsetX =
      side === "right"
        ? anchorBox.max.x + gap - partnerAtAnchor.min.x
        : anchorBox.min.x - gap - partnerAtAnchor.max.x;
    const anchorCenterZ = (anchorBox.min.z + anchorBox.max.z) * 0.5;
    const partnerCenterZ = (partnerAtAnchor.min.z + partnerAtAnchor.max.z) * 0.5;
    const anchorCenterY = (anchorBox.min.y + anchorBox.max.y) * 0.5;
    const partnerCenterY = (partnerAtAnchor.min.y + partnerAtAnchor.max.y) * 0.5;
    const offsetY = anchorCenterY - partnerCenterY;

    partnerPivot.position.x += offsetX;
    partnerPivot.position.y += offsetY;
    partnerPivot.position.z += anchorCenterZ - partnerCenterZ;
    partnerPivot.updateMatrixWorld(true);
  }

  /**
   * Place a co-host beside Luna using the same math as Viktor (right side).
   * Himari uses the mirrored left-side formula with identical Y/Z alignment.
   */
  private _layoutCastMemberBesideLuna(
    partnerVrm: VRM,
    partnerPivot: THREE.Group,
    side: "left" | "right",
  ): void {
    if (!this.vrm || !this.lunaPivot) return;
    this._layoutCastMemberBesideAnchor(
      this.vrm,
      this.lunaPivot,
      partnerVrm,
      partnerPivot,
      side,
    );
  }

  private _layoutCohostBesideLuna() {
    if (!this.cohostVrm || !this.cohostPivot) return;
    this._layoutCastMemberBesideLuna(this.cohostVrm, this.cohostPivot, "right");
  }

  private _layoutHimariBesideLuna() {
    if (!this.himariVrm || !this.himariPivot) return;
    this._layoutCastMemberBesideLuna(this.himariVrm, this.himariPivot, "left");
  }

  private _himariVisibleOnStage(): boolean {
    return !!(
      this.himariVrm?.scene.visible &&
      (this.himariInScene || this._himariChatReplyTakeover)
    );
  }

  private _cohostVisibleOnStage(): boolean {
    return !!(
      this.cohostVrm?.scene.visible &&
      (this.cohostInScene || this._chatReplyTakeover)
    );
  }

  /** Creator chat tab — only one avatar visible; do not let dock/banter layout override. */
  private _applyCreatorPanelVisibility(target: "luna" | "cohost" | "himari"): void {
    if (!this.vrm) return;
    if (target === "luna") {
      if (this.cohostVrm) this.cohostVrm.scene.visible = false;
      if (this.himariVrm) this.himariVrm.scene.visible = false;
      this.vrm.scene.visible = true;
      if (this.lunaPivot) {
        this._applyDefaultStageFraming(this.lunaPivot, this.vrm);
        this._orientAvatarTowardCamera(this.vrm);
      }
      return;
    }
    if (target === "cohost") {
      if (this.vrm) this.vrm.scene.visible = false;
      if (this.himariVrm) this.himariVrm.scene.visible = false;
      if (this.cohostVrm && this.cohostPivot) {
        this.cohostVrm.scene.visible = true;
        this._applyDefaultStageFraming(this.cohostPivot, this.cohostVrm);
        this._orientAvatarTowardCamera(this.cohostVrm);
      }
      return;
    }
    if (this.vrm) this.vrm.scene.visible = false;
    if (this.cohostVrm) this.cohostVrm.scene.visible = false;
    if (this.himariVrm && this.himariPivot) {
      this.himariVrm.scene.visible = true;
      this._applyDefaultStageFraming(this.himariPivot, this.himariVrm);
      this._orientAvatarTowardCamera(this.himariVrm);
    }
  }

  private async _refreshVisibleCastIdle(): Promise<void> {
    if (this.cohostVrm?.scene.visible) {
      await this._ensureCohostIdleForAppearance();
      this._kickIdleMixer(this.cohostVrm, this.cohostMixer);
    }
    if (this.himariVrm?.scene.visible) {
      await this._ensureHimariIdleForAppearance();
      this._kickIdleMixer(this.himariVrm, this.himariMixer);
    }
    if (this.vrm?.scene.visible && this.idleClips.length > 0 && !this.lunaThinkingActive) {
      this._ensureMixerForCurrentVrm();
      if (!this._idleActionActive(this.action)) {
        this.idleModeEnabled = true;
        this._playIdleAt(this.idleClipIndex, null, "fresh");
      }
      this._kickIdleMixer(this.vrm, this.mixer);
    }
  }

  /** Dock cast layout: Luna+Viktor, Luna+Himari, Viktor+Himari (both toggles), or Luna solo. */
  private _syncCastStageLayout(): void {
    if (!this.vrm) return;
    const focus = this._creatorPanelFocus;
    if (focus) {
      this._applyCreatorPanelVisibility(focus);
      void this._refreshVisibleCastIdle();
      return;
    }
    const viktor = this.cohostInScene && !!this.cohostVrm;
    const himari = this.himariInScene && !!this.himariVrm;

    if (!viktor && !himari) {
      this.vrm.scene.visible = true;
      if (this.cohostVrm) this.cohostVrm.scene.visible = false;
      if (this.himariVrm) this.himariVrm.scene.visible = false;
      this._applyDefaultStageFraming(this.lunaPivot!, this.vrm);
      this._orientAvatarTowardCamera(this.vrm);
      this.cb.onSceneStatus("Luna solo");
      return;
    }

    if (viktor && himari) {
      if (this.castTrioWithLuna) {
        this.vrm.scene.visible = true;
        this.himariVrm!.scene.visible = true;
        this.cohostVrm!.scene.visible = true;
        this._applyCastLayoutPositions();
        this.cb.onSceneStatus("Cast on stage: Luna + Viktor + Himari");
        return;
      }
      this.vrm.scene.visible = false;
      this.himariVrm!.scene.visible = true;
      this.cohostVrm!.scene.visible = true;
      this._applyDefaultStageFraming(this.himariPivot!, this.himariVrm!);
      this._orientAvatarTowardCamera(this.himariVrm!);
      this._layoutCastMemberBesideAnchor(
        this.himariVrm!,
        this.himariPivot!,
        this.cohostVrm!,
        this.cohostPivot!,
        "right",
      );
      this._centerCastGroupOnScreen();
      this.cb.onSceneStatus("Co-host duo on stage: Viktor + Himari");
      return;
    }

    this.vrm.scene.visible = true;
    if (viktor && this.cohostVrm) {
      this.cohostVrm.scene.visible = true;
    } else if (this.cohostVrm) {
      this.cohostVrm.scene.visible = false;
    }
    if (himari && this.himariVrm) {
      this.himariVrm.scene.visible = true;
    } else if (this.himariVrm) {
      this.himariVrm.scene.visible = false;
    }

    if (viktor) {
      if (
        this._haveSavedCohostRelativePlacement &&
        this.lunaPivot &&
        this.cohostPivot
      ) {
        this.cohostPivot.position
          .copy(this.lunaPivot.position)
          .add(this._savedCohostOffsetFromLuna);
        this._haveSavedCohostRelativePlacement = false;
      } else {
        this._layoutCohostBesideLuna();
      }
      this._centerCastGroupOnScreen();
      this.cb.onSceneStatus("Cast on stage: Luna + Viktor");
    } else {
      if (
        this._haveSavedHimariRelativePlacement &&
        this.lunaPivot &&
        this.himariPivot
      ) {
        this.himariPivot.position
          .copy(this.lunaPivot.position)
          .add(this._savedHimariOffsetFromLuna);
        this._haveSavedHimariRelativePlacement = false;
      } else {
        this._layoutHimariBesideLuna();
      }
      this._centerCastGroupOnScreen();
      this.cb.onSceneStatus("Cast on stage: Luna + Himari");
    }
    void this._refreshVisibleCastIdle();
  }

  /** Shift every visible cast pivot so the group bbox center sits on the orbit target. */
  private _centerCastGroupOnScreen(): void {
    const union = new THREE.Box3();
    const addVisible = (vrm: VRM | null, visible: boolean) => {
      if (!vrm || !visible) return;
      vrm.scene.updateMatrixWorld(true);
      union.union(this._layoutBox.setFromObject(vrm.scene));
    };
    const lunaVisible = !!(this.vrm?.scene.visible && this.lunaPivot);
    addVisible(this.vrm, lunaVisible);
    addVisible(this.himariVrm, this._himariVisibleOnStage());
    addVisible(this.cohostVrm, this._cohostVisibleOnStage());
    if (union.isEmpty()) return;

    union.getCenter(this._stageCenterScratch);
    const dx = -this._stageCenterScratch.x;
    const dy = VrmRuntime.STAGE_TARGET_Y - this._stageCenterScratch.y;
    const dz = -this._stageCenterScratch.z;

    const shiftPivot = (pivot: THREE.Group | null) => {
      if (!pivot) return;
      pivot.position.x += dx;
      pivot.position.y += dy;
      pivot.position.z += dz;
    };
    if (lunaVisible) {
      shiftPivot(this.lunaPivot);
    }
    if (this._himariVisibleOnStage()) {
      shiftPivot(this.himariPivot);
    }
    if (this._cohostVisibleOnStage()) {
      shiftPivot(this.cohostPivot);
    }

    union.getSize(this._bellyPivotScratch);
    const span = Math.max(this._bellyPivotScratch.x, this._bellyPivotScratch.y);
    const fovRad = (this.camera.fov * Math.PI) / 180;
    const fitZ = (span * 0.58) / Math.tan(fovRad / 2);
    const z = THREE.MathUtils.clamp(
      fitZ,
      VrmRuntime.STAGE_CAMERA_Z_MIN,
      VrmRuntime.STAGE_CAMERA_Z_MAX,
    );
    this.controls.target.set(0, VrmRuntime.STAGE_TARGET_Y, 0);
    this.camera.position.set(0, VrmRuntime.STAGE_TARGET_Y, z);
    this.controls.update();
  }

  /** Himari left, Viktor right of Luna; then center the whole cast on screen. */
  private _applyCastLayoutPositions() {
    if (!this.vrm) return;
    if (this._himariVisibleOnStage()) {
      this._layoutHimariBesideLuna();
    }
    if (this._cohostVisibleOnStage()) {
      this._layoutCohostBesideLuna();
    }
    if (this._himariVisibleOnStage() || this._cohostVisibleOnStage()) {
      this._centerCastGroupOnScreen();
    }
  }

  private _setVowelExpressions(vowel: string, amp: number) {
    const model = this.activeVrm();
    if (!model?.expressionManager) return;
    const mgr = model.expressionManager;
    const a = Math.max(0, Math.min(1, amp));
    const mapping: Record<string, readonly string[]> = {
      a: ["aa", "a"],
      i: ["ih", "i"],
      u: ["ou", "u"],
      e: ["ee", "e"],
      o: ["oh", "o"],
    };
    for (const [k, aliases] of Object.entries(mapping)) {
      this._trySetExpression(mgr, aliases, k === vowel ? a : 0);
    }
    // Jaw bone drive is Luna-only; co-hosts use blend shapes to avoid head shake.
    if (this.activeAvatar === "luna") {
      this._lipJawTarget = a;
    }
  }

  constructor(
    private readonly canvas: HTMLCanvasElement,
    private readonly cb: VrmRuntimeCallbacks,
  ) {
    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
    });
    const dprRaw = import.meta.env.VITE_RENDERER_MAX_DPR;
    let maxDpr = 1.5;
    if (typeof dprRaw === "string" && dprRaw.trim()) {
      const parsed = Number(dprRaw);
      if (Number.isFinite(parsed) && parsed > 0) {
        maxDpr = Math.min(2, Math.max(0.75, parsed));
      }
    }
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, maxDpr));
    const onPerf = (ev: Event) => {
      const d = (ev as CustomEvent<{ rendererMaxDpr?: number }>).detail;
      if (typeof d?.rendererMaxDpr === "number" && Number.isFinite(d.rendererMaxDpr)) {
        const cap = Math.min(2, Math.max(0.75, d.rendererMaxDpr));
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, cap));
        this.resize();
      }
    };
    window.addEventListener("luna-perf-config", onPerf);
    this._disposePerfListener = () => window.removeEventListener("luna-perf-config", onPerf);
    this.renderer.setClearColor(0x000000, 1);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(this.defaultBackground);

    this.sceneFog = new THREE.FogExp2(0x05051a, 0.045);
    this.scene.fog = this.sceneFog;

    this.camera = new THREE.PerspectiveCamera(30, 1, 0.05, 50);
    this.camera.position.set(0, VrmRuntime.STAGE_TARGET_Y, 2.35);

    this.controls = new OrbitControls(this.camera, this.canvas);
    this.controls.target.set(0, VrmRuntime.STAGE_TARGET_Y, 0);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.06;
    this.controls.minDistance = 0.8;
    this.controls.maxDistance = 6;
    this.controls.mouseButtons = {
      LEFT: null as unknown as THREE.MOUSE,
      MIDDLE: THREE.MOUSE.DOLLY,
      RIGHT: THREE.MOUSE.PAN,
    };
    this.controls.update();

    this.canvas.style.userSelect = "none";
    this.canvas.style.setProperty("-webkit-user-select", "none");
    this.canvas.style.touchAction = "none";
    this.canvas.addEventListener("contextmenu", this.onCanvasContextMenu);
    this.canvas.addEventListener("pointerdown", this.onPointerDown, { capture: true });
    this.canvas.addEventListener("pointermove", this.onPointerMove);
    this.canvas.addEventListener("pointerup", this.onPointerUp);
    this.canvas.addEventListener("pointercancel", this.onPointerUp);

    const key = new THREE.DirectionalLight(0xffffff, Math.PI * 0.9);
    key.position.set(1.2, 2.2, 2.5);
    this.scene.add(key);

    const rim = new THREE.DirectionalLight(0x6af0ff, Math.PI * 0.25);
    rim.position.set(-2.5, 0.6, -1.8);
    this.scene.add(rim);

    const fill = new THREE.HemisphereLight(0x88aaff, 0x080810, 0.35);
    this.scene.add(fill);

    this.floorGrid = new THREE.GridHelper(8, 16, 0x1a3a4a, 0x0d1520);
    this.floorGrid.position.y = 0;
    this.scene.add(this.floorGrid);

    this.loader.crossOrigin = "anonymous";
    this.loader.register((parser) => new VRMLoaderPlugin(parser));
    this.animationLoader.crossOrigin = "anonymous";
    this.animationLoader.register((parser) => new VRMAnimationLoaderPlugin(parser));

    this.resize();
    this.loop = this.loop.bind(this);
    this.raf = requestAnimationFrame(this.loop);
    this.cb.onSceneStatus("Initializing scene…");
  }

  /**
   * OBS capture modes: true alpha (no chroma filter), or flat green/blue for classic keying.
   */
  setChromaKeyMode(mode: ChromaKeyMode) {
    if (this.disposed) return;
    const CHROMA_GREEN = 0x00ff00;
    const CHROMA_BLUE = 0x0047bb;

    if (mode === "transparent") {
      this.renderer.setClearColor(0x000000, 0);
      this.scene.background = null;
      this.scene.fog = null;
      this.floorGrid.visible = false;
      return;
    }

    this.renderer.setClearColor(0x000000, 1);

    if (mode === "off") {
      this.scene.background = new THREE.Color(this.defaultBackground);
      this.scene.fog = this.sceneFog;
      this.floorGrid.visible = true;
      return;
    }
    if (mode === "green") {
      this.scene.background = new THREE.Color(CHROMA_GREEN);
    } else {
      this.scene.background = new THREE.Color(CHROMA_BLUE);
    }
    this.scene.fog = null;
    this.floorGrid.visible = false;
  }

  resize() {
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    if (w <= 0 || h <= 0) return;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h, false);
  }

  private loop() {
    if (this.disposed) return;
    this.raf = requestAnimationFrame(this.loop);

    const tabHidden =
      typeof document !== "undefined" && document.hidden;

    const now = performance.now();
    const dt = (now - this.lastFrame) / 1000;
    this.lastFrame = now;

    if (!tabHidden) {
      this.fpsAccum += dt;
      this.fpsFrames += 1;
      if (this.fpsAccum >= 0.5) {
        const fps = this.fpsFrames / this.fpsAccum;
        this.cb.onFps(fps);
        this.fpsAccum = 0;
        this.fpsFrames = 0;
      }
    }

    const delta = this.clock.getDelta();
    // Always advance mixers (paused actions keep their pose). Skipping updates caused T-pose during TTS.
    if (this.mixer) this.mixer.update(delta);
    if (this.cohostMixer) this.cohostMixer.update(delta);
    if (this.himariMixer) this.himariMixer.update(delta);
    if (this.activeVrm()) {
      const lipTarget = this._lipJawTarget;
      this._lipJawSmoothed += (lipTarget - this._lipJawSmoothed) * Math.min(1, delta * 18);
    }
    if (!tabHidden) {
      this.controls.update();
      this._faceVisibleAvatarsTowardCamera();
    }
    if (this.vrm) this.vrm.update(delta);
    if (this.cohostVrm) this.cohostVrm.update(delta);
    if (this.himariVrm) this.himariVrm.update(delta);
    if (!tabHidden && this.activeVrm()) {
      // After VRM/humanoid update so VRMA does not stomp TTS jaw/visemes.
      this._applyJawBeforeHumanoidUpdate();
      if (this._forceSpeaking || performance.now() < this._visemeUntil) {
        this._reapplyActiveLipMorphs();
      }
    }
    if (!tabHidden) {
      this.renderer.render(this.scene, this.camera);
    }
  }

  private _ensureMixerForCurrentVrm() {
    if (!this.vrm) return;
    if (this.mixer) return;
    this.mixer = new THREE.AnimationMixer(this.vrm.scene);
    this.mixer.addEventListener("finished", this._onActionFinished);
  }

  private _onActionFinished = (event: THREE.Event & { action?: THREE.AnimationAction }) => {
    const finished = event.action;
    if (!finished || finished !== this.action) return;
    if (this.lunaThinkingActive || !this.idleModeEnabled || this.idleClips.length === 0) {
      return;
    }
    if (!this._idleReachedClipEnd(finished)) return;
    finished.setEffectiveWeight(1);
    this._playIdleAt(
      this.idleClipIndex % this.idleClips.length,
      finished,
      "finished",
    );
  };

  private _onCohostIdleFinished = (event: THREE.Event & { action?: THREE.AnimationAction }) => {
    const finished = event.action;
    if (!finished || finished !== this.cohostIdleAction) return;
    if (this.cohostThinkingActive || !this.cohostIdleModeEnabled || this.cohostIdleClips.length === 0) {
      return;
    }
    if (!this._idleReachedClipEnd(finished)) return;
    finished.setEffectiveWeight(1);
    this._playCohostIdleAt(
      this.cohostIdleClipIndex % this.cohostIdleClips.length,
      finished,
      "finished",
    );
  };

  private _ensureMixerForCohost() {
    if (!this.cohostVrm) return;
    if (this.cohostMixer) return;
    this.cohostMixer = new THREE.AnimationMixer(this.cohostVrm.scene);
    this.cohostMixer.addEventListener("finished", this._onCohostIdleFinished);
  }

  private _playCohostIdleAt(
    index: number,
    fadeFrom: THREE.AnimationAction | null = null,
    blend: "finished" | "interrupt" | "fresh" = "fresh",
  ) {
    if (this.cohostThinkingActive || !this.cohostMixer || this.cohostIdleClips.length === 0) {
      return;
    }
    const normalized =
      ((index % this.cohostIdleClips.length) + this.cohostIdleClips.length) %
      this.cohostIdleClips.length;
    this.cohostIdleClipIndex = (normalized + 1) % this.cohostIdleClips.length;
    const clip = this.cohostIdleClips[normalized];
    const previous =
      blend === "fresh" ? null : fadeFrom ?? this.cohostIdleAction;
    this.cohostIdleAction = this._beginIdleClipAction(
      this.cohostMixer,
      clip,
      previous,
      this.cohostIdleSkipSec,
      "cohost",
      blend,
    );
  }

  setCohostIdleSkipSec(seconds: number) {
    this.cohostIdleSkipSec = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  }

  async setCohostIdleMotionUrls(urls: string[]): Promise<void> {
    this.cohostIdleSourceUrls = [...urls];
    if (this.cohostIdleAction) {
      this.cohostIdleAction.stop();
      this.cohostIdleAction = null;
    }
    this.cohostIdleClips = [];
    this.cohostIdleClipIndex = 0;
    this.cohostIdleModeEnabled = false;
    if (!this.cohostVrm) return;
    this._ensureMixerForCohost();

    let { clips, failed } = await this._loadIdleClipsForVrm(this.cohostVrm, urls);
    let usedFallback = false;
    if (clips.length === 0 && this.idleSourceUrls.length > 0) {
      const fb = await this._loadIdleClipsForVrm(this.cohostVrm, this.idleSourceUrls);
      clips = fb.clips;
      failed += fb.failed;
      usedFallback = clips.length > 0;
    }

    if (clips.length === 0) {
      this.cb.onSceneStatus(
        failed > 0
          ? `Viktor idle: no clips loaded (${failed} failed) — add VRMA for this VRM in expressions1`
          : "Viktor idle: no motion URLs configured",
      );
      return;
    }

    this.cohostIdleClips = clips;
    if (!this.cohostThinkingActive) {
      this.cohostIdleModeEnabled = true;
      this.cohostIdleClipIndex = this._initialIdleClipIndex(
        this.cohostIdleClips.length,
        "cohost",
      );
      this._playCohostIdleAt(this.cohostIdleClipIndex, null, "fresh");
      this._kickIdleMixer(this.cohostVrm, this.cohostMixer);
    }
    const note = usedFallback ? " (Luna motions retargeted)" : "";
    this.cb.onSceneStatus(
      `Viktor idle loop (${this.cohostIdleClips.length} clip${this.cohostIdleClips.length === 1 ? "" : "s"})${note}`,
    );
  }

  private _stopCohostThinkingMotion() {
    if (this.cohostThinkingAction) {
      this.cohostThinkingAction.stop();
      this.cohostThinkingAction = null;
    }
    this.cohostThinkingActive = false;
  }

  async setCohostThinkingMotionUrl(url: string): Promise<void> {
    this.cohostThinkingUrl = url.trim();
    this.cohostThinkingClip = null;
    if (!this.cohostThinkingUrl || !this.cohostVrm) return;
    try {
      this.cohostThinkingClip = await this._loadVrmaClipForVrm(
        this.cohostVrm,
        this.cohostThinkingUrl,
      );
    } catch {
      this.cohostThinkingClip = null;
    }
  }

  async setCohostThinking(active: boolean): Promise<void> {
    if (!this.cohostVrm) return;
    if (!active) {
      this.cohostThinkingActive = false;
      const fadeFrom = this.cohostThinkingAction;
      this.cohostThinkingAction = null;
      if (this.cohostIdleClips.length > 0) {
        this.cohostIdleModeEnabled = true;
        this._ensureMixerForCohost();
        this._playCohostIdleAt(this.cohostIdleClipIndex, fadeFrom, "interrupt");
        this._kickIdleMixer(this.cohostVrm, this.cohostMixer);
      } else if (fadeFrom) {
        fadeFrom.fadeOut(this._crossfadeSecFor("cohost"));
      }
      return;
    }
    if (!this.cohostThinkingClip && this.cohostThinkingUrl) {
      await this.setCohostThinkingMotionUrl(this.cohostThinkingUrl);
    }
    if (!this.cohostThinkingClip) return;
    this._ensureMixerForCohost();
    this.cohostThinkingActive = true;
    const fadeFrom = this.cohostIdleAction ?? this.cohostThinkingAction;
    this.cohostIdleAction = null;
    this.cohostThinkingAction = this._beginThinkingClipAction(
      this.cohostMixer!,
      this.cohostThinkingClip,
      fadeFrom,
      "cohost",
    );
  }

  private _stopCohostIdleMotion() {
    this._stopCohostThinkingMotion();
    if (this.cohostIdleAction) {
      this.cohostIdleAction.stop();
      this.cohostIdleAction = null;
    }
    if (this.cohostMixer) {
      this.cohostMixer.removeEventListener("finished", this._onCohostIdleFinished);
      this.cohostMixer.stopAllAction();
      this.cohostMixer = null;
    }
    this.cohostIdleClips = [];
    this.cohostIdleClipIndex = 0;
    this.cohostIdleModeEnabled = false;
  }

  private _onHimariIdleFinished = (event: THREE.Event & { action?: THREE.AnimationAction }) => {
    const finished = event.action;
    if (!finished || finished !== this.himariIdleAction) return;
    if (this.himariThinkingActive || !this.himariIdleModeEnabled) return;
    if (this.himariIdleClips.length === 0) return;
    if (!this._idleReachedClipEnd(finished)) return;
    finished.setEffectiveWeight(1);
    this._playHimariIdleAt(
      this.himariIdleClipIndex % this.himariIdleClips.length,
      finished,
      "finished",
    );
  };

  private _ensureMixerForHimari() {
    if (!this.himariVrm) return;
    if (this.himariMixer) return;
    this.himariMixer = new THREE.AnimationMixer(this.himariVrm.scene);
    this.himariMixer.addEventListener("finished", this._onHimariIdleFinished);
  }

  private _playHimariIdleAt(
    index: number,
    fadeFrom: THREE.AnimationAction | null = null,
    blend: "finished" | "interrupt" | "fresh" = "fresh",
  ) {
    if (this.himariThinkingActive || !this.himariMixer || this.himariIdleClips.length === 0) {
      return;
    }
    const normalized =
      ((index % this.himariIdleClips.length) + this.himariIdleClips.length) %
      this.himariIdleClips.length;
    this.himariIdleClipIndex = (normalized + 1) % this.himariIdleClips.length;
    const clip = this.himariIdleClips[normalized];
    const previous =
      blend === "fresh" ? null : fadeFrom ?? this.himariIdleAction;
    this.himariIdleAction = this._beginIdleClipAction(
      this.himariMixer,
      clip,
      previous,
      this.himariIdleSkipSec,
      "himari",
      blend,
    );
  }

  private _stopHimariThinkingMotion() {
    if (this.himariThinkingAction) {
      this.himariThinkingAction.stop();
      this.himariThinkingAction = null;
    }
    this.himariThinkingActive = false;
  }

  setHimariIdleSkipSec(seconds: number) {
    this.himariIdleSkipSec = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  }

  async setHimariIdleMotionUrls(urls: string[]): Promise<void> {
    this.himariIdleSourceUrls = [...urls];
    if (this.himariIdleAction) {
      this.himariIdleAction.stop();
      this.himariIdleAction = null;
    }
    this.himariIdleClips = [];
    this.himariIdleClipIndex = 0;
    this.himariIdleModeEnabled = false;
    if (!this.himariVrm) return;
    this._ensureMixerForHimari();
    const { clips } = await this._loadIdleClipsForVrm(this.himariVrm, urls);
    this.himariIdleClips = clips;
    if (this.himariIdleClips.length > 0 && !this.himariThinkingActive) {
      this.himariIdleModeEnabled = true;
      this.himariIdleClipIndex = this._initialIdleClipIndex(
        this.himariIdleClips.length,
        "himari",
      );
      this._playHimariIdleAt(this.himariIdleClipIndex, null, "fresh");
      this._kickIdleMixer(this.himariVrm, this.himariMixer);
      this.cb.onSceneStatus(
        `Himari idle loop (${this.himariIdleClips.length} clip${this.himariIdleClips.length === 1 ? "" : "s"})`,
      );
    }
  }

  async setHimariThinkingMotionUrl(url: string): Promise<void> {
    this.himariThinkingUrl = url.trim();
    this.himariThinkingClip = null;
    if (!this.himariThinkingUrl || !this.himariVrm) return;
    try {
      this.himariThinkingClip = await this._loadVrmaClipForVrm(
        this.himariVrm,
        this.himariThinkingUrl,
      );
    } catch {
      this.himariThinkingClip = null;
    }
  }

  private _clearHimariAnimations() {
    this._stopHimariThinkingMotion();
    if (this.himariIdleAction) {
      this.himariIdleAction.stop();
      this.himariIdleAction = null;
    }
    if (this.himariMixer) {
      this.himariMixer.removeEventListener("finished", this._onHimariIdleFinished);
      this.himariMixer.stopAllAction();
      this.himariMixer = null;
    }
    this.himariIdleModeEnabled = false;
  }

  async setHimariThinking(active: boolean): Promise<void> {
    if (!this.himariVrm) return;
    if (!this.himariInScene && this._creatorPanelFocus !== "himari") return;
    if (!active) {
      this.himariThinkingActive = false;
      const fadeFrom = this.himariThinkingAction;
      this.himariThinkingAction = null;
      if (this.himariIdleClips.length > 0) {
        this.himariIdleModeEnabled = true;
        this._ensureMixerForHimari();
        this._playHimariIdleAt(this.himariIdleClipIndex, fadeFrom, "interrupt");
      } else if (fadeFrom) {
        fadeFrom.fadeOut(VrmRuntime.ANIM_CROSSFADE_SEC);
      }
      return;
    }
    if (!this.himariThinkingClip && this.himariThinkingUrl) {
      await this.setHimariThinkingMotionUrl(this.himariThinkingUrl);
    }
    if (!this.himariThinkingClip) return;
    this._ensureMixerForHimari();
    this.himariThinkingActive = true;
    const fadeFrom = this.himariIdleAction ?? this.himariThinkingAction;
    this.himariIdleAction = null;
    this.himariThinkingAction = this._beginThinkingClipAction(
      this.himariMixer!,
      this.himariThinkingClip,
      fadeFrom,
      "himari",
    );
  }

  setLunaIdleSkipSec(seconds: number) {
    this.lunaIdleSkipSec = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  }

  private _playIdleAt(
    index: number,
    fadeFrom: THREE.AnimationAction | null = null,
    blend: "finished" | "interrupt" | "fresh" = "fresh",
  ) {
    if (
      this.lunaThinkingActive ||
      !this.mixer ||
      this.idleClips.length === 0 ||
      !this.idleModeEnabled
    ) {
      return;
    }
    const normalized =
      ((index % this.idleClips.length) + this.idleClips.length) %
      this.idleClips.length;
    this.idleClipIndex = (normalized + 1) % this.idleClips.length;
    const clip = this.idleClips[normalized];
    const previous = blend === "fresh" ? null : fadeFrom ?? this.action;
    this.action = this._beginIdleClipAction(
      this.mixer,
      clip,
      previous,
      this.lunaIdleSkipSec,
      "luna",
      blend,
    );
  }

  async loadVrmFile(file: File): Promise<void> {
    this.clearVrm();
    const url = URL.createObjectURL(file);
    try {
      const gltf = await this.loader.loadAsync(url, (e) => {
        if (e.lengthComputable) this.cb.onLoadProgress(e.loaded, e.total);
        else this.cb.onLoadProgress(e.loaded, e.loaded || 1);
      });

      const vrm = gltf.userData.vrm as VRM | undefined;
      if (!vrm) {
        throw new Error("File is not a valid VRM (missing extension data).");
      }

      VRMUtils.removeUnnecessaryVertices(gltf.scene);
      VRMUtils.combineSkeletons(gltf.scene);
      VRMUtils.combineMorphs(vrm);

      vrm.scene.traverse((obj) => {
        obj.frustumCulled = false;
      });

      this.vrm = vrm;
      this.lunaPivot = this._createAvatarPivot(vrm);
      this._addVrmToScene(vrm, this.lunaPivot);
      this._orientAvatarTowardCamera(vrm);
      this._captureJawRestPose();
      this._ensureMixerForCurrentVrm();
      this.cb.onSceneStatus(`Avatar loaded: ${file.name}`);
      if (this.idleSourceUrls.length > 0) {
        await this.setIdleMotionUrls(this.idleSourceUrls);
      }
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  async loadVrmFromUrl(url: string, label = "avatar.vrm"): Promise<void> {
    this.clearVrm();
    const gltf = await this.loader.loadAsync(url, (e) => {
      if (e.lengthComputable) this.cb.onLoadProgress(e.loaded, e.total);
      else this.cb.onLoadProgress(e.loaded, e.loaded || 1);
    });

    const vrm = gltf.userData.vrm as VRM | undefined;
    if (!vrm) {
      throw new Error("File is not a valid VRM (missing extension data).");
    }

    VRMUtils.removeUnnecessaryVertices(gltf.scene);
    VRMUtils.combineSkeletons(gltf.scene);
    VRMUtils.combineMorphs(vrm);

    vrm.scene.traverse((obj) => {
      obj.frustumCulled = false;
    });

    this.vrm = vrm;
    this.lunaPivot = this._createAvatarPivot(vrm);
    this._addVrmToScene(vrm, this.lunaPivot);
    this._orientAvatarTowardCamera(vrm);
    this._captureJawRestPose();
    this._ensureMixerForCurrentVrm();
    this.cb.onSceneStatus(`Avatar loaded: ${label}`);
    if (this.lunaThinkingUrl) {
      await this.setLunaThinkingMotionUrl(this.lunaThinkingUrl);
    }
    if (this.idleSourceUrls.length > 0) {
      await this.setIdleMotionUrls(this.idleSourceUrls);
    }
  }

  async loadVrmaFile(file: File): Promise<void> {
    const url = URL.createObjectURL(file);
    try {
      await this.loadVrmaFromUrl(url, file.name);
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  async loadVrmaFromUrl(url: string, label = "animation"): Promise<void> {
    if (!this.vrm || !this.mixer) {
      throw new Error("Load a VRM avatar first.");
    }
    const clip = await this._loadVrmaClipFromUrl(url);
    const previous = this.action;
    const next = this.mixer.clipAction(clip);
    next.reset();
    next.setLoop(THREE.LoopRepeat, Infinity);
    if (previous && previous !== next) {
      this._crossfadeInterrupt(previous, next);
    } else {
      this._fadeInAction(next);
    }
    this.action = next;
    this.cb.onSceneStatus(`Motion loaded: ${label}`);
  }

  async setIdleMotionUrls(urls: string[]): Promise<void> {
    this.idleSourceUrls = [...urls];
    if (this.action) {
      this.action.stop();
      this.action = null;
    }
    this.idleClips = [];
    this.idleClipIndex = 0;
    this.idleModeEnabled = false;
    if (!this.vrm) return;
    this._ensureMixerForCurrentVrm();
    const { clips } = await this._loadIdleClipsForVrm(this.vrm, urls);
    this.idleClips = clips;
    if (this.idleClips.length > 0 && !this.lunaThinkingActive) {
      this.idleModeEnabled = true;
      this.idleClipIndex = this._initialIdleClipIndex(this.idleClips.length, "luna");
      this._playIdleAt(this.idleClipIndex, null, "fresh");
      this._kickIdleMixer(this.vrm, this.mixer);
      this.cb.onSceneStatus(`Idle motion loop active (${this.idleClips.length} clip${this.idleClips.length === 1 ? "" : "s"})`);
    }
  }

  async setLunaThinkingMotionUrl(url: string): Promise<void> {
    this.lunaThinkingUrl = url.trim();
    this.lunaThinkingClip = null;
    if (!this.lunaThinkingUrl || !this.vrm) return;
    try {
      this.lunaThinkingClip = await this._loadVrmaClipForVrm(
        this.vrm,
        this.lunaThinkingUrl,
      );
    } catch {
      this.lunaThinkingClip = null;
    }
  }

  async setLunaThinking(active: boolean): Promise<void> {
    if (!this.vrm) return;
    if (!active) {
      const fadeFrom = this.lunaThinkingAction;
      this.lunaThinkingAction = null;
      this.lunaThinkingActive = false;
      if (this.idleClips.length > 0) {
        this.idleModeEnabled = true;
        this._ensureMixerForCurrentVrm();
        this._playIdleAt(this.idleClipIndex, fadeFrom, "interrupt");
      } else if (fadeFrom) {
        fadeFrom.fadeOut(this._crossfadeSecFor("luna"));
      }
      return;
    }
    if (!this.lunaThinkingClip && this.lunaThinkingUrl) {
      await this.setLunaThinkingMotionUrl(this.lunaThinkingUrl);
    }
    if (!this.lunaThinkingClip) return;
    this._ensureMixerForCurrentVrm();
    this.lunaThinkingActive = true;
    const fadeFrom = this.action ?? this.lunaThinkingAction;
    this.action = null;
    this.lunaThinkingAction = this._beginThinkingClipAction(
      this.mixer!,
      this.lunaThinkingClip,
      fadeFrom,
      "luna",
    );
  }

  async setAvatarThinking(
    avatar: "luna" | "cohost" | "himari",
    active: boolean,
  ): Promise<void> {
    if (avatar === "luna") {
      await this.setLunaThinking(active);
      return;
    }
    if (avatar === "cohost") {
      await this.setCohostThinking(active);
      return;
    }
    await this.setHimariThinking(active);
  }

  private async _loadVrmaClipForVrm(
    vrm: VRM,
    url: string,
  ): Promise<THREE.AnimationClip> {
    const gltf = await this.animationLoader.loadAsync(url);
    const animations = gltf.userData.vrmAnimations as unknown[] | undefined;
    if (!animations || animations.length === 0) {
      throw new Error("No VRM animation track found in file.");
    }
    const vrmAnimation = animations[0] as VRMAnimation;
    return createVRMAnimationClip(vrmAnimation, vrm);
  }

  private _idleClipUsable(clip: THREE.AnimationClip): boolean {
    return clip.duration > 0.05 && clip.tracks.length > 0;
  }

  /** Load VRMA clips retargeted to a VRM; skip empty or incompatible files. */
  private async _loadIdleClipsForVrm(
    vrm: VRM,
    urls: string[],
  ): Promise<{ clips: THREE.AnimationClip[]; failed: number }> {
    const clips: THREE.AnimationClip[] = [];
    let failed = 0;
    for (const url of urls) {
      try {
        const clip = await this._loadVrmaClipForVrm(vrm, url);
        if (!this._idleClipUsable(clip)) {
          failed += 1;
          continue;
        }
        clips.push(clip);
      } catch {
        failed += 1;
      }
    }
    return { clips, failed };
  }

  private _kickIdleMixer(vrm: VRM | null, mixer: THREE.AnimationMixer | null): void {
    if (!vrm || !mixer) return;
    mixer.update(0);
    vrm.update(0);
  }

  private async _loadVrmaClipFromUrl(url: string): Promise<THREE.AnimationClip> {
    if (!this.vrm) {
      throw new Error("Load a VRM avatar first.");
    }
    return this._loadVrmaClipForVrm(this.vrm, url);
  }

  private clearVrm() {
    if (this.lunaThinkingAction) {
      this.lunaThinkingAction.stop();
      this.lunaThinkingAction = null;
    }
    this.lunaThinkingActive = false;
    if (this.action) {
      this.action.stop();
      this.action = null;
    }
    if (this.mixer) {
      this.mixer.removeEventListener("finished", this._onActionFinished);
      this.mixer.stopAllAction();
      this.mixer = null;
    }
    this.idleClips = [];
    this.idleClipIndex = 0;
    this.idleModeEnabled = false;
    if (!this.vrm) return;
    if (this.lunaPivot) {
      this.lunaPivot.remove(this.vrm.scene);
      this.scene.remove(this.lunaPivot);
      this.lunaPivot = null;
    }
    disposeObject(this.vrm.scene);
    this.vrm = null;
    this.manualAvatarFacing.delete("luna");
    this.activeAvatar = "luna";
    this._jawRestQuat = null;
    this._lipJawTarget = 0;
    this._lipJawSmoothed = 0;
  }

  private clearCohostVrm() {
    if (!this.cohostVrm) return;
    this._stopCohostIdleMotion();
    if (this.cohostPivot) {
      this.cohostPivot.remove(this.cohostVrm.scene);
      this.scene.remove(this.cohostPivot);
      this.cohostPivot = null;
    }
    disposeObject(this.cohostVrm.scene);
    this.cohostVrm = null;
    this.manualAvatarFacing.delete("cohost");
    if (this.activeAvatar === "cohost") {
      this.activeAvatar = "luna";
    }
    if (this.vrm) this.vrm.scene.visible = true;
  }

  isCohostInScene(): boolean {
    return this.cohostInScene && this.cohostVrm !== null;
  }

  isCohostSoloMode(): boolean {
    return getCohostSoloMode();
  }

  async summonCohost(url: string, label = "cohost.vrm"): Promise<void> {
    this._creatorPanelFocus = null;
    setCohostSoloMode(false);
    const trimmed = url.trim();
    if (!trimmed) {
      throw new Error("Co-host VRM URL is missing (check LUNA_COHOST_VRM in .env).");
    }
    if (!this.cohostVrm) {
      await this.loadCohostVrmFromUrl(trimmed, label, { enableLayout: false });
    }
    this.cohostInScene = true;
    this.castTrioWithLuna = false;
    this._syncCastStageLayout();
    this._ensureCohostIdlePlaying();
  }

  isHimariInScene(): boolean {
    return this.himariInScene && this.himariVrm !== null;
  }

  isViktorHimariDuoInScene(): boolean {
    return this.isCohostInScene() && this.isHimariInScene();
  }

  isLunaOnStage(): boolean {
    if (this.isViktorHimariDuoInScene() && !this.castTrioWithLuna) {
      return false;
    }
    return true;
  }

  isCastTrioWithLuna(): boolean {
    return this.castTrioWithLuna;
  }

  async summonViktorHimariDuo(
    viktorUrl: string,
    himariUrl: string,
    viktorLabel = "cohost.vrm",
    himariLabel = "himari.vrm",
  ): Promise<void> {
    this._creatorPanelFocus = null;
    setCohostSoloMode(false);
    const vUrl = viktorUrl.trim();
    const hUrl = himariUrl.trim();
    if (!vUrl) {
      throw new Error("Co-host VRM URL is missing (check LUNA_COHOST_VRM in .env).");
    }
    if (!hUrl) {
      throw new Error("Himari VRM URL is missing (check LUNA_HIMARI_VRM in .env).");
    }
    if (!this.cohostVrm) {
      await this.loadCohostVrmFromUrl(vUrl, viktorLabel, { enableLayout: false });
    }
    if (!this.himariVrm) {
      await this.loadHimariVrmFromUrl(hUrl, himariLabel);
    }
    this.cohostInScene = true;
    this.himariInScene = true;
    this.castTrioWithLuna = false;
    this._syncCastStageLayout();
    await this._ensureCohostIdleForAppearance();
    await this._ensureHimariIdleForAppearance();
  }

  dismissViktorHimariDuo(): void {
    if (this.cohostInScene) {
      this.dismissCohost();
    }
    if (this.himariInScene) {
      this.dismissHimari();
    }
  }

  async summonHimari(url: string, label = "himari.vrm"): Promise<void> {
    this._creatorPanelFocus = null;
    setCohostSoloMode(false);
    const trimmed = url.trim();
    if (!trimmed) {
      throw new Error("Himari VRM URL is missing (check LUNA_HIMARI_VRM in .env).");
    }
    if (!this.himariVrm) {
      await this.loadHimariVrmFromUrl(trimmed, label);
    }
    this.himariInScene = true;
    this.castTrioWithLuna = false;
    this._syncCastStageLayout();
    await this._ensureHimariIdleForAppearance();
  }

  dismissHimari(): void {
    if (!this.himariVrm) return;
    this._clearHimariAnimations();
    if (this.lunaPivot && this.himariPivot) {
      this._savedHimariOffsetFromLuna
        .copy(this.himariPivot.position)
        .sub(this.lunaPivot.position);
      this._haveSavedHimariRelativePlacement = true;
    } else {
      this._haveSavedHimariRelativePlacement = false;
    }
    this.himariInScene = false;
    if (!this.cohostInScene) {
      this.castTrioWithLuna = false;
    }
    if (this.activeAvatar === "himari") {
      this.activeAvatar = "luna";
      this._resetMouth(this.vrm);
      this._resetMouth(this.himariVrm);
      this._captureJawRestPose();
    }
    this._syncCastStageLayout();
  }

  async loadHimariVrmFromUrl(url: string, label = "himari.vrm"): Promise<void> {
    if (this.himariVrm) return;
    const gltf = await this.loader.loadAsync(url);
    const vrm = gltf.userData.vrm as VRM | undefined;
    if (!vrm) {
      throw new Error("Himari file is not a valid VRM.");
    }
    VRMUtils.removeUnnecessaryVertices(gltf.scene);
    VRMUtils.combineSkeletons(gltf.scene);
    VRMUtils.combineMorphs(vrm);
    this._prepareVrmScene(vrm);
    this.himariVrm = vrm;
    this.himariPivot = this._createAvatarPivot(vrm, false);
    this._addVrmToScene(vrm, this.himariPivot);
    vrm.scene.visible = false;
    this.cb.onSceneStatus(`Himari model ready: ${label}`);
    if (this.himariThinkingUrl) {
      await this.setHimariThinkingMotionUrl(this.himariThinkingUrl);
    }
    if (this.himariIdleSourceUrls.length > 0) {
      await this.setHimariIdleMotionUrls(this.himariIdleSourceUrls);
    }
  }

  dismissCohost(): void {
    stopViewerTts();
    window.dispatchEvent(
      new CustomEvent("luna-avatar-speaking", { detail: false }),
    );
    if (!this.cohostVrm) {
      this.cohostInScene = false;
      this.castTrioWithLuna = false;
      this._syncCastStageLayout();
      return;
    }
    if (this.lunaPivot && this.cohostPivot) {
      this._savedCohostOffsetFromLuna
        .copy(this.cohostPivot.position)
        .sub(this.lunaPivot.position);
      this._haveSavedCohostRelativePlacement = true;
    } else {
      this._haveSavedCohostRelativePlacement = false;
    }
    this.avatarRotateDrag = null;
    this.avatarDragMove = null;
    this.interactionPointerId = null;
    this.controls.enabled = true;
    this.cohostInScene = false;
    if (!this.himariInScene) {
      this.castTrioWithLuna = false;
    }
    if (this.activeAvatar === "cohost") {
      this._resetMouth(this.vrm);
      this._resetMouth(this.cohostVrm);
      this._lipJawTarget = 0;
      this._lipJawSmoothed = 0;
      this.activeAvatar = "luna";
      this._captureJawRestPose();
    }
    this._syncCastStageLayout();
  }

  private _prepareVrmScene(vrm: VRM) {
    vrm.scene.traverse((obj) => {
      obj.frustumCulled = false;
    });
    this._orientAvatarTowardCamera(vrm);
  }

  async loadCohostVrmFromUrl(
    url: string,
    label = "cohost.vrm",
    opts?: { enableLayout?: boolean },
  ): Promise<void> {
    if (this.cohostVrm) {
      if (this.cohostIdleSourceUrls.length > 0) {
        await this.setCohostIdleMotionUrls(this.cohostIdleSourceUrls);
      }
      if (opts?.enableLayout !== false) {
        await this.enableDualCohostLayout();
      }
      return;
    }
    const gltf = await this.loader.loadAsync(url);
    const vrm = gltf.userData.vrm as VRM | undefined;
    if (!vrm) {
      throw new Error("Co-host file is not a valid VRM.");
    }
    VRMUtils.removeUnnecessaryVertices(gltf.scene);
    VRMUtils.combineSkeletons(gltf.scene);
    VRMUtils.combineMorphs(vrm);
    this._prepareVrmScene(vrm);
    this.cohostVrm = vrm;
    this.cohostPivot = this._createAvatarPivot(vrm, false);
    this._addVrmToScene(vrm, this.cohostPivot);
    vrm.scene.visible = false;
    this.cb.onSceneStatus(`Co-host model ready: ${label}`);
    if (this.cohostThinkingUrl) {
      await this.setCohostThinkingMotionUrl(this.cohostThinkingUrl);
    }
    if (this.cohostIdleSourceUrls.length > 0) {
      await this.setCohostIdleMotionUrls(this.cohostIdleSourceUrls);
    }
    if (opts?.enableLayout !== false) {
      await this.enableDualCohostLayout();
    }
  }

  /** Bot / bridge: put Viktor on stage (optionally Luna+Viktor+Himari trio). */
  async enableDualCohostLayout(
    vrmUrl?: string,
    opts?: { trioWithLuna?: boolean },
  ): Promise<void> {
    this._creatorPanelFocus = null;
    if (getCohostSoloMode()) {
      return;
    }
    if (!this.cohostVrm && vrmUrl?.trim()) {
      await this.loadCohostVrmFromUrl(vrmUrl.trim(), "cohost.vrm", { enableLayout: false });
    }
    if (!this.cohostVrm) return;

    setCohostSoloMode(false);
    this.cohostInScene = true;
    if (opts?.trioWithLuna) {
      this.castTrioWithLuna = true;
    }
    this._syncCastStageLayout();
    await this._ensureCohostIdleForAppearance();
    this.activeAvatar = "luna";
    this._captureJawRestPose();
  }

  setActiveSpeaker(speaker: "luna" | "cohost" | "himari" | "viktor") {
    const target = speaker === "viktor" ? "cohost" : speaker;
    this._resetMouth(this.vrm);
    this._resetMouth(this.cohostVrm);
    this._resetMouth(this.himariVrm);
    this._lipJawTarget = 0;
    this._lipJawSmoothed = 0;
    this.activeAvatar = target;
    this._captureJawRestPose();
  }

  /**
   * Creator chat tab — show only the selected cast member centered on stage.
   */
  async focusCreatorChatTarget(
    target: "luna" | "cohost" | "himari",
    urls?: { himariVrm?: string; cohostVrm?: string },
  ): Promise<void> {
    this._creatorPanelFocus = target;
    this.setActiveSpeaker(target === "cohost" ? "cohost" : target);

    if (target === "cohost") {
      const url = (urls?.cohostVrm || "").trim();
      if (!this.cohostVrm && url) {
        await this.loadCohostVrmFromUrl(url, "cohost.vrm", { enableLayout: false });
      }
      if (!this.cohostVrm || !this.cohostPivot) {
        this.cb.onSceneStatus("Viktor VRM not loaded — check LUNA_COHOST_VRM in .env");
        return;
      }
    } else if (target === "himari") {
      const himariUrl = (urls?.himariVrm || "").trim();
      if (!this.himariVrm && himariUrl) {
        await this.loadHimariVrmFromUrl(himariUrl, "himari.vrm");
      }
      if (!this.himariVrm || !this.himariPivot) {
        this.cb.onSceneStatus("Himari VRM not loaded — check LUNA_HIMARI_VRM in .env");
        return;
      }
    }

    this._applyCreatorPanelVisibility(target);
    await this._refreshVisibleCastIdle();

    if (target === "luna") {
      this.cb.onSceneStatus("Talking to Luna");
    } else if (target === "cohost") {
      this.cb.onSceneStatus("Talking to Viktor");
    } else {
      this.cb.onSceneStatus("Talking to Himari");
    }
  }

  getCreatorPanelFocus(): "luna" | "cohost" | "himari" | null {
    return this._creatorPanelFocus;
  }

  private _ensureCohostIdlePlaying(): void {
    if (!this.cohostVrm || this.cohostThinkingActive) return;
    if (this.cohostIdleClips.length === 0) return;
    this.cohostIdleModeEnabled = true;
    this._ensureMixerForCohost();
    if (this._idleActionActive(this.cohostIdleAction)) return;
    const idx =
      ((this.cohostIdleClipIndex % this.cohostIdleClips.length) +
        this.cohostIdleClips.length) %
      this.cohostIdleClips.length;
    this._playCohostIdleAt(idx, null, "fresh");
    this._kickIdleMixer(this.cohostVrm, this.cohostMixer);
  }

  private async _ensureCohostIdleForAppearance(): Promise<void> {
    if (this.cohostIdleSourceUrls.length > 0 && this.cohostIdleClips.length === 0) {
      await this.setCohostIdleMotionUrls(this.cohostIdleSourceUrls);
      return;
    }
    this._ensureCohostIdlePlaying();
  }

  private _ensureHimariIdlePlaying(): void {
    if (!this.himariVrm || this.himariThinkingActive) return;
    if (this.himariIdleClips.length === 0) return;
    if (this._idleActionActive(this.himariIdleAction)) return;
    this.himariIdleModeEnabled = true;
    this._ensureMixerForHimari();
    this._playHimariIdleAt(this.himariIdleClipIndex);
  }

  private async _ensureHimariIdleForAppearance(): Promise<void> {
    if (this.himariIdleSourceUrls.length > 0 && this.himariIdleClips.length === 0) {
      await this.setHimariIdleMotionUrls(this.himariIdleSourceUrls);
      return;
    }
    this._ensureHimariIdlePlaying();
  }

  /** Twitch/YouTube @Himari reply — lip-sync even when dismissed from scene. */
  async prepareHimariChatReply(vrmUrl?: string): Promise<void> {
    const url = (vrmUrl || "").trim();
    if (!this.himariVrm && url) {
      await this.loadHimariVrmFromUrl(url, "himari.vrm");
    }
    if (!this.himariVrm) return;

    if (this._creatorPanelFocus === "himari") {
      if (this.vrm) this.vrm.scene.visible = false;
      if (this.cohostVrm) this.cohostVrm.scene.visible = false;
      this.himariVrm.scene.visible = true;
      this._applyDefaultStageFraming(this.himariPivot!, this.himariVrm);
      this._orientAvatarTowardCamera(this.himariVrm);
      this.setActiveSpeaker("himari");
      await this._ensureHimariIdleForAppearance();
      return;
    }

    if (this.himariInScene) {
      if (this.vrm?.scene.visible) {
        this._applyCastLayoutPositions();
      }
      this.setActiveSpeaker("himari");
      await this._ensureHimariIdleForAppearance();
      this.cb.onSceneStatus("Himari (Twitch/YouTube chat reply)");
      return;
    }

    this._himariChatReplyTakeover = true;
    this.himariVrm.scene.visible = true;
    if (this.vrm) {
      this.vrm.scene.visible = true;
      this._applyCastLayoutPositions();
    }
    this._orientAvatarTowardCamera(this.himariVrm);
    this.setActiveSpeaker("himari");
    await this._ensureHimariIdleForAppearance();
    this.cb.onSceneStatus("Himari (Twitch/YouTube chat reply)");
  }

  finishHimariChatReply(): void {
    if (this._himariChatReplyTakeover) {
      this._himariChatReplyTakeover = false;
      if (this.himariVrm) {
        this._resetMouth(this.himariVrm);
        this.himariVrm.scene.visible = false;
      }
      if (this._creatorPanelFocus === "himari") {
        void this.focusCreatorChatTarget("himari");
        return;
      }
      if (this.activeAvatar === "himari") {
        this.activeAvatar = "luna";
        this._captureJawRestPose();
      }
      this.cb.onSceneStatus("Himari dismissed");
      return;
    }
    if (this.himariInScene && this.activeAvatar === "himari") {
      if (this._creatorPanelFocus === "himari") {
        void this.focusCreatorChatTarget("himari");
        return;
      }
      this.setActiveSpeaker("luna");
    }
  }

  /** Twitch/YouTube @Viktor reply — load his VRM and lip-sync even when dismissed from scene. */
  async prepareCohostChatReply(vrmUrl?: string): Promise<void> {
    const url = (vrmUrl || "").trim();
    if (!this.cohostVrm && url) {
      await this.loadCohostVrmFromUrl(url, "cohost.vrm", { enableLayout: false });
    }
    if (!this.cohostVrm) return;

    if (this._creatorPanelFocus === "cohost") {
      if (this.vrm) this.vrm.scene.visible = false;
      if (this.himariVrm) this.himariVrm.scene.visible = false;
      this.cohostVrm.scene.visible = true;
      this._applyDefaultStageFraming(this.cohostPivot!, this.cohostVrm);
      this._orientAvatarTowardCamera(this.cohostVrm);
      this.setActiveSpeaker("cohost");
      await this._ensureCohostIdleForAppearance();
      return;
    }

    if (getCohostSoloMode()) {
      this._chatReplyTakeover = true;
      if (this.vrm) this.vrm.scene.visible = false;
      this.cohostVrm.scene.visible = true;
      if (this.vrm) {
        this.cohostPivot!.position.copy(this.lunaPivot!.position);
      }
      this._orientAvatarTowardCamera(this.cohostVrm);
      this.activeAvatar = "cohost";
      this._captureJawRestPose();
      await this._ensureCohostIdleForAppearance();
      this.cb.onSceneStatus("Viktor (Twitch/YouTube chat reply)");
      return;
    }

    if (this.cohostInScene) {
      this.setActiveSpeaker("cohost");
      await this._ensureCohostIdleForAppearance();
      this.cb.onSceneStatus("Viktor (Twitch/YouTube chat reply)");
      return;
    }

    await this.enableDualCohostLayout(url || undefined);
    this.setActiveSpeaker("cohost");
    await this._ensureCohostIdleForAppearance();
  }

  /** After Viktor chat TTS — hide temporary takeover or hand lip-sync back to Luna. */
  finishCohostChatReply(): void {
    if (this._chatReplyTakeover) {
      this._chatReplyTakeover = false;
      if (this.cohostVrm) {
        this._resetMouth(this.cohostVrm);
        this.cohostVrm.scene.visible = false;
      }
      if (this._creatorPanelFocus === "cohost") {
        void this.focusCreatorChatTarget("cohost");
        return;
      }
      if (this.vrm) {
        this.vrm.scene.visible = true;
        this.activeAvatar = "luna";
        this._captureJawRestPose();
        this.cb.onSceneStatus("Luna solo — summon co-host when you want them back");
      }
      return;
    }
    if (this.cohostInScene && this.activeAvatar === "cohost") {
      if (this._creatorPanelFocus === "cohost") {
        void this.focusCreatorChatTarget("cohost");
        return;
      }
      this.setActiveSpeaker("luna");
    }
  }

  /** @deprecated use enableDualCohostLayout + setActiveSpeaker */
  async setCohostAvatarVisible(visible: boolean, vrmUrl?: string): Promise<void> {
    if (visible) {
      await this.enableDualCohostLayout(vrmUrl);
      this.setActiveSpeaker("cohost");
    } else {
      this.setActiveSpeaker("luna");
    }
  }

  triggerEmotion(raw: string, durationMs?: number) {
    const model = this.activeVrm();
    if (!model?.expressionManager) return;
    const mgr = model.expressionManager;

    const e = (raw || "").toLowerCase();
    const preset =
      e === "happy" || e === "excited"
        ? "happy"
        : e === "sad" || e === "crying"
          ? "sad"
          : e === "angry"
            ? "angry"
            : e === "surprised" || e === "scared" || e === "shout"
              ? "surprised"
              : "relaxed";

    const emotionAliases: Record<string, readonly string[]> = {
      happy: ["happy", "joy"],
      sad: ["sad", "sorrow"],
      angry: ["angry"],
      surprised: ["surprised", "surprise"],
      relaxed: ["relaxed", "neutral"],
    };
    for (const n of ["happy", "sad", "angry", "surprised", "relaxed"]) {
      this._trySetExpression(mgr, emotionAliases[n], n === preset ? 1 : 0);
    }
    const hold = Math.max(
      700,
      Math.min(12_000, durationMs ?? 2600),
    );
    if (this.emotionTimer) window.clearTimeout(this.emotionTimer);
    this.emotionTimer = window.setTimeout(() => {
      for (const n of ["happy", "sad", "angry", "surprised", "relaxed"]) {
        this._trySetExpression(mgr, emotionAliases[n], 0);
      }
      this.emotionTimer = 0;
    }, hold);
  }

  triggerTalk(text: string, holdUntilStop = false) {
    const model = this.activeVrm();
    if (!model) return;
    const mgr = model.expressionManager;

    const clean = (text || "").trim();
    if (!clean) return;
    this._forceSpeaking = holdUntilStop;
    const chars = Math.max(10, Math.min(420, clean.length));
    const ms = Math.max(800, Math.min(5000, chars * 45));
    this.talkUntil = performance.now() + ms;

    if (this.talkTimer) window.clearTimeout(this.talkTimer);
    if (this.talkRaf) cancelAnimationFrame(this.talkRaf);

    const vowelAliases: ReadonlyArray<readonly string[]> = [
      ["aa", "a"],
      ["ih", "i"],
      ["ou", "u"],
      ["ee", "e"],
      ["oh", "o"],
    ];
    const step = () => {
      const now = performance.now();
      if (this._visemeUntil > now) {
        this._setVowelExpressions(this._visemeVowel, this._visemeAmp);
        this.talkRaf = requestAnimationFrame(step);
        return;
      }
      // TTS / "speaking" hold: do not cycle fake vowels between server visemes.
      if (this._forceSpeaking) {
        if (mgr) {
          for (const aliases of vowelAliases) this._trySetExpression(mgr, aliases, 0);
        }
        this._lipJawTarget = 0;
        this.talkRaf = requestAnimationFrame(step);
        return;
      }
      if ((now >= this.talkUntil) || this.disposed) {
        if (mgr) {
          for (const aliases of vowelAliases) this._trySetExpression(mgr, aliases, 0);
        }
        this._lipJawTarget = 0;
        this.talkRaf = 0;
        return;
      }
      const t = now * 0.03;
      const idx = Math.floor(now / 120) % vowelAliases.length;
      const amp = 0.2 + 0.55 * (0.5 + 0.5 * Math.sin(t));
      this._lipJawTarget = Math.min(1, amp * 1.15);
      if (mgr) {
        for (let i = 0; i < vowelAliases.length; i += 1) {
          this._trySetExpression(mgr, vowelAliases[i], i === idx ? amp : 0);
        }
      }
      this.talkRaf = requestAnimationFrame(step);
    };
    this.talkRaf = requestAnimationFrame(step);

    this.talkTimer = window.setTimeout(() => {
      if (this._forceSpeaking) {
        this.talkTimer = 0;
        return;
      }
      if (mgr) {
        for (const aliases of vowelAliases) this._trySetExpression(mgr, aliases, 0);
      }
      this._lipJawTarget = 0;
      this.talkTimer = 0;
    }, ms + 120);
  }

  setSpeaking(active: boolean) {
    if (active) {
      // Keep VRMA idles/thinking running; visemes/jaw are re-applied after vrm.update().
      this.triggerTalk("speaking", true);
      return;
    }
    this._forceSpeaking = false;
    this._visemeUntil = 0;
    this._visemeVowel = "";
    this._visemeAmp = 0;
    this.talkUntil = 0;
    if (this.talkTimer) window.clearTimeout(this.talkTimer);
    if (this.talkRaf) cancelAnimationFrame(this.talkRaf);
    this.talkTimer = 0;
    this.talkRaf = 0;
    this._lipJawTarget = 0;
    const model = this.activeVrm();
    if (!model) return;
    const mgr = model.expressionManager;
    if (mgr) {
      for (const aliases of [["aa", "a"], ["ih", "i"], ["ou", "u"], ["ee", "e"], ["oh", "o"]] as const) {
        this._trySetExpression(mgr, aliases, 0);
      }
    }
  }

  setViseme(vowel: string, intensity = 1, holdMs = 120) {
    const now = performance.now();
    const v = String(vowel || "").toLowerCase();
    const amp = Math.max(0, Math.min(1, Number.isFinite(intensity) ? intensity : 1));
    const hold = Math.max(45, Math.min(400, Number.isFinite(holdMs) ? holdMs : 120));
    if (!["a", "e", "i", "o", "u"].includes(v)) {
      this._visemeVowel = "";
      this._visemeAmp = 0;
      this._visemeUntil = now + hold;
      this._setVowelExpressions("", 0);
      return;
    }
    this._visemeVowel = v;
    this._visemeAmp = amp;
    this._visemeUntil = now + hold;
    this._setVowelExpressions(v, amp);
  }

  dispose() {
    this.disposed = true;
    this._disposePerfListener?.();
    this._disposePerfListener = null;
    cancelAnimationFrame(this.raf);
    if (this.emotionTimer) window.clearTimeout(this.emotionTimer);
    if (this.talkTimer) window.clearTimeout(this.talkTimer);
    if (this.talkRaf) cancelAnimationFrame(this.talkRaf);
    this.canvas.removeEventListener("contextmenu", this.onCanvasContextMenu);
    this.canvas.removeEventListener("pointerdown", this.onPointerDown, { capture: true });
    this.canvas.removeEventListener("pointermove", this.onPointerMove);
    this.canvas.removeEventListener("pointerup", this.onPointerUp);
    this.canvas.removeEventListener("pointercancel", this.onPointerUp);
    this.clearCohostVrm();
    if (this.himariVrm) {
      this._clearHimariAnimations();
      if (this.himariPivot) {
        this.himariPivot.remove(this.himariVrm.scene);
        this.scene.remove(this.himariPivot);
        this.himariPivot = null;
      }
      disposeObject(this.himariVrm.scene);
      this.himariVrm = null;
      this.manualAvatarFacing.delete("himari");
    }
    this.himariInScene = false;
    this.clearVrm();
    this.controls.dispose();
    this.renderer.dispose();
    this.cb.onSceneStatus("Scene disposed.");
  }
}
