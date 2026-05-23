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
  private himariInScene = false;
  private activeAvatar: "luna" | "cohost" | "himari" = "luna";
  private dualLayoutEnabled = false;
  private static readonly COHOST_SIDE_GAP = 0.18;
  /** At dismiss: co-host root minus Luna root (world), so re-summon can place Viktor without moving Luna. */
  private readonly _savedCohostOffsetFromLuna = new THREE.Vector3();
  private _haveSavedCohostRelativePlacement = false;
  private readonly _savedHimariOffsetFromLuna = new THREE.Vector3();
  private _haveSavedHimariRelativePlacement = false;
  /** Viktor answering Twitch/YouTube while Luna solo — temporary on-screen takeover. */
  private _chatReplyTakeover = false;
  private _himariChatReplyTakeover = false;
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
  private static readonly MIN_IDLE_PLAY_SEC = 1.75;
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

  /** Local Y of hips/waist so pivot origin sits at the belly, not the feet. */
  private _computeBellyPivotLocalY(vrm: VRM): number {
    vrm.scene.updateMatrixWorld(true);
    const hips = vrm.humanoid?.getNormalizedBoneNode(VRMHumanBoneName.Hips);
    if (hips) {
      hips.getWorldPosition(this._bellyPivotScratch);
      vrm.scene.worldToLocal(this._bellyPivotScratch);
      if (this._bellyPivotScratch.y > 0.05) {
        return this._bellyPivotScratch.y;
      }
    }
    const box = new THREE.Box3().setFromObject(vrm.scene);
    if (!box.isEmpty()) {
      return box.min.y + (box.max.y - box.min.y) * 0.55;
    }
    return 0.9;
  }

  private _createAvatarPivot(vrm: VRM): THREE.Group {
    const pivot = new THREE.Group();
    const bellyY = this._computeBellyPivotLocalY(vrm);
    vrm.scene.position.set(0, -bellyY, 0);
    vrm.scene.rotation.set(0, 0, 0);
    pivot.add(vrm.scene);
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

  /** Stagger idle start; always leave enough time before clip end (phase near 1.0 used to finish instantly). */
  private _idleStartTime(
    clip: THREE.AnimationClip,
    skipSec: number,
    avatar: "luna" | "cohost" | "himari",
  ): number {
    const dur = clip.duration;
    if (dur <= 0) return 0;
    const minPlay = Math.min(
      dur * 0.85,
      Math.max(0.35, VrmRuntime.MIN_IDLE_PLAY_SEC),
    );
    const maxStart = Math.max(0, dur - minPlay);
    const skip = Math.min(Math.max(0, skipSec), maxStart);
    const span = Math.max(0, maxStart - skip);
    const t = skip + (this._animPhase(avatar) % 1) * span;
    return Math.min(Math.max(0, t), Math.max(0, dur - 0.02));
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

  /** Start a one-shot idle clip; holds last frame until the next clip (no bind-pose flash). */
  private _beginIdleClipAction(
    mixer: THREE.AnimationMixer,
    clip: THREE.AnimationClip,
    previous: THREE.AnimationAction | null,
    skipSec: number,
    avatar: "luna" | "cohost" | "himari",
  ): THREE.AnimationAction {
    if (previous) {
      previous.stop();
    }
    const action = mixer.clipAction(clip);
    action.reset();
    action.enabled = true;
    action.setLoop(THREE.LoopOnce, 1);
    action.clampWhenFinished = true;
    if (clip.duration > 0) {
      action.time = this._idleStartTime(clip, skipSec, avatar);
    }
    action.play();
    return action;
  }

  private _beginThinkingClipAction(
    mixer: THREE.AnimationMixer,
    clip: THREE.AnimationClip,
    previous: THREE.AnimationAction | null,
    avatar: "luna" | "cohost" | "himari",
  ): THREE.AnimationAction {
    if (previous) {
      previous.stop();
    }
    const action = mixer.clipAction(clip);
    action.reset();
    action.enabled = true;
    action.setLoop(THREE.LoopRepeat, Infinity);
    if (clip.duration > 0) {
      action.time = this._thinkingStartTime(clip, avatar);
    }
    action.play();
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

  private _worldBounds(vrm: VRM): THREE.Box3 {
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

  /** Places co-host to Luna's side in world space. Does not move Luna (keeps summon/manual placement). */
  private _layoutCohostBesideLuna() {
    if (!this.vrm || !this.cohostVrm || !this.lunaPivot || !this.cohostPivot) return;

    const lunaBox = this._worldBounds(this.vrm).clone();
    this.cohostPivot.position.copy(this.lunaPivot.position);
    this.cohostPivot.rotation.set(0, 0, 0);
    const cohostAtLuna = this._worldBounds(this.cohostVrm).clone();

    const gap = VrmRuntime.COHOST_SIDE_GAP;
    const offsetX = lunaBox.max.x + gap - cohostAtLuna.min.x;
    const lunaCenterZ = (lunaBox.min.z + lunaBox.max.z) * 0.5;
    const cohostCenterZ = (cohostAtLuna.min.z + cohostAtLuna.max.z) * 0.5;
    const offsetY = lunaBox.min.y - cohostAtLuna.min.y;

    this.cohostPivot.position.x += offsetX;
    this.cohostPivot.position.y += offsetY;
    this.cohostPivot.position.z += lunaCenterZ - cohostCenterZ;
  }

  private _layoutHimariBesideLuna() {
    if (!this.vrm || !this.himariVrm || !this.lunaPivot || !this.himariPivot) return;
    const lunaBox = this._worldBounds(this.vrm).clone();
    this.himariPivot.position.copy(this.lunaPivot.position);
    this.himariPivot.rotation.set(0, 0, 0);
    const himariAtLuna = this._worldBounds(this.himariVrm).clone();
    const gap = VrmRuntime.COHOST_SIDE_GAP;
    const offsetX = lunaBox.min.x - gap - himariAtLuna.max.x;
    const lunaCenterZ = (lunaBox.min.z + lunaBox.max.z) * 0.5;
    const himariCenterZ = (himariAtLuna.min.z + himariAtLuna.max.z) * 0.5;
    const offsetY = lunaBox.min.y - himariAtLuna.min.y;
    this.himariPivot.position.x += offsetX;
    this.himariPivot.position.y += offsetY;
    this.himariPivot.position.z += lunaCenterZ - himariCenterZ;
  }

  /** Place every visible cast member (Himari left, Viktor right of Luna). */
  private _applyCastLayoutPositions() {
    if (!this.vrm) return;
    if (this.himariInScene && this.himariVrm?.scene.visible) {
      this._layoutHimariBesideLuna();
    }
    if (this.dualLayoutEnabled && this.cohostVrm?.scene.visible) {
      this._layoutCohostBesideLuna();
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
    this._lipJawTarget = a;
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
    this.camera.position.set(0, 1.35, 2.15);

    this.controls = new OrbitControls(this.camera, this.canvas);
    this.controls.target.set(0, 1, 0);
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

    if (typeof document !== "undefined" && document.hidden) {
      return;
    }

    const now = performance.now();
    const dt = (now - this.lastFrame) / 1000;
    this.lastFrame = now;

    this.fpsAccum += dt;
    this.fpsFrames += 1;
    if (this.fpsAccum >= 0.5) {
      const fps = this.fpsFrames / this.fpsAccum;
      this.cb.onFps(fps);
      this.fpsAccum = 0;
      this.fpsFrames = 0;
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
    this.controls.update();
    this._faceVisibleAvatarsTowardCamera();
    if (this.vrm) this.vrm.update(delta);
    if (this.cohostVrm) this.cohostVrm.update(delta);
    if (this.himariVrm) this.himariVrm.update(delta);
    if (this.activeVrm()) {
      // After VRM/humanoid update so VRMA does not stomp TTS jaw/visemes.
      this._applyJawBeforeHumanoidUpdate();
      if (this._forceSpeaking || performance.now() < this._visemeUntil) {
        this._reapplyActiveLipMorphs();
      }
    }
    this.renderer.render(this.scene, this.camera);
  }

  private _ensureMixerForCurrentVrm() {
    if (!this.vrm) return;
    if (this.mixer) return;
    this.mixer = new THREE.AnimationMixer(this.vrm.scene);
    this.mixer.addEventListener("finished", this._onActionFinished);
  }

  private _onActionFinished = (event: THREE.Event & { action?: THREE.AnimationAction }) => {
    if (event.action !== this.action) return;
    if (this.lunaThinkingActive || !this.idleModeEnabled || this.idleClips.length === 0) {
      return;
    }
    this._playIdleAt(this.idleClipIndex % this.idleClips.length);
  };

  private _onCohostIdleFinished = (event: THREE.Event & { action?: THREE.AnimationAction }) => {
    if (event.action !== this.cohostIdleAction) return;
    if (this.cohostThinkingActive || !this.cohostIdleModeEnabled || this.cohostIdleClips.length === 0) {
      return;
    }
    this._playCohostIdleAt(
      this.cohostIdleClipIndex % this.cohostIdleClips.length,
    );
  };

  private _ensureMixerForCohost() {
    if (!this.cohostVrm) return;
    if (this.cohostMixer) return;
    this.cohostMixer = new THREE.AnimationMixer(this.cohostVrm.scene);
    this.cohostMixer.addEventListener("finished", this._onCohostIdleFinished);
  }

  private _playCohostIdleAt(index: number) {
    if (this.cohostThinkingActive || !this.cohostMixer || this.cohostIdleClips.length === 0) {
      return;
    }
    const normalized =
      ((index % this.cohostIdleClips.length) + this.cohostIdleClips.length) %
      this.cohostIdleClips.length;
    this.cohostIdleClipIndex = (normalized + 1) % this.cohostIdleClips.length;
    const clip = this.cohostIdleClips[normalized];
    this.cohostIdleAction = this._beginIdleClipAction(
      this.cohostMixer,
      clip,
      this.cohostIdleAction,
      this.cohostIdleSkipSec,
      "cohost",
    );
  }

  setCohostIdleSkipSec(seconds: number) {
    this.cohostIdleSkipSec = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  }

  async setCohostIdleMotionUrls(urls: string[]): Promise<void> {
    this.cohostIdleSourceUrls = [...urls];
    this.cohostIdleClips = [];
    this.cohostIdleClipIndex = 0;
    this.cohostIdleModeEnabled = false;
    if (!this.cohostVrm) return;
    this._ensureMixerForCohost();
    for (const url of urls) {
      try {
        const clip = await this._loadVrmaClipForVrm(this.cohostVrm, url);
        this.cohostIdleClips.push(clip);
      } catch {
        /* skip bad files */
      }
    }
    if (this.cohostIdleClips.length > 0) {
      this.cohostIdleModeEnabled = true;
      this.cohostIdleClipIndex = this._initialIdleClipIndex(
        this.cohostIdleClips.length,
        "cohost",
      );
      this._playCohostIdleAt(this.cohostIdleClipIndex);
      this.cb.onSceneStatus(
        `Co-host idle loop (${this.cohostIdleClips.length} clip${this.cohostIdleClips.length === 1 ? "" : "s"})`,
      );
    }
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
      this._stopCohostThinkingMotion();
      if (
        this.cohostIdleClips.length > 0 &&
        (this.dualLayoutEnabled || this._chatReplyTakeover)
      ) {
        this.cohostIdleModeEnabled = true;
        this._ensureMixerForCohost();
        this._playCohostIdleAt(this.cohostIdleClipIndex);
      }
      return;
    }
    if (!this.cohostThinkingClip && this.cohostThinkingUrl) {
      await this.setCohostThinkingMotionUrl(this.cohostThinkingUrl);
    }
    if (!this.cohostThinkingClip) return;
    this._ensureMixerForCohost();
    this.cohostThinkingActive = true;
    if (this.cohostIdleAction) {
      this.cohostIdleAction.stop();
      this.cohostIdleAction = null;
    }
    if (this.cohostThinkingAction) {
      this.cohostThinkingAction.stop();
    }
    this.cohostThinkingAction = this._beginThinkingClipAction(
      this.cohostMixer!,
      this.cohostThinkingClip,
      this.cohostThinkingAction,
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
    if (event.action !== this.himariIdleAction) return;
    if (this.himariThinkingActive || !this.himariIdleModeEnabled) return;
    if (this.himariIdleClips.length === 0) return;
    this._playHimariIdleAt(
      this.himariIdleClipIndex % this.himariIdleClips.length,
    );
  };

  private _ensureMixerForHimari() {
    if (!this.himariVrm) return;
    if (this.himariMixer) return;
    this.himariMixer = new THREE.AnimationMixer(this.himariVrm.scene);
    this.himariMixer.addEventListener("finished", this._onHimariIdleFinished);
  }

  private _playHimariIdleAt(index: number) {
    if (this.himariThinkingActive || !this.himariMixer || this.himariIdleClips.length === 0) {
      return;
    }
    const normalized =
      ((index % this.himariIdleClips.length) + this.himariIdleClips.length) %
      this.himariIdleClips.length;
    this.himariIdleClipIndex = (normalized + 1) % this.himariIdleClips.length;
    const clip = this.himariIdleClips[normalized];
    this.himariIdleAction = this._beginIdleClipAction(
      this.himariMixer,
      clip,
      this.himariIdleAction,
      this.himariIdleSkipSec,
      "himari",
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
    this.himariIdleClips = [];
    this.himariIdleClipIndex = 0;
    this.himariIdleModeEnabled = false;
    if (!this.himariVrm) return;
    this._ensureMixerForHimari();
    for (const url of urls) {
      try {
        const clip = await this._loadVrmaClipForVrm(this.himariVrm, url);
        this.himariIdleClips.push(clip);
      } catch {
        /* skip bad files */
      }
    }
    if (this.himariIdleClips.length > 0 && !this.himariThinkingActive) {
      this.himariIdleModeEnabled = true;
      this.himariIdleClipIndex = this._initialIdleClipIndex(
        this.himariIdleClips.length,
        "himari",
      );
      this._playHimariIdleAt(this.himariIdleClipIndex);
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
    if (!this.himariVrm || !this.himariInScene) return;
    if (!active) {
      this._stopHimariThinkingMotion();
      if (this.himariIdleClips.length > 0) {
        this.himariIdleModeEnabled = true;
        this._ensureMixerForHimari();
        this._playHimariIdleAt(this.himariIdleClipIndex);
      }
      return;
    }
    if (!this.himariThinkingClip && this.himariThinkingUrl) {
      await this.setHimariThinkingMotionUrl(this.himariThinkingUrl);
    }
    if (!this.himariThinkingClip) return;
    this._ensureMixerForHimari();
    this.himariThinkingActive = true;
    if (this.himariIdleAction) {
      this.himariIdleAction.stop();
      this.himariIdleAction = null;
    }
    if (this.himariThinkingAction) {
      this.himariThinkingAction.stop();
    }
    this.himariThinkingAction = this._beginThinkingClipAction(
      this.himariMixer!,
      this.himariThinkingClip,
      this.himariThinkingAction,
      "himari",
    );
  }

  setLunaIdleSkipSec(seconds: number) {
    this.lunaIdleSkipSec = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  }

  private _playIdleAt(index: number) {
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
    this.action = this._beginIdleClipAction(
      this.mixer,
      clip,
      this.action,
      this.lunaIdleSkipSec,
      "luna",
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
    if (this.action) {
      this.action.stop();
      this.action = null;
    }
    this.action = this.mixer.clipAction(clip);
    this.action.reset();
    this.action.setLoop(THREE.LoopRepeat, Infinity);
    this.action.play();
    this.cb.onSceneStatus(`Motion loaded: ${label}`);
  }

  async setIdleMotionUrls(urls: string[]): Promise<void> {
    this.idleSourceUrls = [...urls];
    this.idleClips = [];
    this.idleClipIndex = 0;
    this.idleModeEnabled = false;
    if (!this.vrm) return;
    this._ensureMixerForCurrentVrm();
    for (const url of urls) {
      try {
        const clip = await this._loadVrmaClipForVrm(this.vrm, url);
        this.idleClips.push(clip);
      } catch {
        // ignore invalid files and continue with remaining clips
      }
    }
    if (this.idleClips.length > 0 && !this.lunaThinkingActive) {
      this.idleModeEnabled = true;
      this.idleClipIndex = this._initialIdleClipIndex(this.idleClips.length, "luna");
      this._playIdleAt(this.idleClipIndex);
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
      if (this.lunaThinkingAction) {
        this.lunaThinkingAction.stop();
        this.lunaThinkingAction = null;
      }
      this.lunaThinkingActive = false;
      if (this.idleClips.length > 0) {
        this.idleModeEnabled = true;
        this._ensureMixerForCurrentVrm();
        this._playIdleAt(this.idleClipIndex);
      }
      return;
    }
    if (!this.lunaThinkingClip && this.lunaThinkingUrl) {
      await this.setLunaThinkingMotionUrl(this.lunaThinkingUrl);
    }
    if (!this.lunaThinkingClip) return;
    this._ensureMixerForCurrentVrm();
    this.lunaThinkingActive = true;
    if (this.action) {
      this.action.stop();
      this.action = null;
    }
    if (this.lunaThinkingAction) {
      this.lunaThinkingAction.stop();
    }
    this.lunaThinkingAction = this._beginThinkingClipAction(
      this.mixer!,
      this.lunaThinkingClip,
      this.lunaThinkingAction,
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
    return this.cohostVrm !== null && this.dualLayoutEnabled;
  }

  isCohostSoloMode(): boolean {
    return getCohostSoloMode();
  }

  async summonCohost(url: string, label = "cohost.vrm"): Promise<void> {
    setCohostSoloMode(false);
    const trimmed = url.trim();
    if (!trimmed) {
      throw new Error("Co-host VRM URL is missing (check LUNA_COHOST_VRM in .env).");
    }
    if (!this.cohostVrm) {
      await this.loadCohostVrmFromUrl(trimmed, label, { enableLayout: false });
    }
    await this.enableDualCohostLayout();
  }

  isHimariInScene(): boolean {
    return this.himariInScene && this.himariVrm !== null;
  }

  async summonHimari(url: string, label = "himari.vrm"): Promise<void> {
    const trimmed = url.trim();
    if (!trimmed) {
      throw new Error("Himari VRM URL is missing (check LUNA_HIMARI_VRM in .env).");
    }
    if (!this.himariVrm) {
      await this.loadHimariVrmFromUrl(trimmed, label);
    }
    this.himariInScene = true;
    this.himariVrm!.scene.visible = true;
    if (this.vrm) {
      if (
        this._haveSavedHimariRelativePlacement &&
        this.himariVrm
      ) {
        this.himariPivot!.position
          .copy(this.lunaPivot!.position)
          .add(this._savedHimariOffsetFromLuna);
        this._haveSavedHimariRelativePlacement = false;
      } else {
        this._applyCastLayoutPositions();
      }
    }
    this.cb.onSceneStatus(
      `${label} on stage · left-drag on body: rotate · right-drag on body: move`,
    );
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
    this.himariVrm.scene.visible = false;
    if (this.activeAvatar === "himari") {
      this.activeAvatar = "luna";
      this._resetMouth(this.vrm);
      this._resetMouth(this.himariVrm);
      this._captureJawRestPose();
    }
    this.cb.onSceneStatus("Himari dismissed");
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
    this.himariPivot = this._createAvatarPivot(vrm);
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
    setCohostSoloMode(true);
    stopViewerTts();
    window.dispatchEvent(
      new CustomEvent("luna-avatar-speaking", { detail: false }),
    );
    if (!this.cohostVrm) return;
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
    this.dualLayoutEnabled = false;
    this.clearCohostVrm();
    this._resetMouth(this.vrm);
    this._lipJawTarget = 0;
    this._lipJawSmoothed = 0;
    this.activeAvatar = "luna";
    this._captureJawRestPose();
    this.cb.onSceneStatus("Luna solo — summon co-host when you want them back");
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
    this.cohostPivot = this._createAvatarPivot(vrm);
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

  /** Both avatars on screen; lip-sync follows ``setActiveSpeaker`` only. */
  async enableDualCohostLayout(vrmUrl?: string): Promise<void> {
    if (getCohostSoloMode()) {
      return;
    }
    if (!this.cohostVrm && vrmUrl?.trim()) {
      await this.loadCohostVrmFromUrl(vrmUrl.trim(), "cohost.vrm", { enableLayout: false });
    }
    if (!this.cohostVrm) return;

    const alreadySideBySide = this.dualLayoutEnabled;
    this.dualLayoutEnabled = true;
    if (this.vrm) this.vrm.scene.visible = true;
    this.cohostVrm.scene.visible = true;

    if (alreadySideBySide) {
      /* Bot may resend dual_layout while both are already up — keep user-placed roots. */
    } else if (this._haveSavedCohostRelativePlacement && this.vrm && this.cohostVrm) {
      /* Re-summon after dismiss: keep Luna where she is; restore Viktor relative to her. */
      this.cohostPivot!.position
        .copy(this.lunaPivot!.position)
        .add(this._savedCohostOffsetFromLuna);
      this._haveSavedCohostRelativePlacement = false;
    } else {
      this._applyCastLayoutPositions();
    }

    this.activeAvatar = "luna";
    this._captureJawRestPose();
    this.cb.onSceneStatus(
      "Cast on stage · left-drag on a body: rotate · right-drag on a body: move · right-drag empty: pan · scroll: zoom",
    );
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

  /** Twitch/YouTube @Himari reply — lip-sync even when dismissed from scene. */
  async prepareHimariChatReply(vrmUrl?: string): Promise<void> {
    const url = (vrmUrl || "").trim();
    if (!this.himariVrm && url) {
      await this.loadHimariVrmFromUrl(url, "himari.vrm");
    }
    if (!this.himariVrm) return;

    if (this.himariInScene) {
      this.setActiveSpeaker("himari");
      this.cb.onSceneStatus("Himari (Twitch/YouTube chat reply)");
      return;
    }

    this._himariChatReplyTakeover = true;
    this.himariVrm.scene.visible = true;
    if (this.vrm) {
      this._applyCastLayoutPositions();
    }
    this._orientAvatarTowardCamera(this.himariVrm);
    this.setActiveSpeaker("himari");
    this.cb.onSceneStatus("Himari (Twitch/YouTube chat reply)");
  }

  finishHimariChatReply(): void {
    if (this._himariChatReplyTakeover) {
      this._himariChatReplyTakeover = false;
      if (this.himariVrm) {
        this._resetMouth(this.himariVrm);
        this.himariVrm.scene.visible = false;
      }
      if (this.activeAvatar === "himari") {
        this.activeAvatar = "luna";
        this._captureJawRestPose();
      }
      this.cb.onSceneStatus("Himari dismissed");
      return;
    }
    if (this.himariInScene && this.activeAvatar === "himari") {
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
      this.cb.onSceneStatus("Viktor (Twitch/YouTube chat reply)");
      return;
    }

    await this.enableDualCohostLayout(url || undefined);
    this.setActiveSpeaker("cohost");
  }

  /** After Viktor chat TTS — hide temporary takeover or hand lip-sync back to Luna. */
  finishCohostChatReply(): void {
    if (this._chatReplyTakeover) {
      this._chatReplyTakeover = false;
      if (this.cohostVrm) {
        this._resetMouth(this.cohostVrm);
        this.cohostVrm.scene.visible = false;
      }
      if (this.vrm) {
        this.vrm.scene.visible = true;
        this.activeAvatar = "luna";
        this._captureJawRestPose();
        this.cb.onSceneStatus("Luna solo — summon co-host when you want them back");
      }
      return;
    }
    if (this.dualLayoutEnabled && this.activeAvatar === "cohost") {
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
