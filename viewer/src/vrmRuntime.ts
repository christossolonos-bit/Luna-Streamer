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
  private cohostVrm: VRM | null = null;
  private activeAvatar: "luna" | "cohost" = "luna";
  private dualLayoutEnabled = false;
  private static readonly COHOST_SIDE_GAP = 0.18;
  /** At dismiss: co-host root minus Luna root (world), so re-summon can place Viktor without moving Luna. */
  private readonly _savedCohostOffsetFromLuna = new THREE.Vector3();
  private _haveSavedCohostRelativePlacement = false;
  /** Viktor answering Twitch/YouTube while Luna solo — temporary on-screen takeover. */
  private _chatReplyTakeover = false;
  private static readonly CAMERA_ORBIT_PHI_PER_PX = 0.005;
  private static readonly CAMERA_ORBIT_PHI_MIN = 0.12;
  private static readonly CAMERA_ORBIT_PHI_MAX = Math.PI - 0.12;
  private static readonly AVATAR_DRAG_HORIZ_PER_PX = 0.0022;
  private static readonly AVATAR_DRAG_VERT_PER_PX = 0.0022;
  private readonly _layoutBox = new THREE.Box3();
  private readonly raycaster = new THREE.Raycaster();
  private readonly pointerNdc = new THREE.Vector2();
  /** Left-drag: vertical camera orbit (polar) around ``controls.target`` — no per-avatar hit areas. */
  private verticalOrbitDragActive = false;
  /** Right-drag reposition (horizontal on floor + vertical in world Y). */
  private avatarDragMove: "luna" | "cohost" | null = null;
  private orbitPointerY = 0;
  private dragMovePointerX = 0;
  private dragMovePointerY = 0;
  private interactionPointerId: number | null = null;
  private readonly _dragCamRight = new THREE.Vector3();
  private readonly _orbitScratchOffset = new THREE.Vector3();
  private readonly _orbitSpherical = new THREE.Spherical();
  private loader = new GLTFLoader();
  private animationLoader = new GLTFLoader();
  private mixer: THREE.AnimationMixer | null = null;
  private action: THREE.AnimationAction | null = null;
  private idleClips: THREE.AnimationClip[] = [];
  private idleClipIndex = 0;
  private idleModeEnabled = false;
  private idleSourceUrls: string[] = [];
  private cohostMixer: THREE.AnimationMixer | null = null;
  private cohostIdleAction: THREE.AnimationAction | null = null;
  private cohostIdleClips: THREE.AnimationClip[] = [];
  private cohostIdleClipIndex = 0;
  private cohostIdleModeEnabled = false;
  private cohostIdleSourceUrls: string[] = [];
  /** Skip leading seconds on co-host VRMA idles (avoids bind/T-pose at t=0). */
  private cohostIdleSkipSec = 2;
  private raf = 0;
  private lastFrame = performance.now();
  private fpsAccum = 0;
  private fpsFrames = 0;
  private disposed = false;
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
      e.preventDefault();
      e.stopPropagation();
      this.verticalOrbitDragActive = true;
      this.orbitPointerY = e.clientY;
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
    if (this.verticalOrbitDragActive) {
      const dy = e.clientY - this.orbitPointerY;
      this.orbitPointerY = e.clientY;
      this._orbitCameraVerticallyAroundTarget(dy);
      return;
    }

    if (this.avatarDragMove) {
      const dx = e.clientX - this.dragMovePointerX;
      const dy = e.clientY - this.dragMovePointerY;
      this.dragMovePointerX = e.clientX;
      this.dragMovePointerY = e.clientY;
      const root =
        this.avatarDragMove === "luna"
          ? this.vrm?.scene
          : this.cohostVrm?.scene;
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
    this.verticalOrbitDragActive = false;
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

  private activeVrm(): VRM | null {
    return this.activeAvatar === "cohost" ? this.cohostVrm : this.vrm;
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

  private _orientAvatarTowardCamera(vrm: VRM) {
    this._faceSceneRootTowardCamera(vrm.scene);
    vrm.scene.updateMatrixWorld(true);
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

  private _pickAvatar(clientX: number, clientY: number): "luna" | "cohost" | null {
    this._setPointerNdc(clientX, clientY);
    this.raycaster.setFromCamera(this.pointerNdc, this.camera);
    const roots: THREE.Object3D[] = [];
    if (this.vrm?.scene) roots.push(this.vrm.scene);
    if (this.cohostVrm?.scene.visible && this.cohostVrm.scene) {
      roots.push(this.cohostVrm.scene);
    }
    if (!roots.length) return null;
    const hits = this.raycaster.intersectObjects(roots, true);
    if (!hits.length) return null;
    let node: THREE.Object3D | null = hits[0].object;
    while (node) {
      if (this.cohostVrm && node === this.cohostVrm.scene) return "cohost";
      if (this.vrm && node === this.vrm.scene) return "luna";
      node = node.parent;
    }
    return null;
  }

  private _worldBounds(vrm: VRM): THREE.Box3 {
    vrm.scene.updateMatrixWorld(true);
    return this._layoutBox.setFromObject(vrm.scene);
  }

  /** Polar orbit from vertical mouse drag; pivot = current orbit target (not a picked avatar). */
  private _orbitCameraVerticallyAroundTarget(dyPx: number): void {
    if (dyPx === 0) return;
    const focus = this.controls.target;
    this._orbitScratchOffset.subVectors(this.camera.position, focus);
    this._orbitSpherical.setFromVector3(this._orbitScratchOffset);
    this._orbitSpherical.phi = THREE.MathUtils.clamp(
      this._orbitSpherical.phi - dyPx * VrmRuntime.CAMERA_ORBIT_PHI_PER_PX,
      VrmRuntime.CAMERA_ORBIT_PHI_MIN,
      VrmRuntime.CAMERA_ORBIT_PHI_MAX,
    );
    this._orbitScratchOffset.setFromSpherical(this._orbitSpherical);
    this.camera.position.copy(focus).add(this._orbitScratchOffset);
    this.camera.lookAt(focus);
  }

  private _faceSceneRootTowardCamera(root: THREE.Object3D) {
    const cam = this.camera.position;
    const dx = cam.x - root.position.x;
    const dz = cam.z - root.position.z;
    if (dx * dx + dz * dz < 1e-10) return;
    root.rotation.y = Math.atan2(dx, dz) + Math.PI;
  }

  private _faceVisibleAvatarsTowardCamera() {
    if (this.vrm?.scene.visible) this._faceSceneRootTowardCamera(this.vrm.scene);
    if (this.cohostVrm?.scene.visible) this._faceSceneRootTowardCamera(this.cohostVrm.scene);
  }

  /** Places co-host to Luna's side in world space. Does not move Luna (keeps summon/manual placement). */
  private _layoutCohostBesideLuna() {
    if (!this.vrm || !this.cohostVrm) return;

    const lunaBox = this._worldBounds(this.vrm).clone();

    this.cohostVrm.scene.position.set(0, 0, 0);
    const cohostAtOrigin = this._worldBounds(this.cohostVrm).clone();

    const gap = VrmRuntime.COHOST_SIDE_GAP;
    const offsetX = lunaBox.max.x + gap - cohostAtOrigin.min.x;
    const lunaCenterZ = (lunaBox.min.z + lunaBox.max.z) * 0.5;
    const cohostCenterZ = (cohostAtOrigin.min.z + cohostAtOrigin.max.z) * 0.5;
    const offsetY = lunaBox.min.y - cohostAtOrigin.min.y;

    this.cohostVrm.scene.position.set(offsetX, offsetY, lunaCenterZ - cohostCenterZ);
  }

  private _applyDualLayoutPositions() {
    if (!this.vrm || !this.cohostVrm) return;
    this._layoutCohostBesideLuna();
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
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
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
    if (this.mixer) this.mixer.update(delta);
    if (this.cohostMixer) this.cohostMixer.update(delta);
    if (this.activeVrm()) {
      const lipTarget = this._lipJawTarget;
      this._lipJawSmoothed += (lipTarget - this._lipJawSmoothed) * Math.min(1, delta * 18);
    }
    this.controls.update();
    this._faceVisibleAvatarsTowardCamera();
    if (this.vrm) this.vrm.update(delta);
    if (this.cohostVrm) this.cohostVrm.update(delta);
    if (this.activeVrm()) {
      // After VRM/humanoid update so idle animation does not stomp co-host jaw/visemes.
      this._applyJawBeforeHumanoidUpdate();
    }
    this.renderer.render(this.scene, this.camera);
  }

  private _ensureMixerForCurrentVrm() {
    if (!this.vrm) return;
    if (this.mixer) return;
    this.mixer = new THREE.AnimationMixer(this.vrm.scene);
    this.mixer.addEventListener("finished", this._onActionFinished);
  }

  private _onActionFinished = () => {
    if (!this.idleModeEnabled || this.idleClips.length === 0) return;
    this._playIdleAt(this.idleClipIndex % this.idleClips.length);
  };

  private _onCohostIdleFinished = () => {
    if (!this.cohostIdleModeEnabled || this.cohostIdleClips.length === 0) return;
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
    if (!this.cohostMixer || this.cohostIdleClips.length === 0) return;
    const normalized =
      ((index % this.cohostIdleClips.length) + this.cohostIdleClips.length) %
      this.cohostIdleClips.length;
    this.cohostIdleClipIndex = (normalized + 1) % this.cohostIdleClips.length;
    const clip = this.cohostIdleClips[normalized];
    // Hard cut between clips (like Luna). crossFadeFrom/fadeIn blended toward VRMA bind
    // pose at t=0 and caused a T-pose flash before each idle.
    if (this.cohostIdleAction) {
      this.cohostIdleAction.stop();
      this.cohostIdleAction = null;
    }
    const action = this.cohostMixer.clipAction(clip);
    action.reset();
    action.setLoop(THREE.LoopOnce, 1);
    action.clampWhenFinished = true;
    if (this.cohostIdleSkipSec > 0 && clip.duration > 0) {
      action.time = Math.min(
        this.cohostIdleSkipSec,
        Math.max(0, clip.duration - 0.05),
      );
    }
    action.play();
    this.cohostIdleAction = action;
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
      this._playCohostIdleAt(0);
      this.cb.onSceneStatus(
        `Co-host idle loop (${this.cohostIdleClips.length} clip${this.cohostIdleClips.length === 1 ? "" : "s"})`,
      );
    }
  }

  private _stopCohostIdleMotion() {
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

  private _playIdleAt(index: number) {
    if (!this.mixer || this.idleClips.length === 0) return;
    const normalized =
      ((index % this.idleClips.length) + this.idleClips.length) %
      this.idleClips.length;
    this.idleClipIndex = (normalized + 1) % this.idleClips.length;
    if (this.action) {
      this.action.stop();
      this.action = null;
    }
    const clip = this.idleClips[normalized];
    const action = this.mixer.clipAction(clip);
    action.reset();
    action.setLoop(THREE.LoopOnce, 1);
    action.clampWhenFinished = false;
    action.play();
    this.action = action;
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
      this._orientAvatarTowardCamera(vrm);
      this._captureJawRestPose();
      this._ensureMixerForCurrentVrm();
      this.scene.add(vrm.scene);
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
    this._orientAvatarTowardCamera(vrm);
    this._captureJawRestPose();
    this._ensureMixerForCurrentVrm();
    this.scene.add(vrm.scene);
    this.cb.onSceneStatus(`Avatar loaded: ${label}`);
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
    if (this.idleClips.length > 0) {
      this.idleModeEnabled = true;
      this._playIdleAt(0);
      this.cb.onSceneStatus(`Idle motion loop active (${this.idleClips.length} clip${this.idleClips.length === 1 ? "" : "s"})`);
    }
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
    this.scene.remove(this.vrm.scene);
    disposeObject(this.vrm.scene);
    this.vrm = null;
    this.activeAvatar = "luna";
    this._jawRestQuat = null;
    this._lipJawTarget = 0;
    this._lipJawSmoothed = 0;
  }

  private clearCohostVrm() {
    if (!this.cohostVrm) return;
    this._stopCohostIdleMotion();
    this.scene.remove(this.cohostVrm.scene);
    disposeObject(this.cohostVrm.scene);
    this.cohostVrm = null;
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

  dismissCohost(): void {
    setCohostSoloMode(true);
    stopViewerTts();
    window.dispatchEvent(
      new CustomEvent("luna-avatar-speaking", { detail: false }),
    );
    if (!this.cohostVrm) return;
    if (this.vrm && this.cohostVrm) {
      this._savedCohostOffsetFromLuna
        .copy(this.cohostVrm.scene.position)
        .sub(this.vrm.scene.position);
      this._haveSavedCohostRelativePlacement = true;
    } else {
      this._haveSavedCohostRelativePlacement = false;
    }
    this.verticalOrbitDragActive = false;
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
    this.scene.add(vrm.scene);
    vrm.scene.visible = false;
    this.cb.onSceneStatus(`Co-host model ready: ${label}`);
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
      this.cohostVrm.scene.position
        .copy(this.vrm.scene.position)
        .add(this._savedCohostOffsetFromLuna);
      this._haveSavedCohostRelativePlacement = false;
    } else {
      this._applyDualLayoutPositions();
    }

    this.activeAvatar = "luna";
    this._captureJawRestPose();
    this.cb.onSceneStatus(
      "Luna + co-host · left-drag: camera up/down · right-drag on body: move · right-drag empty: pan · scroll: zoom · models track the camera",
    );
  }

  setActiveSpeaker(speaker: "luna" | "cohost") {
    this._resetMouth(this.vrm);
    this._resetMouth(this.cohostVrm);
    this._lipJawTarget = 0;
    this._lipJawSmoothed = 0;
    this.activeAvatar = speaker;
    this._captureJawRestPose();
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
        this.cohostVrm.scene.position.copy(this.vrm.scene.position);
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
      // Pause Viktor idle while he speaks so idle keyframes don't override lip/shape + jaw.
      if (this.activeAvatar === "cohost" && this.cohostIdleAction) {
        this.cohostIdleAction.paused = true;
      }
      // Keep viseme+jaw loop alive for the full TTS playback window.
      this.triggerTalk("speaking", true);
      return;
    }
    if (this.cohostIdleAction) {
      this.cohostIdleAction.paused = false;
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
    this.clearVrm();
    this.controls.dispose();
    this.renderer.dispose();
    this.cb.onSceneStatus("Scene disposed.");
  }
}
