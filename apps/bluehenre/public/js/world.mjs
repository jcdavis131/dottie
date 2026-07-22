// Campus blockout — the 8 doc locations, terminals, wandering NPCs (BLUEHENRE SPEC "World").
// All three.js scene construction lives here; main.mjs owns input + game state.
import * as THREE from "three";

export const DEPARTMENTS = [
  { id: "labs", label: "Developer Labs", color: 0x93c47d },
  { id: "design", label: "Design Studio & Marketing Plazas", color: 0x6fa8dc },
  { id: "finance", label: "Finance Towers", color: 0xe06666 },
  { id: "archives", label: "Legal Archives", color: 0x8e7cc3 },
  { id: "servers", label: "Subterranean Server Farms", color: 0xf6b26b },
  { id: "hall", label: "The Great Hall & Cafeteria", color: 0xffd966 },
  { id: "gardens", label: "Botanical Gardens", color: 0x76d7a5 },
  { id: "proving", label: "Proving Grounds", color: 0x76a5af },
];

const toon = (color) => new THREE.MeshToonMaterial({ color });

export function buildWorld(scene) {
  scene.background = new THREE.Color(0xbfe3f2); // soft Ghibli sky
  scene.fog = new THREE.Fog(0xbfe3f2, 60, 160);

  const sun = new THREE.DirectionalLight(0xfff2d9, 2.2);
  sun.position.set(30, 50, 20);
  scene.add(sun, new THREE.AmbientLight(0xdfeef7, 0.9));

  const ground = new THREE.Mesh(new THREE.CircleGeometry(90, 48), toon(0x9ed08c));
  ground.rotation.x = -Math.PI / 2;
  scene.add(ground);

  // 7 department buildings on a ring
  const buildings = [];
  DEPARTMENTS.forEach((d, i) => {
    const a = (i / DEPARTMENTS.length) * Math.PI * 2;
    const h = 6 + (i % 3) * 3;
    const b = new THREE.Mesh(new THREE.BoxGeometry(10, h, 10), toon(d.color));
    b.position.set(Math.cos(a) * 40, h / 2, Math.sin(a) * 40);
    b.userData = d;
    scene.add(b);
    buildings.push(b);
  });

  // hot-swap terminals: glowing pads near center
  const terminals = [];
  for (const [x, z] of [[6, 0], [-6, 4], [0, -7]]) {
    const t = new THREE.Mesh(
      new THREE.CylinderGeometry(1.4, 1.4, 0.3, 24),
      new THREE.MeshToonMaterial({ color: 0x66ffe0, emissive: 0x1c8f78 }),
    );
    t.position.set(x, 0.15, z);
    scene.add(t);
    terminals.push(t);
  }

  // one wandering NPC sphere per department, tinted to match
  const npcs = DEPARTMENTS.map((d, i) => {
    const m = new THREE.Mesh(new THREE.SphereGeometry(0.8, 20, 16), toon(d.color));
    const a = (i / DEPARTMENTS.length) * Math.PI * 2;
    m.position.set(Math.cos(a) * 25, 0.8, Math.sin(a) * 25);
    m.userData = { npcId: `${d.id}-1`, dept: d.id, heading: Math.random() * Math.PI * 2 };
    scene.add(m);
    return m;
  });

  const player = new THREE.Mesh(new THREE.CapsuleGeometry(0.5, 1.0, 6, 12), toon(0x444a5a));
  player.position.set(0, 1.0, 12);
  scene.add(player);

  return { player, npcs, terminals, buildings };
}

// (P1's random-wander tickNpcs was removed in P2 — ecosystem.mjs circuits now
// drive every NPC, so there is exactly ONE movement system.)

export const onTerminal = (player, terminals) =>
  terminals.some((t) => player.position.distanceTo(t.position) < 2.2);

export const nearestNpc = (player, npcs, maxDist = 4) => {
  let best = null;
  let bd = maxDist;
  for (const n of npcs) {
    const d = player.position.distanceTo(n.position);
    if (d < bd) ({ best, bd } = { best: n, bd: d });
  }
  return best;
};
