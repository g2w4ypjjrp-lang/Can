"use client";
/**
 * 3D AI Ofis (three.js). Gerçek ajan verisini gösterir: çalışan ajanın monitörü yanar, klavyede yazar,
 * etiketinde yeşil ışık yanar. Fareyle yakınlaştırma/kaydırma ve sınırlı döndürme vardır.
 */
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { ROOMS, shortName, type Agent } from "@/lib/office";

const ROOM_W = 7.4, ROOM_D = 8.2, GAP = 1.2, CORRIDOR = 2.6, LOUNGE_W = 11;
const FLOOR_W = ROOM_W * 4 + GAP * 3 + 2 + LOUNGE_W, FLOOR_D = ROOM_D * 2 + CORRIDOR + 2;

export type OfficeMode = "normal" | "cinema" | "tour";
export type OfficeHandle = { reset: () => void };
const SKIN = ["#f1c9a5", "#e0ac83", "#c68a5e", "#8d5a3b", "#f5d6bd"];
const HAIR = ["#2b1d16", "#5a3825", "#111111", "#a0642c", "#d9b26a", "#6b4a3a"];

type Seat = { group: THREE.Group; screen: THREE.MeshStandardMaterial; armL: THREE.Object3D; armR: THREE.Object3D;
  head: THREE.Object3D; chip: HTMLButtonElement; bubble: HTMLElement; phase: number; working: boolean; real: boolean };

const mat = (color: string, o: Partial<THREE.MeshStandardMaterialParameters> = {}) =>
  new THREE.MeshStandardMaterial({ color, roughness: 0.75, metalness: 0.02, ...o });

function box(w: number, h: number, d: number, m: THREE.Material, x = 0, y = 0, z = 0) {
  const b = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m);
  b.position.set(x, y, z); b.castShadow = true; b.receiveShadow = true;
  return b;
}

function woodTexture() {
  const c = document.createElement("canvas"); c.width = 512; c.height = 512;
  const g = c.getContext("2d")!;
  g.fillStyle = "#d9a15a"; g.fillRect(0, 0, 512, 512);
  for (let y = 0; y < 512; y += 32) {
    for (let x = (y / 32) % 2 ? -128 : 0; x < 512; x += 256) {
      const l = 0.9 + Math.random() * 0.16;
      g.fillStyle = `rgb(${217 * l},${161 * l},${90 * l})`; g.fillRect(x + 1, y + 1, 254, 30);
      g.strokeStyle = "rgba(90,50,15,.08)";
      for (let i = 0; i < 4; i++) { g.beginPath(); g.moveTo(x, y + 6 + i * 6); g.bezierCurveTo(x + 80, y + 2 + i * 7, x + 170, y + 10 + i * 5, x + 256, y + 5 + i * 6); g.stroke(); }
    }
  }
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(6, 4);
  t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8;
  return t;
}

function hatchTexture() {
  const c = document.createElement("canvas"); c.width = 128; c.height = 128;
  const g = c.getContext("2d")!;
  g.strokeStyle = "rgba(40,30,20,.55)"; g.lineWidth = 7;
  for (let i = -128; i < 256; i += 26) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i + 128, 128); g.stroke(); }
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function plant(x: number, z: number, s = 1) {
  const g = new THREE.Group();
  g.add(box(0.42 * s, 0.45 * s, 0.42 * s, mat("#e8e4dc"), 0, 0.225 * s, 0));
  const leaf = mat("#3f9d5a", { roughness: 0.9 });
  for (let i = 0; i < 5; i++) {
    const l = new THREE.Mesh(new THREE.IcosahedronGeometry(0.28 * s, 0), leaf);
    l.position.set(Math.sin(i * 1.3) * 0.15 * s, (0.6 + i * 0.14) * s, Math.cos(i * 1.7) * 0.15 * s);
    l.castShadow = true; g.add(l);
  }
  g.position.set(x, 0, z);
  return g;
}

function chair(color: string) {
  const g = new THREE.Group(), m = mat(color, { roughness: 0.6 }), metal = mat("#334155", { metalness: 0.6, roughness: 0.4 });
  g.add(box(0.5, 0.08, 0.5, m, 0, 0.48, 0));
  g.add(box(0.5, 0.55, 0.08, m, 0, 0.78, 0.24));
  g.add(box(0.06, 0.44, 0.06, metal, 0, 0.24, 0));
  g.add(box(0.5, 0.04, 0.06, metal, 0, 0.02, 0)); g.add(box(0.06, 0.04, 0.5, metal, 0, 0.02, 0));
  return g;
}

function person(tone: string, idx: number) {
  const g = new THREE.Group();
  const shirt = mat(tone, { roughness: 0.7 }), skin = mat(SKIN[idx % SKIN.length], { roughness: 0.6 });
  const torso = new THREE.Mesh(new THREE.CapsuleGeometry(0.2, 0.32, 6, 12), shirt);
  torso.position.set(0, 0.86, 0.05); torso.castShadow = true; g.add(torso);
  const legs = box(0.36, 0.14, 0.5, mat("#334155"), 0, 0.56, -0.12); g.add(legs);
  const head = new THREE.Group(); head.position.set(0, 1.32, 0.03);
  const face = new THREE.Mesh(new THREE.SphereGeometry(0.16, 20, 16), skin); face.castShadow = true; head.add(face);
  const hair = new THREE.Mesh(new THREE.SphereGeometry(0.17, 20, 12, 0, Math.PI * 2, 0, Math.PI * (idx % 3 === 0 ? 0.62 : 0.5)),
    mat(HAIR[(idx * 7) % HAIR.length], { roughness: 0.9 }));
  hair.rotation.x = -0.25; head.add(hair);
  g.add(head);
  const mkArm = (side: number) => {
    const pivot = new THREE.Group(); pivot.position.set(0.24 * side, 1.02, 0.02);
    const arm = new THREE.Mesh(new THREE.CapsuleGeometry(0.06, 0.32, 4, 8), shirt);
    arm.position.set(0, -0.12, -0.16); arm.rotation.x = Math.PI / 2.6; arm.castShadow = true; pivot.add(arm);
    const hand = new THREE.Mesh(new THREE.SphereGeometry(0.06, 10, 8), skin); hand.position.set(0, -0.2, -0.33); pivot.add(hand);
    g.add(pivot); return pivot;
  };
  return { g, head, armL: mkArm(-1), armR: mkArm(1) };
}

function deskSet(tone: string, idx: number, deskColor: string) {
  const g = new THREE.Group();
  const top = mat(deskColor, { roughness: 0.45 }), leg = mat("#cbd5e1", { metalness: 0.4, roughness: 0.4 });
  g.add(box(1.5, 0.06, 0.8, top, 0, 0.76, -0.45));
  for (const [x, z] of [[-0.7, -0.8], [0.7, -0.8], [-0.7, -0.1], [0.7, -0.1]]) g.add(box(0.05, 0.74, 0.05, leg, x, 0.37, z));
  const screen = new THREE.MeshStandardMaterial({ color: "#0f172a", emissive: "#000000", roughness: 0.3 });
  const mon = box(0.66, 0.4, 0.04, mat("#1e293b"), 0, 1.06, -0.72); g.add(mon);
  const scr = new THREE.Mesh(new THREE.PlaneGeometry(0.6, 0.34), screen); scr.position.set(0, 1.06, -0.695); g.add(scr);
  g.add(box(0.06, 0.2, 0.06, mat("#334155"), 0, 0.87, -0.74));
  g.add(box(0.46, 0.02, 0.16, mat("#e2e8f0"), 0, 0.8, -0.38));            // klavye
  g.add(box(0.1, 0.12, 0.1, mat(["#f8fafc", "#fde68a", "#fecaca"][idx % 3]), 0.55, 0.85, -0.55)); // kupa
  const c = chair("#1f2937"); c.position.set(0, 0, 0.25); g.add(c);
  const p = person(tone, idx); p.g.position.set(0, 0, 0.18); g.add(p.g);
  return { g, screen, head: p.head, armL: p.armL, armR: p.armR };
}

function chipEl(name: string) {
  const wrap = document.createElement("div"); wrap.className = "o3-label";
  const bubble = document.createElement("span"); bubble.className = "o3-bubble"; bubble.textContent = "çalışıyor…";
  const chip = document.createElement("button"); chip.type = "button"; chip.className = "o3-chip";
  chip.innerHTML = `<i></i><span></span>`; (chip.querySelector("span") as HTMLElement).textContent = name;
  wrap.append(bubble, chip);
  return { wrap, chip, bubble };
}

export default function Office3D({ agents, target, onPick, mode = "normal", shortLabels = false, demoCodes = [], resetKey = 0 }:
  { agents: Agent[]; target: string; onPick?: (code: string) => void; mode?: OfficeMode; shortLabels?: boolean;
    demoCodes?: string[]; resetKey?: number }) {
  const ctl = useRef<{ controls: OrbitControls; camera: THREE.OrthographicCamera; rooms: THREE.Vector3[]; home: () => void } | null>(null);
  const host = useRef<HTMLDivElement>(null);
  const seats = useRef<Map<string, Seat>>(new Map());
  const pickRef = useRef(onPick); pickRef.current = onPick;

  // Sahne bir kez kurulur.
  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const scene = new THREE.Scene();
    scene.background = null;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.12;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    el.appendChild(renderer.domElement);
    const labels = new CSS2DRenderer(); labels.domElement.className = "o3-labels"; el.appendChild(labels.domElement);

    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 200);
    camera.position.set(29, 26, 26); camera.lookAt(3, 0, 0);
    const controls = new OrbitControls(camera, labels.domElement);
    controls.target.set(3, 0, 0); controls.enableDamping = true; controls.minZoom = 0.5; controls.maxZoom = 3; controls.screenSpacePanning = true;
    controls.minPolarAngle = Math.PI / 5; controls.maxPolarAngle = Math.PI / 3.2;
    controls.minAzimuthAngle = Math.PI / 4 - 0.5; controls.maxAzimuthAngle = Math.PI / 4 + 0.5;

    // Işıklar
    scene.add(new THREE.HemisphereLight("#ffffff", "#d8c8b0", 1.9));
    const sun = new THREE.DirectionalLight("#fff6e8", 1.7);
    sun.position.set(-14, 26, 10); sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048); sun.shadow.bias = -0.0004; sun.shadow.radius = 8;
    Object.assign(sun.shadow.camera, { left: -24, right: 24, top: 20, bottom: -20, near: 1, far: 80 });
    scene.add(sun);

    // Zemin ve dış duvarlar (pencereli)
    const wood = woodTexture();
    const floor = box(FLOOR_W, 0.3, FLOOR_D, new THREE.MeshStandardMaterial({ map: wood, roughness: 0.8 }), 0, -0.15, 0);
    scene.add(floor);
    scene.add(box(FLOOR_W + 0.6, 0.5, FLOOR_D + 0.6, mat("#f5f3ee"), 0, -0.42, 0));
    const wallM = mat("#f8f7f4"), frame = mat("#475569", { roughness: 0.4 }),
      glassWin = new THREE.MeshStandardMaterial({ color: "#cfe6f7", emissive: "#bfe0ff", emissiveIntensity: 0.3, roughness: 0.1 });
    scene.add(box(FLOOR_W, 3.6, 0.3, wallM, 0, 1.8, -FLOOR_D / 2 - 0.15));
    scene.add(box(0.3, 3.6, FLOOR_D, wallM, -FLOOR_W / 2 - 0.15, 1.8, 0));
    const gridWindow = (w: number, h: number, alongX: boolean, x: number, y: number, z: number) => {
      const g = new THREE.Group(); g.position.set(x, y, z); if (!alongX) g.rotation.y = Math.PI / 2;
      g.add(box(w, h, 0.04, glassWin, 0, 0, 0));
      for (let i = 0; i <= 3; i++) g.add(box(0.06, h + 0.06, 0.08, frame, -w / 2 + (w * i) / 3, 0, 0.03));
      for (let j = 0; j <= 2; j++) g.add(box(w + 0.06, 0.06, 0.08, frame, 0, -h / 2 + (h * j) / 2, 0.03));
      scene.add(g);
    };
    for (let i = 0; i < 6; i++) gridWindow(3.2, 2, true, -FLOOR_W / 2 + 3.4 + i * (FLOOR_W - 6.8) / 5, 1.95, -FLOOR_D / 2 + 0.03);
    for (let i = 0; i < 2; i++) gridWindow(3.2, 2, false, -FLOOR_W / 2 + 0.03, 1.95, -FLOOR_D / 2 + 5 + i * (FLOOR_D - 10));
    // Duvardaki logo
    const sign = document.createElement("div"); sign.className = "o3-sign"; sign.textContent = "AI BUSINESS CENTER";
    const signObj = new CSS2DObject(sign); signObj.position.set(FLOOR_W / 2 - LOUNGE_W / 2, 3.1, -FLOOR_D / 2 + 0.2); scene.add(signObj);

    // Odalar
    const glassM = new THREE.MeshStandardMaterial({ color: "#dbeafe", transparent: true, opacity: 0.3, roughness: 0.05, depthWrite: false });
    const frameM = mat("#ffffff", { roughness: 0.35 });
    const hatch = hatchTexture();
    const hatchM = new THREE.MeshStandardMaterial({ map: hatch, transparent: true, roughness: 0.9 });
    const roomCenters: THREE.Vector3[] = [];
    const pickables: THREE.Object3D[] = [];
    ROOMS.forEach((room, ri) => {
      const cx = -FLOOR_W / 2 + 1 + ROOM_W / 2 + room.col * (ROOM_W + GAP);
      const cz = -FLOOR_D / 2 + 1 + ROOM_D / 2 + room.row * (ROOM_D + CORRIDOR);
      const g = new THREE.Group(); g.position.set(cx, 0, cz); scene.add(g);
      roomCenters.push(new THREE.Vector3(cx, 0, cz));
      // Cam bölmeler (koridor tarafında kapı boşluğu)
      const H = 1.35;
      const pane = (w: number, d: number, x: number, z: number) => {
        const p = new THREE.Mesh(new THREE.BoxGeometry(w, H, d), glassM); p.position.set(x, H / 2, z); g.add(p);
        g.add(box(w + 0.03, 0.05, d + 0.03, frameM, x, H, z));
        g.add(box(w + 0.03, 0.08, d + 0.03, frameM, x, 0.04, z));
      };
      const hw = ROOM_W / 2, hd = ROOM_D / 2, door = 1.6;
      const back = room.row === 0 ? -hd : hd, front = -back;
      pane(ROOM_W, 0.05, 0, back);
      pane((ROOM_W - door) / 2, 0.05, -hw + (ROOM_W - door) / 4, front); pane((ROOM_W - door) / 2, 0.05, hw - (ROOM_W - door) / 4, front);
      pane(0.05, ROOM_D, -hw, 0); pane(0.05, ROOM_D, hw, 0);
      for (const [x, z] of [[-hw, -hd], [hw, -hd], [-hw, hd], [hw, hd]]) g.add(box(0.05, H + 0.03, 0.05, frameM, x, (H + 0.03) / 2, z));
      g.add(plant(hw - 0.5, -hd + 0.5));

      // Oda etiketi
      const lab = document.createElement("div"); lab.className = "o3-room"; lab.style.setProperty("--tone", room.tone); lab.textContent = room.label;
      const lo = new CSS2DObject(lab); lo.position.set(-hw + 1.6, 1.45, -hd); g.add(lo);

      // Odaya özel eşyalar
      if (room.key === "ceo") {
        g.add(box(2.6, 0.08, 1.3, mat("#f8fafc", { roughness: 0.3 }), 0, 0.74, 1.6));
        g.add(box(0.12, 0.7, 0.12, mat("#94a3b8"), 0, 0.37, 1.6));
        for (const [x, z, r] of [[-0.8, 2.45, 0], [0.8, 2.45, 0], [-0.8, 0.75, Math.PI], [0.8, 0.75, Math.PI]]) {
          const ch = chair("#475569"); ch.position.set(x, 0, z); ch.rotation.y = r; g.add(ch);
        }
      }
      if (room.key === "ideas" || room.key === "finance") {
        const shelf = new THREE.Group(); shelf.position.set(-hw + 0.35, 0, -hd + 1.8);
        shelf.add(box(0.4, 2, 1.6, mat("#f1f5f9"), 0, 1, 0));
        const bookColors = ["#ef4444", "#3b82f6", "#f59e0b", "#10b981", "#8b5cf6"];
        for (let s = 0; s < 3; s++) for (let b = 0; b < 6; b++)
          shelf.add(box(0.28, 0.4, 0.16, mat(bookColors[(s + b) % 5]), 0.02, 0.35 + s * 0.6, -0.6 + b * 0.24));
        g.add(shelf);
      }
      if (room.key === "studio") {
        const tripod = new THREE.Group(); tripod.position.set(hw - 1, 0, 1.8);
        tripod.add(box(0.05, 1.4, 0.05, mat("#111827"), 0, 0.7, 0));
        tripod.add(box(0.35, 0.25, 0.4, mat("#111827"), 0, 1.5, 0));
        const light = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.3, 0.06, 24), new THREE.MeshStandardMaterial({ color: "#fff", emissive: "#fff7d6", emissiveIntensity: 0.9 }));
        light.position.set(-1.2, 1.7, 0); light.rotation.z = Math.PI / 2; tripod.add(light);
        g.add(tripod);
      }

      // Masalar
      const codes = room.key === "ceo" ? ["ceo"] : room.codes;
      const perRow = codes.length > 4 ? 3 : 2;
      codes.forEach((code, i) => {
        const row = Math.floor(i / perRow), col = i % perRow, n = Math.min(perRow, codes.length - row * perRow);
        const x = (col - (n - 1) / 2) * 2.2, z = room.key === "ceo" ? -1.9 : -hd + 2 + row * 2.7;
        const d = deskSet(room.tone, ri * 5 + i, "#fafaf9");
        d.g.position.set(x, 0, z); d.g.rotation.y = Math.PI; g.add(d.g);
        d.g.userData.code = code; pickables.push(d.g);
        const { wrap, chip, bubble } = chipEl(code);
        chip.addEventListener("click", () => pickRef.current?.(code));
        const lo2 = new CSS2DObject(wrap); lo2.position.set(0, 1.72, 0.2); d.g.add(lo2);
        seats.current.set(code, { group: d.g, screen: d.screen, armL: d.armL, armR: d.armR, head: d.head,
          chip, bubble, phase: Math.random() * 6, working: false, real: false });
      });
    });

    // Sağda açık dinlenme alanı
    const lx = FLOOR_W / 2 - LOUNGE_W / 2, lounge = new THREE.Group(); lounge.position.set(lx, 0, 0); scene.add(lounge);
    const rugM = mat("#d6cfc4", { roughness: 1 }), sofaM = mat("#3f4654", { roughness: 0.9 }), cushion = mat("#e8d9c0", { roughness: 1 });
    const rug2 = new THREE.Mesh(new THREE.CylinderGeometry(3, 3, 0.02, 48), rugM); rug2.position.set(0, 0.01, 1.5); rug2.receiveShadow = true; lounge.add(rug2);
    lounge.add(box(3.6, 0.45, 1, sofaM, 0, 0.3, 3.6)); lounge.add(box(3.6, 0.7, 0.28, sofaM, 0, 0.7, 4));
    lounge.add(box(0.3, 0.6, 1, sofaM, -1.8, 0.45, 3.6)); lounge.add(box(0.3, 0.6, 1, sofaM, 1.8, 0.45, 3.6));
    for (const x of [-1, 0.2, 1.2]) lounge.add(box(0.6, 0.4, 0.15, cushion, x, 0.75, 3.8));
    lounge.add(box(1.6, 0.06, 0.8, mat("#2b2f38", { roughness: 0.3 }), 0, 0.42, 1.6));
    for (const [x, z] of [[-0.7, 1.3], [0.7, 1.3], [-0.7, 1.9], [0.7, 1.9]]) lounge.add(box(0.05, 0.4, 0.05, mat("#111827"), x, 0.2, z));
    for (const [x, r] of [[-2.6, 0.6], [2.6, -0.6]]) {
      const a = new THREE.Group(); a.position.set(x, 0, 1.3); a.rotation.y = r;
      a.add(box(0.9, 0.4, 0.9, mat("#b4876a"), 0, 0.3, 0)); a.add(box(0.9, 0.6, 0.2, mat("#b4876a"), 0, 0.65, 0.4)); lounge.add(a);
    }
    // TV duvarı ve raflar
    lounge.add(box(4.4, 1.2, 0.5, mat("#f1f0ec"), 0, 0.6, -FLOOR_D / 2 + 0.55));
    const tv = new THREE.Mesh(new THREE.BoxGeometry(3, 1.7, 0.08), new THREE.MeshStandardMaterial({ color: "#0b1220", emissive: "#1e3a8a", emissiveIntensity: 0.35, roughness: 0.2 }));
    tv.position.set(0, 2.15, -FLOOR_D / 2 + 0.1); lounge.add(tv);
    const shelf = new THREE.Group(); shelf.position.set(LOUNGE_W / 2 - 0.5, 0, -FLOOR_D / 2 + 2.5); lounge.add(shelf);
    for (let k = 0; k < 4; k++) shelf.add(box(0.5, 0.05, 2.2, mat("#7c5a3c"), 0, 0.4 + k * 0.55, 0));
    shelf.add(box(0.5, 2.1, 0.05, mat("#7c5a3c"), 0, 1.05, -1.1)); shelf.add(box(0.5, 2.1, 0.05, mat("#7c5a3c"), 0, 1.05, 1.1));
    const deco = ["#f59e0b", "#e11d48", "#10b981", "#6366f1", "#f8fafc"];
    for (let k = 0; k < 3; k++) for (let b = 0; b < 4; b++) shelf.add(box(0.3, 0.3, 0.3, mat(deco[(k + b) % 5]), 0, 0.6 + k * 0.55, -0.8 + b * 0.5));
    // Kahve köşesi ve bitkiler
    const bar = new THREE.Group(); bar.position.set(-LOUNGE_W / 2 + 1.6, 0, -FLOOR_D / 2 + 1); lounge.add(bar);
    bar.add(box(2.6, 0.95, 0.7, mat("#e7e5e4"), 0, 0.47, 0)); bar.add(box(0.45, 0.55, 0.4, mat("#1f2937"), -0.7, 1.22, 0));
    bar.add(box(0.12, 0.14, 0.12, mat("#f8fafc"), 0.3, 1.02, 0.1));
    for (const [x, z, sc] of [[LOUNGE_W / 2 - 0.8, 4.2, 1.3], [-LOUNGE_W / 2 + 0.9, 4.2, 1.1]])
      lounge.add(plant(x, z, sc));
    const loungeLabel = document.createElement("div"); loungeLabel.className = "o3-room"; loungeLabel.style.setProperty("--tone", "#a16207");
    loungeLabel.textContent = "DİNLENME ALANI"; const llo = new CSS2DObject(loungeLabel); llo.position.set(0, 0.05, 4.9); lounge.add(llo);

    // Boyut ve kamera sığdırma
    const fit = () => {
      const w = el.clientWidth, h = el.clientHeight;
      renderer.setSize(w, h); labels.setSize(w, h);
      const aspect = w / h, view = 13;
      Object.assign(camera, { left: -view * aspect, right: view * aspect, top: view, bottom: -view });
      camera.zoom = Math.max(0.55, Math.min(1.1, w / 1600));
      camera.updateProjectionMatrix();
    };
    fit();
    const ro = new ResizeObserver(fit); ro.observe(el);
    const home = () => {
      camera.position.set(29, 26, 26); controls.target.set(3, 0, 0); fit(); controls.update();
    };
    ctl.current = { controls, camera, rooms: roomCenters, home };

    // Tıklama ile ajan seçimi
    const ray = new THREE.Raycaster(), ptr = new THREE.Vector2();
    let down = { x: 0, y: 0 };
    const onDown = (e: PointerEvent) => { down = { x: e.clientX, y: e.clientY }; };
    const onUp = (e: PointerEvent) => {
      if (Math.hypot(e.clientX - down.x, e.clientY - down.y) > 5) return;
      const r = labels.domElement.getBoundingClientRect();
      ptr.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(ptr, camera);
      const hit = ray.intersectObjects(pickables, true)[0];
      let o: THREE.Object3D | null = hit?.object ?? null;
      while (o && !o.userData.code) o = o.parent;
      if (o) pickRef.current?.(o.userData.code);
    };
    labels.domElement.addEventListener("pointerdown", onDown);
    labels.domElement.addEventListener("pointerup", onUp);

    // Döngü
    const clock = new THREE.Clock();
    let raf = 0;
    const loop = () => {
      raf = requestAnimationFrame(loop);
      if (document.hidden) return;
      const t = clock.getElapsedTime();
      controls.update();
      for (const s of seats.current.values()) {
        if (reduce) continue;
        if (s.working) {
          s.armL.rotation.x = Math.sin(t * 14 + s.phase) * 0.12;
          s.armR.rotation.x = Math.sin(t * 14 + s.phase + 1.7) * 0.12;
          s.head.rotation.x = Math.sin(t * 2 + s.phase) * 0.05;
          s.screen.emissiveIntensity = 0.85 + Math.sin(t * 3 + s.phase) * 0.15;
        } else {
          s.armL.rotation.x = s.armR.rotation.x = 0;
          s.head.rotation.y = Math.sin(t * 0.4 + s.phase) * 0.25;
        }
      }
      renderer.render(scene, camera); labels.render(scene, camera);
    };
    loop();

    return () => {
      cancelAnimationFrame(raf); ro.disconnect(); controls.dispose();
      labels.domElement.removeEventListener("pointerdown", onDown); labels.domElement.removeEventListener("pointerup", onUp);
      scene.traverse((o) => {
        const m = o as THREE.Mesh;
        m.geometry?.dispose();
        (Array.isArray(m.material) ? m.material : m.material ? [m.material] : []).forEach((x) => x.dispose());
      });
      wood.dispose(); hatch.dispose(); renderer.dispose(); ctl.current = null;
      el.replaceChildren(); seats.current.clear();
    };
  }, []);

  // Veri değişince yalnızca durumlar güncellenir.
  useEffect(() => {
    const byCode = new Map(agents.map((a) => [a.code, a]));
    for (const [code, s] of seats.current) {
      const a = byCode.get(code);
      s.real = !!a && a.active_tasks > 0;
      const demo = demoCodes.includes(code);
      s.working = s.real || demo;
      s.bubble.textContent = s.real ? "çalışıyor…" : "DEMO";
      s.bubble.classList.toggle("is-demo", demo && !s.real);
      s.chip.parentElement?.classList.toggle("is-short", shortLabels && !s.working && target !== code);
      (s.chip.querySelector("span") as HTMLElement).textContent = a ? shortName(a.name) : code;
      s.chip.title = a ? `${a.name}: ${a.description}` : code;
      s.chip.classList.toggle("is-working", s.working);
      s.chip.classList.toggle("is-selected", target === code);
      s.chip.disabled = !pickRef.current;
      s.bubble.style.display = s.working && (!shortLabels || (demo && !s.real)) ? "" : "none";
      s.screen.emissive.set(s.working ? "#3b82f6" : "#000000");
      s.screen.color.set(s.working ? "#1d4ed8" : "#0f172a");
      s.group.visible = !!a;
    }
  }, [agents, target, demoCodes, shortLabels]);

  // Kamera modları: sinema (yavaş dönüş), tur (odaları sırayla gezer)
  useEffect(() => {
    const c = ctl.current;
    if (!c) return;
    const { controls, camera } = c;
    controls.autoRotate = mode === "cinema"; controls.autoRotateSpeed = 0.6;
    controls.minAzimuthAngle = mode === "cinema" ? -Infinity : Math.PI / 4 - 0.5;
    controls.maxAzimuthAngle = mode === "cinema" ? Infinity : Math.PI / 4 + 0.5;
    if (mode !== "tour") return;
    let i = 0, raf = 0, from = controls.target.clone(), to = c.rooms[0], t0 = performance.now(), z0 = camera.zoom;
    const step = () => {
      const k = Math.min(1, (performance.now() - t0) / 1400), e = k * k * (3 - 2 * k);
      const delta = from.clone().lerp(to, e).sub(controls.target);
      controls.target.add(delta); camera.position.add(delta);
      camera.zoom = z0 + (2.1 - z0) * e; camera.updateProjectionMatrix();
      if (k < 1) raf = requestAnimationFrame(step);
    };
    const next = () => { from = controls.target.clone(); to = c.rooms[i++ % c.rooms.length]; t0 = performance.now(); z0 = camera.zoom; step(); };
    next();
    const id = setInterval(next, 3200);
    return () => { clearInterval(id); cancelAnimationFrame(raf); };
  }, [mode]);

  useEffect(() => { if (resetKey) ctl.current?.home(); }, [resetKey]);

  return <div ref={host} className="o3-host" aria-label="3D ofis görünümü. Fareyle yakınlaştırın ve kaydırın." />;
}
