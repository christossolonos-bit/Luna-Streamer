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

export type ChromaKeyMode = "off" | "green" | "blue";

export class VrmRuntime {
  /** Rotate loaded avatars so they face the camera at startup. */
  private static readonly STARTUP_YAW_RAD = Math.PI;
  private renderer: THREE.WebGLRenderer;
  private scene: THREE.Scene;
  private readonly sceneFog: THREE.FogExp2;
  private floorGrid: THREE.GridHelper;
  private readonly defaultBackground = 0x030308;
  private camera: THREE.PerspectiveCamera;
  private controls: OrbitControls;
  private readonly clock = new THREE.Clock();
  private vrm: VRM | null = null;
  private loader = new GLTFLoader();
  private animationLoader = new GLTFLoader();
  private mixer: THREE.AnimationMixer | null = null;
  private action: THREE.AnimationAction | null = null;
  private idleClips: THREE.AnimationClip[] = [];
  private idleClipIndex = 0;
  private idleModeEnabled = false;
  private idleSourceUrls: string[] = [];
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

  private _trySetExpression(mgr: VRMExpressionManager, names: readonly string[], value: number): boolean {
    for (const name of names) {
      if (mgr.getExpression(name)) {
        mgr.setValue(name, value);
        return true;
      }
    }
    return false;
  }

  private _captureJawRestPose() {
    this._jawRestQuat = null;
    if (!this.vrm) return;
    const jaw = this.vrm.humanoid.getNormalizedBoneNode(VRMHumanBoneName.Jaw);
    if (jaw) {
      this._jawRestQuat = jaw.quaternion.clone();
    }
  }

  private _applyJawBeforeHumanoidUpdate() {
    if (!this.vrm || !this._jawRestQuat) return;
    const jaw = this.vrm.humanoid.getNormalizedBoneNode(VRMHumanBoneName.Jaw);
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
    vrm.scene.rotation.y = VrmRuntime.STARTUP_YAW_RAD;
    vrm.scene.updateMatrixWorld(true);
  }

  private _setVowelExpressions(vowel: string, amp: number) {
    if (!this.vrm?.expressionManager) return;
    const mgr = this.vrm.expressionManager;
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
      alpha: false,
      powerPreference: "high-performance",
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
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
    this.controls.update();

    this.canvas.style.userSelect = "none";
    this.canvas.style.setProperty("-webkit-user-select", "none");
    this.canvas.style.touchAction = "none";
    this.canvas.addEventListener("contextmenu", this.onCanvasContextMenu);

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
   * Solid green/blue background for OBS chroma key. Disables fog and floor grid so only the avatar keys cleanly.
   */
  setChromaKeyMode(mode: ChromaKeyMode) {
    if (this.disposed) return;
    const CHROMA_GREEN = 0x00ff00;
    const CHROMA_BLUE = 0x0047bb;
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
    if (this.vrm) {
      const lipTarget = this._lipJawTarget;
      this._lipJawSmoothed += (lipTarget - this._lipJawSmoothed) * Math.min(1, delta * 14);
      this._applyJawBeforeHumanoidUpdate();
      this.vrm.update(delta);
    }
    this.controls.update();
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
        const clip = await this._loadVrmaClipFromUrl(url);
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

  private async _loadVrmaClipFromUrl(url: string): Promise<THREE.AnimationClip> {
    if (!this.vrm) {
      throw new Error("Load a VRM avatar first.");
    }
    const gltf = await this.animationLoader.loadAsync(url);
    const animations = gltf.userData.vrmAnimations as unknown[] | undefined;
    if (!animations || animations.length === 0) {
      throw new Error("No VRM animation track found in file.");
    }
    const vrmAnimation = animations[0] as VRMAnimation;
    return createVRMAnimationClip(vrmAnimation, this.vrm);
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
    this._jawRestQuat = null;
    this._lipJawTarget = 0;
    this._lipJawSmoothed = 0;
  }

  triggerEmotion(raw: string) {
    if (!this.vrm?.expressionManager) return;
    const mgr = this.vrm.expressionManager;

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
    if (this.emotionTimer) window.clearTimeout(this.emotionTimer);
    this.emotionTimer = window.setTimeout(() => {
      for (const n of ["happy", "sad", "angry", "surprised", "relaxed"]) {
        this._trySetExpression(mgr, emotionAliases[n], 0);
      }
      this.emotionTimer = 0;
    }, 900);
  }

  triggerTalk(text: string, holdUntilStop = false) {
    if (!this.vrm) return;
    const mgr = this.vrm.expressionManager;

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
      if ((!this._forceSpeaking && now >= this.talkUntil) || this.disposed) {
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
      // Keep viseme+jaw loop alive for the full TTS playback window.
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
    if (!this.vrm) return;
    const mgr = this.vrm.expressionManager;
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
    this.clearVrm();
    this.controls.dispose();
    this.renderer.dispose();
    this.cb.onSceneStatus("Scene disposed.");
  }
}
