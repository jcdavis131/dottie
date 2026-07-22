// BLUEHENRE campus — Austin, TX. Sims/RCT-2010-grade visual layer (BLUEHENRE SPEC "World").
// All three.js scene construction lives here; main.mjs owns input + game state.
//
// CONTRACT (do not break — main.mjs + ecosystem.mjs depend on it):
//   - DEPARTMENTS order/ids fixed: ecosystem circuits derive angles from the index.
//   - Buildings sit on the ring at r=40, NPC homes at r=24, SAME angle formula.
//   - buildWorld(scene) -> { player, npcs, terminals, buildings, animate(dt, t) }.
//     main sets npc/player .position x/z only, so every actor Group has its origin
//     at ground level. Terminal positions stay [6,0] [-6,4] [0,-7] (onTerminal <2.2).
//   - This module is render-only: no game logic, no network, no wall-clock; the
//     deterministic seed below keeps the campus byte-identical across loads.
import * as THREE from "three";

// Each department IS a real Dottie subsystem, staffed by its resident expert
// (SPEC "the Dottie digital twin"). ids/colors/order stay contract-frozen; the
// labels/experts are the twin mapping.
export const DEPARTMENTS = [
  { id: "labs", label: "Foundation Training Lab", color: 0x93c47d,
    expert: "foundation LLM training (ava-factory trainer)" },
  { id: "design", label: "Skills Ecosystem Studio", color: 0x6fa8dc,
    expert: "skills ecosystem (ava-skills + scout plugins)" },
  { id: "finance", label: "Compute & Fleet Ops", color: 0xe06666,
    expert: "infra & compute budgeting (16GB box, GPU, fleet)" },
  { id: "archives", label: "Data Curation & Archives", color: 0x8e7cc3,
    expert: "data curation & curriculum (datagen)" },
  { id: "servers", label: "Collector Farm", color: 0xf6b26b,
    expert: "data collection (collector fleet)" },
  { id: "hall", label: "The Great Hall", color: 0xffd966,
    expert: "org commons — all-hands and memo hub" },
  { id: "gardens", label: "Memory & Router Gardens", color: 0x76d7a5,
    expert: "memory architecture (router + per-NPC stores)" },
  { id: "proving", label: "Eval Harness Proving Grounds", color: 0x76a5af,
    expert: "evals & measurement (run_harness + open-harness)" },
];

// deterministic PRNG (mulberry32) — a reproducible campus, per repo discipline
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// dithering:true on every material — smooth gradients break into the ordered
// noise that reads as 16-bit shading once the low-res pixel grid lands on it
const lambert = (color, extra = {}) =>
  new THREE.MeshLambertMaterial({ color, dithering: true, ...extra });

function shadowed(mesh, cast = true, receive = true) {
  mesh.castShadow = cast;
  mesh.receiveShadow = receive;
  return mesh;
}

// ---- procedural canvas textures (crisp NearestFilter = the 2010 tycoon look) ----

function canvasTexture(w, h, draw) {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  draw(c.getContext("2d"));
  const tex = new THREE.CanvasTexture(c);
  tex.magFilter = THREE.NearestFilter;
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

const hex = (n) => `#${n.toString(16).padStart(6, "0")}`;

function facadeTexture(wallColor, floors, cols, r, { glass = false } = {}) {
  return canvasTexture(cols * 24, floors * 24, (g) => {
    g.fillStyle = hex(wallColor);
    g.fillRect(0, 0, cols * 24, floors * 24);
    for (let f = 0; f < floors; f++) {
      for (let c = 0; c < cols; c++) {
        const lit = r() < 0.35;
        g.fillStyle = glass
          ? (lit ? "#ffe9a8" : "#7fb2c9")
          : (lit ? "#ffe9a8" : "#31424e");
        g.fillRect(c * 24 + 5, f * 24 + 5, 14, 12);
        g.fillStyle = "rgba(255,255,255,.25)";
        g.fillRect(c * 24 + 5, f * 24 + 5, 14, 3); // sky glint
      }
    }
  });
}

function labelTexture(text, bg) {
  return canvasTexture(256, 64, (g) => {
    g.fillStyle = hex(bg); g.fillRect(0, 0, 256, 64);
    g.fillStyle = "rgba(0,0,0,.25)"; g.fillRect(0, 52, 256, 12);
    g.fillStyle = "#ffffff"; g.font = "bold 26px system-ui, sans-serif";
    g.textAlign = "center"; g.textBaseline = "middle";
    g.fillText(text, 128, 30);
  });
}

function grassTexture() {
  // dusk-lit olive greens — sunset light on hill-country grass
  return canvasTexture(256, 256, (g) => {
    g.fillStyle = "#96a55b"; g.fillRect(0, 0, 256, 256);
    for (let i = 0; i < 8; i++) { // mowing stripes
      g.fillStyle = i % 2 ? "#8d9c54" : "#9fae62";
      g.fillRect(0, i * 32, 256, 32);
    }
    const r = rng(7);
    g.fillStyle = "#7d9150";
    for (let i = 0; i < 420; i++) g.fillRect(r() * 256, r() * 256, 2, 2);
    g.fillStyle = "#f2c98b"; // wildflowers catching the last light
    for (let i = 0; i < 40; i++) g.fillRect(r() * 256, r() * 256, 2, 2);
  });
}

// SNES sunset backdrop: hard color bands with checkerboard-dithered seams (the
// classic 16-bit gradient trick), a chunky low sun, and slab clouds. Nearest-
// filtered so every pixel stays where it was placed.
function sunsetSkyTexture() {
  const W = 160, H = 120;
  const bands = ["#2b1e4e", "#4b2a63", "#7a3b6e", "#a84a6c", "#cf6260",
                 "#e8815c", "#f29a5e", "#f7b878"];
  return canvasTexture(W, H, (g) => {
    const bh = H / bands.length;
    bands.forEach((c, i) => {
      g.fillStyle = c;
      g.fillRect(0, Math.floor(i * bh), W, Math.ceil(bh));
    });
    // dither the seams: two checkerboard rows blending each pair of bands
    for (let i = 1; i < bands.length; i++) {
      const y = Math.floor(i * bh);
      for (const [row, color] of [[y - 1, bands[i]], [y, bands[i - 1]]]) {
        g.fillStyle = color;
        for (let x = (row % 2 === 0 ? 0 : 1); x < W; x += 2) g.fillRect(x, row, 1, 1);
      }
    }
    // the low sun: chunky disc with a dithered halo ring
    const sx = Math.floor(W * 0.62), sy = Math.floor(H * 0.68);
    g.fillStyle = "#ffcf8f";
    for (let dy = -7; dy <= 7; dy++)
      for (let dx = -7; dx <= 7; dx++)
        if (dx * dx + dy * dy <= 49) g.fillRect(sx + dx, sy + dy, 1, 1);
    g.fillStyle = "#ffe9bd";
    for (let dy = -4; dy <= 4; dy++)
      for (let dx = -4; dx <= 4; dx++)
        if (dx * dx + dy * dy <= 16) g.fillRect(sx + dx, sy + dy, 1, 1);
    g.fillStyle = "#f7b878";
    for (let dy = -9; dy <= 9; dy++)
      for (let dx = -9; dx <= 9; dx++) {
        const d = dx * dx + dy * dy;
        if (d > 49 && d <= 81 && (dx + dy) % 2 === 0) g.fillRect(sx + dx, sy + dy, 1, 1);
      }
    // slab clouds, lit from below
    g.fillStyle = "#8a4a72";
    g.fillRect(10, 34, 44, 3); g.fillRect(18, 37, 30, 2);
    g.fillRect(96, 22, 52, 3); g.fillRect(104, 25, 36, 2);
    g.fillStyle = "#d97a6a";
    g.fillRect(30, 62, 56, 3); g.fillRect(40, 65, 38, 2);
    g.fillRect(112, 76, 40, 3);
  });
}

function texasFlagTexture() {
  return canvasTexture(120, 80, (g) => {
    g.fillStyle = "#ffffff"; g.fillRect(0, 0, 120, 80);
    g.fillStyle = "#bf0a30"; g.fillRect(40, 40, 80, 40);
    g.fillStyle = "#002868"; g.fillRect(0, 0, 40, 80);
    g.fillStyle = "#ffffff";
    g.save(); g.translate(20, 40);
    g.beginPath();
    for (let i = 0; i < 5; i++) {
      const a = (i * 4 * Math.PI) / 5 - Math.PI / 2;
      g[i ? "lineTo" : "moveTo"](Math.cos(a) * 12, Math.sin(a) * 12);
    }
    g.closePath(); g.fill(); g.restore();
  });
}

// ---- little builders -------------------------------------------------------

function sign(text, color) {
  const board = shadowed(new THREE.Mesh(
    new THREE.BoxGeometry(5.2, 1.4, 0.2),
    [lambert(color), lambert(color), lambert(color), lambert(color),
     new THREE.MeshLambertMaterial({ map: labelTexture(text, color) }), lambert(color)],
  ));
  board.position.y = 2.6;
  const post = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, 2.6, 8), lambert(0x5b5f66)));
  post.position.y = 1.3;
  const grp = new THREE.Group();
  grp.add(board, post);
  return grp;
}

function liveOak(r) {
  const g = new THREE.Group();
  const trunk = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(0.32, 0.5, 2.2, 7), lambert(0x6e4f35)));
  trunk.position.y = 1.1;
  g.add(trunk);
  const greens = [0x4e7d3a, 0x5d9147, 0x6aa251];
  const blobs = 3 + Math.floor(r() * 2);
  for (let i = 0; i < blobs; i++) {
    const s = 1.5 + r() * 1.3;
    const blob = shadowed(new THREE.Mesh(
      new THREE.SphereGeometry(s, 9, 7), lambert(greens[i % greens.length])));
    blob.position.set((r() - 0.5) * 2.4, 2.6 + r() * 1.4, (r() - 0.5) * 2.4);
    blob.scale.y = 0.75; // live oaks spread WIDE, not tall
    g.add(blob);
  }
  return g;
}

function lampPost() {
  const g = new THREE.Group();
  const pole = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.1, 3.4, 8), lambert(0x3d4148)));
  pole.position.y = 1.7;
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.28, 10, 8),
    new THREE.MeshLambertMaterial({ color: 0xffe4b0, emissive: 0xffc46b, emissiveIntensity: 1.6 }));
  head.position.y = 3.5;
  g.add(pole, head);
  return g;
}

function bench() {
  const g = new THREE.Group();
  const seat = shadowed(new THREE.Mesh(new THREE.BoxGeometry(1.8, 0.12, 0.55), lambert(0x9a6b43)));
  seat.position.y = 0.5;
  const back = shadowed(new THREE.Mesh(new THREE.BoxGeometry(1.8, 0.5, 0.1), lambert(0x9a6b43)));
  back.position.set(0, 0.85, -0.24);
  for (const x of [-0.7, 0.7]) {
    const leg = shadowed(new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.5, 0.5), lambert(0x424549)));
    leg.position.set(x, 0.25, 0);
    g.add(leg);
  }
  g.add(seat, back);
  return g;
}

function foodTruck(body, awning, name) {
  const g = new THREE.Group();
  const box = shadowed(new THREE.Mesh(new THREE.BoxGeometry(4.6, 2.4, 2.1), lambert(body)));
  box.position.y = 1.5;
  const cab = shadowed(new THREE.Mesh(new THREE.BoxGeometry(1.3, 1.5, 2.0), lambert(0xdadde2)));
  cab.position.set(-2.8, 1.05, 0);
  const awn = shadowed(new THREE.Mesh(new THREE.BoxGeometry(3.4, 0.12, 1.2), lambert(awning)), true, false);
  awn.position.set(0.4, 2.5, 1.4);
  awn.rotation.x = 0.35;
  const board = new THREE.Mesh(new THREE.BoxGeometry(2.6, 0.7, 0.08),
    new THREE.MeshLambertMaterial({ map: labelTexture(name, 0x2c2f33) }));
  board.position.set(0.4, 2.95, 0);
  for (const [x, z] of [[-2.6, 1.0], [-2.6, -1.0], [1.6, 1.0], [1.6, -1.0]]) {
    const wheel = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(0.42, 0.42, 0.3, 12), lambert(0x24262a)));
    wheel.rotation.x = Math.PI / 2;
    wheel.position.set(x, 0.42, z);
    g.add(wheel);
  }
  g.add(box, cab, awn, board);
  return g;
}

function car(r) {
  const palette = [0xc0392b, 0x2e86c1, 0xf4d03f, 0xf0f3f4, 0x717d7e, 0x1e8449];
  const g = new THREE.Group();
  const body = shadowed(new THREE.Mesh(new THREE.BoxGeometry(2.4, 0.55, 1.2),
    lambert(palette[Math.floor(r() * palette.length)])));
  body.position.y = 0.55;
  const cabin = shadowed(new THREE.Mesh(new THREE.BoxGeometry(1.3, 0.5, 1.05), lambert(0x9fb8c4)));
  cabin.position.set(-0.1, 1.05, 0);
  for (const [x, z] of [[-0.8, 0.62], [-0.8, -0.62], [0.8, 0.62], [0.8, -0.62]]) {
    const w = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(0.26, 0.26, 0.2, 10), lambert(0x24262a)));
    w.rotation.x = Math.PI / 2;
    w.position.set(x, 0.26, z);
    g.add(w);
  }
  g.add(body, cabin);
  return g;
}

// Sims-style minifig: legs + shirt torso + head + hair, plumbob above. Origin at
// ground so main.mjs can keep setting x/z only. userData is stamped by the caller.
// Everything except the plumbob lives in an inner "body" group so animate() can
// give walkers a gait bob without fighting main's x/z placement.
function minifig({ shirt, hair = 0x4a3324, skin = 0xe8bd93, plumbob = 0x39e75f }) {
  const g = new THREE.Group();
  const body = new THREE.Group();
  body.name = "body";
  const legs = shadowed(new THREE.Mesh(new THREE.BoxGeometry(0.55, 0.7, 0.34), lambert(0x33415c)));
  legs.position.y = 0.35;
  const torso = shadowed(new THREE.Mesh(new THREE.CapsuleGeometry(0.32, 0.5, 4, 10), lambert(shirt)));
  torso.position.y = 1.05;
  const head = shadowed(new THREE.Mesh(new THREE.SphereGeometry(0.3, 14, 12), lambert(skin)));
  head.position.y = 1.72;
  const cap = shadowed(new THREE.Mesh(new THREE.SphereGeometry(0.31, 14, 8, 0, Math.PI * 2, 0, 1.2), lambert(hair)), true, false);
  cap.position.y = 1.76;
  body.add(legs, torso, head, cap);
  const bob = new THREE.Mesh(new THREE.OctahedronGeometry(0.22),
    new THREE.MeshLambertMaterial({ color: plumbob, emissive: plumbob, emissiveIntensity: 0.55 }));
  bob.position.y = 2.45;
  bob.name = "plumbob";
  g.add(body, bob);
  return g;
}

// ---- department building archetypes (each returns a Group, origin at ground) ----

function buildingFor(d, r) {
  const g = new THREE.Group();
  const add = (m) => (g.add(m), m);
  switch (d.id) {
    case "finance": { // the tower pair — tallest thing on campus
      const t1 = add(shadowed(new THREE.Mesh(new THREE.BoxGeometry(7, 16, 7),
        new THREE.MeshLambertMaterial({ map: facadeTexture(d.color, 8, 4, r, { glass: true }) }))));
      t1.position.y = 8;
      const t2 = add(shadowed(new THREE.Mesh(new THREE.BoxGeometry(5, 10, 5),
        new THREE.MeshLambertMaterial({ map: facadeTexture(0xc9524f, 5, 3, r, { glass: true }) }))));
      t2.position.set(5.6, 5, 1.5);
      const crown = add(shadowed(new THREE.Mesh(new THREE.CylinderGeometry(0, 2.6, 2.2, 4), lambert(0xd8e4ea))));
      crown.position.y = 17.1; crown.rotation.y = Math.PI / 4; // Frost-tower nod
      break;
    }
    case "hall": { // wide gabled hall, warm — the social hub
      const base = add(shadowed(new THREE.Mesh(new THREE.BoxGeometry(13, 5, 9),
        new THREE.MeshLambertMaterial({ map: facadeTexture(d.color, 2, 6, r) }))));
      base.position.y = 2.5;
      const roof = add(shadowed(new THREE.Mesh(new THREE.CylinderGeometry(0.01, 6.6, 3, 4, 1), lambert(0xa8552f))));
      roof.position.y = 6.5; roof.rotation.y = Math.PI / 4; roof.scale.z = 1.45;
      const chimney = add(shadowed(new THREE.Mesh(new THREE.BoxGeometry(0.9, 2.4, 0.9), lambert(0x8f4a2a))));
      chimney.position.set(3.4, 6.6, 1.4);
      break;
    }
    case "archives": { // limestone classical: columns + pediment
      const base = add(shadowed(new THREE.Mesh(new THREE.BoxGeometry(9, 5.4, 7), lambert(0xd9cfae))));
      base.position.y = 2.7;
      for (let i = 0; i < 4; i++) {
        const col = add(shadowed(new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.4, 4.6, 10), lambert(0xece4c8))));
        col.position.set(-3.3 + i * 2.2, 2.3, 3.9);
      }
      const ped = add(shadowed(new THREE.Mesh(new THREE.CylinderGeometry(0.01, 5.4, 2, 3, 1), lambert(0xe4dabb))));
      ped.position.set(0, 6.3, 1.4); ped.rotation.y = Math.PI; ped.scale.z = 0.6;
      break;
    }
    case "servers": { // low bunker + ramp down + cooling stacks (subterranean farm)
      const bunker = add(shadowed(new THREE.Mesh(new THREE.BoxGeometry(10, 2.6, 8), lambert(0x9aa2ab))));
      bunker.position.y = 1.3;
      for (let i = 0; i < 3; i++) {
        const stack = add(shadowed(new THREE.Mesh(new THREE.CylinderGeometry(0.6, 0.6, 3.2, 10),
          new THREE.MeshLambertMaterial({ color: 0xb9c2cb, emissive: d.color, emissiveIntensity: 0.15 }))));
        stack.position.set(-3 + i * 3, 3.3, -2);
      }
      const ramp = add(shadowed(new THREE.Mesh(new THREE.BoxGeometry(3, 0.3, 5), lambert(0x565b61)), false, true));
      ramp.position.set(0, 0.4, 6); ramp.rotation.x = 0.24;
      break;
    }
    case "gardens": { // greenhouse: glass over frame, green blobs inside
      const glass = new THREE.MeshPhongMaterial({
        color: 0xbfe8dd, transparent: true, opacity: 0.45, shininess: 90 });
      const house = add(shadowed(new THREE.Mesh(new THREE.BoxGeometry(9, 4.2, 7), glass), true, false));
      house.position.y = 2.1;
      const roof = add(shadowed(new THREE.Mesh(new THREE.CylinderGeometry(0.01, 5.2, 2.2, 4), glass), true, false));
      roof.position.y = 5.3; roof.rotation.y = Math.PI / 4; roof.scale.z = 1.25;
      for (let i = 0; i < 5; i++) {
        const bush = add(shadowed(new THREE.Mesh(new THREE.SphereGeometry(0.8 + r() * 0.5, 9, 7), lambert(0x4f9c53))));
        bush.position.set((r() - 0.5) * 6, 0.9, (r() - 0.5) * 4.5);
      }
      break;
    }
    case "proving": { // test pad + oval track + tiny grandstand
      const pad = add(shadowed(new THREE.Mesh(new THREE.CylinderGeometry(6.4, 6.4, 0.24, 26), lambert(0x7c8a92)), false, true));
      pad.position.y = 0.12;
      const track = add(new THREE.Mesh(new THREE.TorusGeometry(4.6, 0.5, 8, 40), lambert(0x424a52)));
      track.rotation.x = Math.PI / 2; track.position.y = 0.26; track.receiveShadow = true;
      const stand = add(shadowed(new THREE.Mesh(new THREE.BoxGeometry(5, 2.4, 1.6),
        new THREE.MeshLambertMaterial({ map: facadeTexture(d.color, 2, 4, r) }))));
      stand.position.set(0, 1.2, -6.6);
      const dummy = add(shadowed(new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.8, 0.8), lambert(0xf2c14e))));
      dummy.position.set(4.6, 0.9, 0);
      break;
    }
    case "design": { // two offset color blocks + rooftop billboard
      const a = add(shadowed(new THREE.Mesh(new THREE.BoxGeometry(6.5, 6, 6),
        new THREE.MeshLambertMaterial({ map: facadeTexture(d.color, 3, 4, r) }))));
      a.position.y = 3;
      const b = add(shadowed(new THREE.Mesh(new THREE.BoxGeometry(4.5, 4, 4.5),
        new THREE.MeshLambertMaterial({ map: facadeTexture(0xe7a95e, 2, 3, r) }))));
      b.position.set(4.6, 2, -1.5);
      const bill = add(shadowed(new THREE.Mesh(new THREE.BoxGeometry(4.6, 1.6, 0.14),
        new THREE.MeshLambertMaterial({ map: labelTexture("dumbmodels.com", 0x30343b) })), true, false));
      bill.position.set(0, 7.4, 0);
      break;
    }
    default: { // labs — modern slab, rooftop AC, entrance awning
      const slab = add(shadowed(new THREE.Mesh(new THREE.BoxGeometry(9, 8, 7.5),
        new THREE.MeshLambertMaterial({ map: facadeTexture(d.color, 4, 5, r) }))));
      slab.position.y = 4;
      for (let i = 0; i < 2; i++) {
        const ac = add(shadowed(new THREE.Mesh(new THREE.BoxGeometry(1.3, 0.8, 1.3), lambert(0xb9c2cb))));
        ac.position.set(-1.6 + i * 3.2, 8.4, -1);
      }
      const awn = add(shadowed(new THREE.Mesh(new THREE.BoxGeometry(3.4, 0.2, 1.6), lambert(0x39424c)), true, false));
      awn.position.set(0, 2.6, 4.4);
    }
  }
  return g;
}

// ---- the campus ------------------------------------------------------------

export function buildWorld(scene) {
  const r = rng(0xa757e); // "Austin" seed — deterministic campus
  scene.background = sunsetSkyTexture(); // banded, dithered SNES sunset
  scene.fog = new THREE.Fog(0xe8935f, 70, 210); // dusty golden-hour haze

  // golden hour: a LOW warm sun (long cozy shadows) + lavender sky bounce
  const sun = new THREE.DirectionalLight(0xffb36b, 2.4);
  sun.position.set(60, 26, 38);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -95, right: 95, top: 95, bottom: -95, far: 260 });
  scene.add(sun,
    new THREE.HemisphereLight(0xd9a0c8, 0x8a6a4f, 0.7),
    new THREE.AmbientLight(0xffd9b0, 0.32));

  // hill-country grass, mown in stripes
  const grass = grassTexture();
  grass.wrapS = grass.wrapT = THREE.RepeatWrapping;
  grass.repeat.set(18, 18);
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(260, 260),
    new THREE.MeshLambertMaterial({ map: grass }));
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  scene.add(ground);

  // ring road + central limestone plaza
  const road = new THREE.Mesh(new THREE.RingGeometry(33.5, 38.5, 64), lambert(0x4d5359));
  road.rotation.x = -Math.PI / 2; road.position.y = 0.02; road.receiveShadow = true;
  const plaza = new THREE.Mesh(new THREE.CircleGeometry(13, 40), lambert(0xd9cfae));
  plaza.rotation.x = -Math.PI / 2; plaza.position.y = 0.03; plaza.receiveShadow = true;
  scene.add(road, plaza);

  // "Lady Bird Creek" + the bat bridge (Congress Ave nod, complete with bats)
  const water = new THREE.Mesh(new THREE.PlaneGeometry(200, 14),
    new THREE.MeshPhongMaterial({ color: 0x6b5d9e, shininess: 150, specular: 0xffb36b, transparent: true, opacity: 0.9, dithering: true }));
  water.rotation.x = -Math.PI / 2; water.rotation.z = 0.35;
  water.position.set(-38, 0.015, 74);
  water.receiveShadow = true;
  scene.add(water);
  const bridge = new THREE.Group();
  const deck = shadowed(new THREE.Mesh(new THREE.BoxGeometry(4.5, 0.5, 20), lambert(0xcdbf9d)));
  deck.position.y = 1.6;
  for (const z of [-7, 0, 7]) {
    const arch = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(1.1, 1.4, 1.6, 10), lambert(0xb8a982)));
    arch.position.set(0, 0.8, z);
    bridge.add(arch);
  }
  bridge.add(deck);
  bridge.position.set(-26, 0, 70); bridge.rotation.y = 0.35;
  scene.add(bridge);
  const bats = new THREE.Group();
  for (let i = 0; i < 12; i++) {
    const bat = new THREE.Mesh(new THREE.TetrahedronGeometry(0.22), lambert(0x23252c));
    bat.position.set(-26 + (r() - 0.5) * 12, 4 + r() * 5, 66 + (r() - 0.5) * 10);
    bats.add(bat);
  }
  scene.add(bats);

  // sidewalks: plaza -> each building
  DEPARTMENTS.forEach((_, i) => {
    const a = (i / DEPARTMENTS.length) * Math.PI * 2;
    const walk = new THREE.Mesh(new THREE.PlaneGeometry(2.4, 22), lambert(0xcfc6ad));
    walk.rotation.x = -Math.PI / 2; walk.rotation.z = -a - Math.PI / 2;
    walk.position.set(Math.cos(a) * 23.5, 0.025, Math.sin(a) * 23.5);
    walk.receiveShadow = true;
    scene.add(walk);
  });

  // department buildings on the ring (r=40 — the ecosystem's angular anchors)
  const buildings = [];
  DEPARTMENTS.forEach((d, i) => {
    const a = (i / DEPARTMENTS.length) * Math.PI * 2;
    const b = buildingFor(d, r);
    b.position.set(Math.cos(a) * 40, 0, Math.sin(a) * 40);
    b.lookAt(0, 0, 0); // storefronts face the plaza
    b.userData = d;
    const s = sign(d.label.length > 18 ? d.id.toUpperCase() : d.label, d.color);
    s.position.set(Math.cos(a) * 31, 0, Math.sin(a) * 31);
    s.lookAt(0, 2.6, 0);
    scene.add(b, s);
    buildings.push(b);
  });

  // hot-swap terminals: kiosks on the plaza (positions are part of the contract)
  const terminals = [];
  for (const [x, z] of [[6, 0], [-6, 4], [0, -7]]) {
    const t = new THREE.Group();
    const ped = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.7, 1.1, 10), lambert(0x39424c)));
    ped.position.y = 0.55;
    const screen = new THREE.Mesh(new THREE.BoxGeometry(1.4, 0.9, 0.1),
      new THREE.MeshLambertMaterial({ color: 0x66ffe0, emissive: 0x1c8f78, emissiveIntensity: 0.9 }));
    screen.position.y = 1.5; screen.rotation.x = -0.35;
    const halo = new THREE.Mesh(new THREE.RingGeometry(1.1, 1.45, 26),
      new THREE.MeshLambertMaterial({ color: 0x66ffe0, emissive: 0x1c8f78, side: THREE.DoubleSide }));
    halo.rotation.x = -Math.PI / 2; halo.position.y = 0.05;
    t.add(ped, screen, halo);
    t.position.set(x, 0, z);
    t.lookAt(0, 0, 0);
    t.position.y = 0.15; // keep the historical y so onTerminal distances are unchanged
    scene.add(t);
    terminals.push(t);
  }

  // ---- working-org layer (SPEC "Working-org visuals") ----------------------
  // Project holo-board on the plaza: live pipeline state, redrawn on change.
  const boardCanvas = document.createElement("canvas");
  boardCanvas.width = 512; boardCanvas.height = 256; // taller: the REAL dashboard lives here now
  const boardTex = new THREE.CanvasTexture(boardCanvas);
  boardTex.colorSpace = THREE.SRGBColorSpace;
  const boardGroup = new THREE.Group();
  for (const x of [-4.6, 4.6]) {
    const post = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.15, 5.2, 8), lambert(0x3d4148)));
    post.position.set(x, 2.6, 0);
    boardGroup.add(post);
  }
  const boardMesh = new THREE.Mesh(new THREE.BoxGeometry(10.4, 5.2, 0.18),
    [lambert(0x22262b), lambert(0x22262b), lambert(0x22262b), lambert(0x22262b),
     new THREE.MeshLambertMaterial({ map: boardTex, emissive: 0x8fd8ff, emissiveIntensity: 0.12, emissiveMap: boardTex }),
     lambert(0x22262b)]);
  boardMesh.position.y = 4.4;
  boardGroup.add(boardMesh);
  boardGroup.position.set(0, 0, -17); // faces the spawn/camera side
  scene.add(boardGroup);
  // Cyberpunk command-center console (operator art directive 2026-07-22):
  // high-density micro-pixel work from a fixed 32-color indexed palette, hard
  // rectangles only — zero anti-aliasing, every pixel placed on purpose.
  const PAL = {
    bg: "#05070c", panel: "#0a0e18", bezel: "#151b2b", bezelHi: "#232c44", rivet: "#3a4666",
    grid: "#0e1524", scan: "#0c1220", cyan: "#28e6ff", cyanDim: "#0f6f80", magenta: "#ff3fa8",
    amber: "#ffb02e", amberDim: "#7a5010", green: "#2eff6a", greenDim: "#0e662a",
    red: "#ff2e4d", redDim: "#6e1020", text: "#c8e6f0", textDim: "#5a7284", white: "#f0f6ff",
  };
  const fmtDur = (s) => {
    if (!Number.isFinite(s)) return "?";
    if (s < 90) return `${Math.round(s)}s`;
    if (s < 5400) return `${Math.round(s / 60)}m`;
    return `${Math.floor(s / 3600)}h${String(Math.round((s % 3600) / 60)).padStart(2, "0")}m`;
  };
  function updateProject(pl, twin = null) {
    const g = boardCanvas.getContext("2d");
    const W = 512, H = 256;
    // panel + bezel frame with corner rivets
    g.fillStyle = PAL.bg; g.fillRect(0, 0, W, H);
    g.fillStyle = PAL.bezel; g.fillRect(2, 2, W - 4, H - 4);
    g.fillStyle = PAL.panel; g.fillRect(8, 8, W - 16, H - 16);
    g.fillStyle = PAL.bezelHi; g.fillRect(2, 2, W - 4, 2); g.fillRect(2, 2, 2, H - 4);
    g.fillStyle = PAL.rivet;
    for (const [rx, ry] of [[4, 4], [W - 7, 4], [4, H - 7], [W - 7, H - 7]]) g.fillRect(rx, ry, 3, 3);
    // faint holo grid + scanlines (1px, hard)
    g.fillStyle = PAL.grid;
    for (let x = 8; x < W - 8; x += 24) g.fillRect(x, 8, 1, H - 16);
    g.fillStyle = PAL.scan;
    for (let y = 9; y < H - 8; y += 4) g.fillRect(8, y, W - 16, 1);
    g.textAlign = "left"; g.textBaseline = "top";
    // title strip
    g.fillStyle = PAL.bezel; g.fillRect(8, 8, W - 16, 26);
    g.fillStyle = PAL.magenta; g.fillRect(8, 33, W - 16, 1);
    g.fillStyle = PAL.cyan; g.font = "bold 18px monospace";
    g.fillText(`▮ PROJECT//${pl.model}${pl.shipped ? " :: SHIPPED" : ""}`, 14, 13);
    // status LEDs top-right
    for (let i = 0; i < 4; i++) {
      g.fillStyle = i < pl.stage ? PAL.green : i === pl.stage ? (pl.blocker ? PAL.red : PAL.amber) : PAL.cyanDim;
      g.fillRect(W - 20 - i * 8, 16, 5, 5);
    }
    // REAL twin readout: amber console line when local, dim when offline
    if (twin) {
      g.font = "bold 11px monospace";
      g.fillStyle = twin.source === "local" ? PAL.amber : PAL.textDim;
      g.fillText((twin.line ?? "").toUpperCase(), 14, 40);
      g.fillStyle = twin.source === "local" ? PAL.amberDim : PAL.grid;
      g.fillRect(14, 52, W - 28, 1);
    }
    // ---- REAL RUN DASHBOARD (operator 2026-07-22: the :8000 training dash-
    // board, alive in-world). Rendered ONLY from source:"local" telemetry;
    // otherwise the block says plainly that it is offline.
    const dash = twin?.source === "local" ? twin.dashboard : null;
    const top = 58;
    if (dash) {
      const modeColor =
        { training: PAL.green, running: PAL.green, recovering: PAL.amber }[dash.mode?.id] ??
        (dash.mode ? PAL.red : PAL.textDim);
      if (dash.mode) {
        g.fillStyle = modeColor; g.fillRect(14, top + 1, 8, 8);
        g.font = "bold 12px monospace"; g.fillStyle = modeColor;
        g.fillText(dash.mode.label.toUpperCase(), 27, top);
      }
      g.font = "11px monospace"; g.fillStyle = PAL.text;
      g.fillText(`STEP ${twin.step ?? "?"}  LOSS ${Number.isFinite(twin.lm) ? twin.lm.toFixed(4) : "?"}`, 14, top + 16);
      if (dash.timing)
        g.fillText(`${Number.isFinite(dash.timing.tokS) ? Math.round(dash.timing.tokS).toLocaleString() : "?"} tok/s  ETA ${fmtDur(dash.timing.etaS)}`, 14, top + 30);
      if (Number.isFinite(dash.ckptAgeS))
        g.fillText(`CKPT ${fmtDur(dash.ckptAgeS)} ago`, 14, top + 44);
      // flow gates: LED row with ids — red LED = a REAL gate is failing
      dash.gates.forEach((gt, i) => {
        g.fillStyle = gt.ok ? PAL.greenDim : PAL.red;
        g.fillRect(14 + i * 28, top + 58, 10, 10);
        g.font = "8px monospace"; g.fillStyle = gt.ok ? PAL.textDim : PAL.red;
        g.fillText(gt.id, 26 + i * 28, top + 59);
      });
      if (dash.funnel) {
        g.font = "9px monospace"; g.fillStyle = PAL.textDim;
        g.fillText(`raw ${dash.funnel.raw ?? 0} · packed ${dash.funnel.packed ?? 0} · used ${dash.funnel.consumed ?? 0} · fail ${dash.funnel.failed ?? 0}`, 14, top + 76);
      }
      // right block: run + phase progress bars, then the loss sparkline
      const rx = 180, rw = 290;
      const bar = (y, frac, label, color) => {
        g.fillStyle = PAL.grid; g.fillRect(rx, y, rw, 12);
        g.fillStyle = PAL.cyanDim; g.fillRect(rx, y, rw, 1); g.fillRect(rx, y + 11, rw, 1);
        g.fillStyle = color; g.fillRect(rx, y + 2, Math.floor(rw * Math.max(0, Math.min(1, frac))), 8);
        g.font = "9px monospace"; g.fillStyle = PAL.white;
        g.fillText(label, rx + 3, y + 2);
      };
      if (Number.isFinite(dash.run?.frac))
        bar(top, dash.run.frac,
            `RUN ${(dash.run.frac * 100).toFixed(1)}%${Number.isFinite(dash.run.total) ? ` of ${(dash.run.total / 1e9).toFixed(1)}B tok` : ""}`, PAL.cyan);
      if (Number.isFinite(dash.phase?.frac))
        bar(top + 18, dash.phase.frac,
            `${dash.phase.name.toUpperCase()} ${(dash.phase.frac * 100).toFixed(0)}%${Number.isFinite(dash.phase.seq) ? ` · SEQ ${dash.phase.seq}` : ""}`, PAL.magenta);
      if (dash.spark) {
        const sy = top + 36, sh = 56;
        g.fillStyle = PAL.grid; g.fillRect(rx, sy, rw, sh);
        const lo = Math.min(...dash.spark.lm), hi = Math.max(...dash.spark.lm);
        const span = hi - lo || 1;
        dash.spark.lm.forEach((v, i) => {
          const x = rx + Math.floor((i / Math.max(1, dash.spark.lm.length - 1)) * (rw - 3));
          const y = sy + 2 + Math.floor((1 - (v - lo) / span) * (sh - 6));
          g.fillStyle = PAL.cyanDim; g.fillRect(x, y + 2, 2, Math.max(0, sy + sh - 2 - y)); // area fill
          g.fillStyle = PAL.cyan; g.fillRect(x, y, 2, 2);
        });
        g.font = "8px monospace"; g.fillStyle = PAL.textDim;
        g.fillText(`LM LOSS  hi ${hi.toFixed(3)} · lo ${lo.toFixed(3)}`, rx + 3, sy + 2);
        g.fillText(`steps ${dash.spark.steps[0]}–${dash.spark.steps[dash.spark.steps.length - 1]}`, rx + 3, sy + sh - 10);
      }
    } else {
      g.font = "11px monospace"; g.fillStyle = PAL.textDim;
      g.fillText("REAL RUN DASHBOARD OFFLINE — renders only where the training box is reachable", 14, top + 2);
    }
    // stage gauges (the game's own pipeline), compressed below the dashboard
    pl.stages.forEach((s, i) => {
      const y = 152 + i * 16;
      const frac = i < pl.stage ? 1 : i > pl.stage ? 0 : Math.min(1, pl.progress / s.work);
      g.font = "10px monospace";
      g.fillStyle = i === pl.stage ? PAL.white : PAL.text;
      g.fillText(s.label.toUpperCase(), 14, y + 1);
      g.fillStyle = PAL.grid; g.fillRect(170, y, 300, 10);
      g.fillStyle = PAL.cyanDim;
      g.fillRect(170, y, 300, 1); g.fillRect(170, y + 9, 300, 1);
      const fill = Math.floor(300 * frac);
      g.fillStyle = i === pl.stage && pl.blocker ? PAL.red : PAL.cyan;
      g.fillRect(170, y + 2, fill, 6);
      if (fill > 2) { // hard highlight row = sub-pixel sheen
        g.fillStyle = i === pl.stage && pl.blocker ? "#ff8093" : "#a8f4ff";
        g.fillRect(170, y + 2, fill, 1);
      }
      g.fillStyle = PAL.panel;
      for (let t = 1; t < 10; t++) g.fillRect(170 + t * 30, y + 2, 1, 6);
      g.fillStyle = PAL.textDim; g.fillText(String(Math.floor(frac * 100)).padStart(3) + "%", 476, y + 1);
    });
    // alert strip: hazard-striped blocker readout
    if (pl.blocker) {
      g.fillStyle = PAL.redDim; g.fillRect(8, H - 22, W - 16, 14);
      g.fillStyle = PAL.red;
      for (let x = 8; x < W - 8; x += 12) g.fillRect(x, H - 22, 6, 2);
      g.font = "bold 11px monospace";
      g.fillText(`⚠ ${pl.blocker.label} → ${pl.blocker.persona}/${pl.blocker.action} @ ${pl.blocker.dept}`.toUpperCase(), 14, H - 19);
    }
    boardTex.needsUpdate = true;
  }

  // Per-department status beacons: green pulse = working, red pulse = blocked.
  const beaconHeights = { labs: 10, design: 9, finance: 19.5, archives: 8.5,
                          servers: 6, hall: 9.5, gardens: 7.5, proving: 6.5 };
  const beacons = new Map();
  DEPARTMENTS.forEach((d, i) => {
    const a = (i / DEPARTMENTS.length) * Math.PI * 2;
    const orb = new THREE.Mesh(new THREE.SphereGeometry(0.55, 12, 10),
      new THREE.MeshLambertMaterial({ color: 0x39424c, emissive: 0x000000, emissiveIntensity: 1 }));
    orb.position.set(Math.cos(a) * 40, beaconHeights[d.id] ?? 9, Math.sin(a) * 40);
    scene.add(orb);
    beacons.set(d.id, { mesh: orb, status: "idle" });
  });
  function setDeptStatus(dept, status) {
    const b = beacons.get(dept);
    if (b) b.status = status; // "working" | "blocked" | "idle" — pulsed in animate()
  }

  // ---- HUB PANELS (operator 2026-07-22: all of :8000 in-world) -------------
  // One mini-board per subsystem department, mounted by its building: walking
  // the campus IS browsing the hub. Drawn ONLY from real published telemetry
  // (parseHub display models); otherwise each shows an honest offline line.
  const HUB_PANELS = [
    { dept: "labs", key: "network", title: "NETWORK//ARCH" },
    { dept: "design", key: "ecosystem", title: "SKILLS//ECOSYSTEM" },
    { dept: "proving", key: "evals", title: "EVAL//REPORT" },
    { dept: "hall", key: "research", title: "RESEARCH//LOOP" },
  ];
  const hubPanels = HUB_PANELS.map((spec) => {
    const canvas = document.createElement("canvas");
    canvas.width = 256; canvas.height = 128;
    const tex = new THREE.CanvasTexture(canvas);
    tex.magFilter = THREE.NearestFilter;
    tex.colorSpace = THREE.SRGBColorSpace;
    const grp = new THREE.Group();
    const post = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.13, 2.4, 8), lambert(0x3d4148)));
    post.position.y = 1.2;
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(5.6, 2.8, 0.14),
      [lambert(0x151b2b), lambert(0x151b2b), lambert(0x151b2b), lambert(0x151b2b),
       new THREE.MeshLambertMaterial({ map: tex, emissive: 0x8fd8ff, emissiveIntensity: 0.1, emissiveMap: tex }),
       lambert(0x151b2b)]);
    mesh.position.y = 3.2;
    grp.add(post, mesh);
    const i = DEPARTMENTS.findIndex((d) => d.id === spec.dept);
    const a = (i / DEPARTMENTS.length) * Math.PI * 2 + 0.16;
    grp.position.set(Math.cos(a) * 34.5, 0, Math.sin(a) * 34.5);
    grp.lookAt(0, 3.2, 0);
    scene.add(grp);
    return { ...spec, canvas, tex };
  });
  function drawHubPanel(p, lines) {
    const g = p.canvas.getContext("2d");
    const W = 256, H = 128;
    g.fillStyle = PAL.bg; g.fillRect(0, 0, W, H);
    g.fillStyle = PAL.panel; g.fillRect(3, 3, W - 6, H - 6);
    g.fillStyle = PAL.bezelHi; g.fillRect(3, 3, W - 6, 1); g.fillRect(3, 3, 1, H - 6);
    g.fillStyle = PAL.scan;
    for (let y = 4; y < H - 3; y += 4) g.fillRect(3, y, W - 6, 1);
    g.textAlign = "left"; g.textBaseline = "top";
    g.fillStyle = PAL.bezel; g.fillRect(3, 3, W - 6, 18);
    g.fillStyle = PAL.magenta; g.fillRect(3, 20, W - 6, 1);
    g.fillStyle = PAL.cyan; g.font = "bold 12px monospace";
    g.fillText(`▮ ${p.title}`, 8, 6);
    g.font = "11px monospace";
    lines.slice(0, 7).forEach(([text, color], i) => {
      g.fillStyle = color ?? PAL.text;
      g.fillText(String(text).slice(0, 36), 8, 26 + i * 14);
    });
    p.tex.needsUpdate = true;
  }
  /** hubModel = twin.parseHub output (or null when offline/unlocal). */
  function updateHubPanels(hubModel) {
    for (const p of hubPanels) {
      const m = hubModel?.[p.key];
      if (!m) {
        drawHubPanel(p, [["feed offline — this build cannot", PAL.textDim],
                         ["see the training box", PAL.textDim]]);
        continue;
      }
      if (p.key === "network") drawHubPanel(p, [
        [`preset ${m.preset} · ${m.mlp}`, PAL.white],
        [m.params ? `${(m.params / 1e6).toFixed(1)}M params` : "params ?", PAL.amber],
        [`d_model ${m.dModel} · ${m.heads} heads`],
        [`${m.layers} layers${m.split ? ` (${m.split})` : ""}`],
      ]);
      else if (p.key === "ecosystem") drawHubPanel(p, [
        [`tools built ${m.toolsBuilt ?? "?"}/${m.toolsTotal ?? "?"}`, PAL.white],
        [`skills ${m.skillsTotal ?? "?"} (${m.skillsOwn ?? "?"} own)`, PAL.amber],
        ...m.agentEval.map((r) => [`${r.model}: ${r.success}/${r.tasks} ok`, PAL.text]),
      ]);
      else if (p.key === "evals") drawHubPanel(p, [
        [`verdicts: ${m.pass} PASS / ${m.fail} FAIL`, m.fail ? PAL.red : PAL.green],
        [m.preset ? `preset ${m.preset}` : "", PAL.text],
        [m.wallS ? `wall ${Math.round(m.wallS)}s · cuda` : "", PAL.textDim],
      ]);
      else if (p.key === "research") drawHubPanel(p, [
        [`${m.metric}`, PAL.white],
        [m.value !== null ? `baseline ${m.value.toFixed(4)}${m.sem ? ` ±${m.sem.toFixed(3)}` : ""}` : "no baseline", PAL.amber],
        [`provenance: ${m.provenance}`, PAL.textDim],
        [`pending ${m.pending ?? "?"} · sota ${m.sota ?? "?"} · rejected ${m.rejected ?? "?"}`],
      ]);
    }
  }
  updateHubPanels(null);

  // Memo-exchange flashes: a small pool of emissive bubbles that pop and fade.
  const memoTex = canvasTexture(64, 64, (g) => {
    g.fillStyle = "#f2e9c8"; g.fillRect(6, 14, 52, 36);
    g.strokeStyle = "#5b5f66"; g.lineWidth = 4;
    g.strokeRect(6, 14, 52, 36);
    g.beginPath(); g.moveTo(6, 14); g.lineTo(32, 36); g.lineTo(58, 14); g.stroke();
  });
  const memoPool = [];
  for (let i = 0; i < 6; i++) {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 1.6),
      new THREE.MeshBasicMaterial({ map: memoTex, transparent: true, opacity: 0, depthWrite: false }));
    m.visible = false; m.userData.life = 0;
    scene.add(m);
    memoPool.push(m);
  }
  function flashMemo(x, z) {
    const m = memoPool.find((p) => !p.visible) ?? memoPool[0];
    m.position.set(x, 3.1, z);
    m.userData.life = 1.4;
    m.visible = true;
  }

  // ---- EARTH TWIN satellite board (operator art directive 2026-07-22) -------
  // Top-down orthographic satellite view, 90s weather-satellite aesthetic:
  // natural 32-color palette (muted greens, deep dithered blues, soft cloud
  // whites), reef shallows on every coast, swirling comma-shaped cloud systems,
  // thin tracking overlay. Hard pixels only; redrawn at 2Hz for clouds/sats.
  const earthCanvas = document.createElement("canvas");
  earthCanvas.width = 320; earthCanvas.height = 160;
  const earthTex = new THREE.CanvasTexture(earthCanvas);
  earthTex.magFilter = THREE.NearestFilter;
  earthTex.colorSpace = THREE.SRGBColorSpace;
  const SAT = { // natural indexed palette — the 90s GOES look
    deep: "#0b2a4a", mid: "#103a5e", shallow: "#17507a", reef: "#3fa8a0",
    lowland: "#4a7a3a", green: "#5f8b47", highland: "#8a8a56", desert: "#b09a6a",
    tundra: "#9aa48c", ice: "#dfe8ec", cloud: "#f4f8fa", cloudShade: "#c2ccd4",
    grat: "#28496b", track: "#d8e0e6", hq: "#e04040", label: "#e8eef2", frame: "#101820",
  };
  // continent plates: [x, y, w, h, biome] — a LOW-GRADE Earth (per SPEC), scaled x1.25
  const PLATES = [
    [27, 32, 43, 23, "green"], [37, 55, 20, 13, "desert"], [57, 25, 15, 10, "tundra"],  // N America
    [72, 82, 20, 33, "green"], [67, 75, 15, 13, "green"],                               // S America
    [145, 30, 22, 15, "green"], [140, 45, 13, 10, "green"],                             // Europe
    [145, 57, 33, 43, "desert"], [172, 67, 13, 20, "green"],                            // Africa
    [175, 25, 78, 33, "tundra"], [210, 55, 28, 18, "green"], [245, 65, 13, 13, "green"],// Asia
    [250, 97, 25, 15, "desert"],                                                        // Australia
    [115, 140, 112, 10, "ice"],                                                         // Antarctica
  ];
  const wr = rng(0xea27); // weather seed — deterministic systems
  const STORMS = Array.from({ length: 6 }, () => ({
    x: wr() * 320, y: 20 + wr() * 115, arms: 8 + Math.floor(wr() * 8),
    size: 5 + wr() * 7, spin: wr() < 0.5 ? 1 : -1, drift: 0.5 + wr() * 0.7,
  }));
  const tr = rng(0x5a7); // terrain speckle seed (fixed — no texture tearing)
  const SPECKS = Array.from({ length: 900 }, () => [tr(), tr(), tr()]);
  function drawEarthMap(t) {
    const g = earthCanvas.getContext("2d");
    const W = 320, H = 160;
    // dithered ocean depth bands: deep -> mid -> shallow, checkerboard seams
    g.fillStyle = SAT.deep; g.fillRect(0, 0, W, H);
    g.fillStyle = SAT.mid; g.fillRect(0, 30, W, 74);
    g.fillStyle = SAT.deep;
    for (let x = 0; x < W; x += 2) { g.fillRect(x + (30 % 2), 30, 1, 1); g.fillRect(x, 103, 1, 1); }
    g.fillStyle = SAT.shallow; g.fillRect(0, 52, W, 34);
    g.fillStyle = SAT.mid;
    for (let x = 0; x < W; x += 2) { g.fillRect(x, 52, 1, 1); g.fillRect(x + 1, 85, 1, 1); }
    // subtle graticule under everything else
    g.fillStyle = SAT.grat;
    for (let x = 0; x < W; x += 20) for (let y = 0; y < H; y += 2) g.fillRect(x, y, 1, 1);
    for (let y = 0; y < H; y += 20) for (let x = 0; x < W; x += 2) g.fillRect(x, y, 1, 1);
    // continents: reef shallows ring every coast, then biome terrain + speckle
    for (const [px, py, pw, ph] of PLATES) {
      g.fillStyle = SAT.reef; g.fillRect(px - 1, py - 1, pw + 2, ph + 2);
    }
    PLATES.forEach(([px, py, pw, ph, biome], pi) => {
      const base = { green: SAT.green, desert: SAT.desert, tundra: SAT.tundra, ice: SAT.ice }[biome];
      g.fillStyle = base; g.fillRect(px, py, pw, ph);
      // micro-pixel terrain: deterministic speckle in sister biome colors
      const sisters = { green: [SAT.lowland, SAT.highland], desert: [SAT.highland, SAT.green],
                        tundra: [SAT.ice, SAT.highland], ice: [SAT.tundra, SAT.cloudShade] }[biome];
      for (let i = pi * 60; i < pi * 60 + 60 && i < SPECKS.length; i++) {
        const [sx, sy, sc] = SPECKS[i];
        g.fillStyle = sisters[sc < 0.5 ? 0 : 1];
        g.fillRect(px + 1 + Math.floor(sx * (pw - 2)), py + 1 + Math.floor(sy * (ph - 2)), 1, 1);
      }
    });
    // swirling comma-shaped cloud systems (drift west->east, wrap) + shadows
    for (const s of STORMS) {
      const cx = (s.x + t * s.drift * 2) % (W + 40) - 20;
      for (let i = 0; i < s.arms * 4; i++) {
        const a = i * 0.42 * s.spin + t * 0.25 * s.spin;
        const rr = 1 + (i / (s.arms * 4)) * s.size;
        const x = Math.floor(cx + Math.cos(a) * rr);
        const y = Math.floor(s.y + Math.sin(a) * rr * 0.6);
        if (x < 0 || x >= W || y < 0 || y >= H) continue;
        g.fillStyle = SAT.cloudShade; g.fillRect(x + 1, y + 1, 2, 1);
        g.fillStyle = SAT.cloud; g.fillRect(x, y, 2, 1);
      }
    }
    // thin tracking overlay: one dotted ground-trace + satellite blip (90s feed)
    g.fillStyle = SAT.track;
    for (let x = 0; x < W; x += 5) {
      const y = 80 + Math.sin((x / W) * Math.PI * 2) * 48;
      g.fillRect(x, Math.floor(y), 1, 1);
    }
    const sx = Math.floor((t * 20) % W);
    const sy = Math.floor(80 + Math.sin((sx / W) * Math.PI * 2) * 48);
    g.fillRect(sx - 1, sy, 3, 1); g.fillRect(sx, sy - 1, 1, 3);
    // HQ AUSTIN: red cross marker, weather-map style
    const blink = Math.floor(t * 2) % 2 === 0;
    g.fillStyle = blink ? SAT.hq : SAT.label;
    g.fillRect(49, 51, 1, 5); g.fillRect(47, 53, 5, 1);
    g.fillStyle = SAT.label; g.font = "bold 8px monospace";
    g.textAlign = "left"; g.textBaseline = "top";
    g.fillText("HQ AUSTIN", 54, 49);
    // feed header, broadcast style
    g.fillStyle = SAT.frame; g.fillRect(0, 0, W, 12);
    g.fillStyle = SAT.label; g.font = "bold 9px monospace";
    g.fillText("EARTH TWIN · SAT VIEW · DOTTIE GLOBAL OPS", 4, 2);
    earthTex.needsUpdate = true;
  }
  drawEarthMap(0);
  const earthGroup = new THREE.Group();
  for (const x of [-5.4, 5.4]) {
    const post = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.15, 4.2, 8), lambert(0x3d4148)));
    post.position.set(x, 2.1, 0);
    earthGroup.add(post);
  }
  const earthMesh = new THREE.Mesh(new THREE.BoxGeometry(11.6, 5.8, 0.18),
    [lambert(0x151b2b), lambert(0x151b2b), lambert(0x151b2b), lambert(0x151b2b),
     new THREE.MeshLambertMaterial({ map: earthTex, emissive: 0xbcd0da, emissiveIntensity: 0.1, emissiveMap: earthTex }),
     lambert(0x151b2b)]);
  earthMesh.position.y = 4.4;
  earthGroup.add(earthMesh);
  earthGroup.position.set(17, 0, -9);
  earthGroup.lookAt(0, 0, 4); // angled toward the plaza approach
  scene.add(earthGroup);
  let earthTimer = 0;

  // Austin set dressing: live oaks, lamps, benches, food trucks, flag, water tower
  const treeSpots = [];
  for (let i = 0; i < 22; i++) {
    const a = r() * Math.PI * 2;
    const rad = 46 + r() * 40;
    const x = Math.cos(a) * rad, z = Math.sin(a) * rad;
    if (z > 55 && x < 0) continue; // keep the creek bank clear
    treeSpots.push([x, z]);
  }
  for (const [x, z] of [[14, 14], [-15, 12], [12, -14], [-13, -13], ...treeSpots]) {
    const t = liveOak(r);
    t.position.set(x, 0, z);
    t.rotation.y = r() * Math.PI * 2;
    scene.add(t);
  }
  for (let i = 0; i < 8; i++) {
    const a = (i / 8) * Math.PI * 2 + 0.4;
    const lamp = lampPost();
    lamp.position.set(Math.cos(a) * 14.5, 0, Math.sin(a) * 14.5);
    scene.add(lamp);
  }
  for (const [x, z, ry] of [[9, 8, 2.2], [-9, -6, -0.6], [3, -10, 0.4]]) {
    const bn = bench();
    bn.position.set(x, 0, z); bn.rotation.y = ry;
    scene.add(bn);
  }
  // food-truck row near the Great Hall (dept index 5 → its ring angle)
  const hallA = (5 / DEPARTMENTS.length) * Math.PI * 2;
  [["BRISKET", 0xa8552f, 0xf2c14e], ["TACOS AL PASTOR", 0x2e86c1, 0xf0f3f4], ["QUESO", 0xf4d03f, 0xbf0a30]]
    .forEach(([name, bodyC, awnC], i) => {
      const truck = foodTruck(bodyC, awnC, name);
      const rr = 27 + i * 5.4;
      truck.position.set(Math.cos(hallA + 0.42) * rr, 0, Math.sin(hallA + 0.42) * rr);
      truck.rotation.y = -hallA + Math.PI / 2;
      scene.add(truck);
    });
  // Texas flag on the plaza edge
  const flagGroup = new THREE.Group();
  const pole = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.12, 9, 8), lambert(0xd7dbe0)));
  pole.position.y = 4.5;
  const flag = new THREE.Mesh(new THREE.PlaneGeometry(3, 2),
    new THREE.MeshLambertMaterial({ map: texasFlagTexture(), side: THREE.DoubleSide }));
  flag.position.set(1.55, 7.8, 0);
  flag.name = "flag";
  flagGroup.add(pole, flag);
  flagGroup.position.set(-11, 0, -8);
  scene.add(flagGroup);
  // water tower: "ATX"
  const tower = new THREE.Group();
  for (let i = 0; i < 4; i++) {
    const a = (i / 4) * Math.PI * 2;
    const leg = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.22, 8, 8), lambert(0x8d949c)));
    leg.position.set(Math.cos(a) * 1.9, 4, Math.sin(a) * 1.9);
    leg.rotation.z = Math.cos(a) * 0.12; leg.rotation.x = -Math.sin(a) * 0.12;
    tower.add(leg);
  }
  const tank = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(2.6, 2.6, 3, 18),
    new THREE.MeshLambertMaterial({ map: labelTexture("ATX · BLUEHENRE", 0x6fa8dc) })));
  tank.position.y = 9.4;
  const cone = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(0.01, 2.8, 1.4, 18), lambert(0x557596)));
  cone.position.y = 11.6;
  tower.add(tank, cone);
  tower.position.set(52, 0, -34);
  scene.add(tower);
  // parking lot + cars (NE of the ring)
  const lot = new THREE.Mesh(new THREE.PlaneGeometry(18, 10), lambert(0x53585e));
  lot.rotation.x = -Math.PI / 2; lot.position.set(48, 0.02, 22); lot.receiveShadow = true;
  scene.add(lot);
  for (let i = 0; i < 6; i++) {
    const c = car(r);
    c.position.set(42 + (i % 3) * 5.4, 0, 19 + Math.floor(i / 3) * 5.2);
    c.rotation.y = Math.PI / 2 + (r() - 0.5) * 0.12;
    scene.add(c);
  }
  // downtown Austin skyline, hazy to the south (beyond the fog line it reads as distance)
  const skyline = new THREE.Group();
  const heights = [26, 34, 22, 40, 18, 30, 24, 36, 20];
  heights.forEach((h, i) => {
    const b = new THREE.Mesh(new THREE.BoxGeometry(7 + (i % 3) * 3, h, 8), lambert(0x5c5480));
    b.position.set(-64 + i * 15, h / 2, 128);
    skyline.add(b);
    if (h === 40) { // the tallest gets a Frost-style crown + antenna
      const crown = new THREE.Mesh(new THREE.CylinderGeometry(0, 4.4, 5, 4), lambert(0x6a6290));
      crown.position.set(b.position.x, h + 2.5, 128); crown.rotation.y = Math.PI / 4;
      const ant = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 8, 6), lambert(0x756c9c));
      ant.position.set(b.position.x, h + 9, 128);
      skyline.add(crown, ant);
    }
  });
  scene.add(skyline);

  // NPCs: one Sims-style minifig per department, shirt tinted to match; the org's
  // circuits (ecosystem.mjs) drive x/z, so groups originate at ground level.
  const npcs = DEPARTMENTS.map((d, i) => {
    const m = minifig({ shirt: d.color });
    const a = (i / DEPARTMENTS.length) * Math.PI * 2;
    m.position.set(Math.cos(a) * 25, 0, Math.sin(a) * 25);
    m.userData = { npcId: `${d.id}-1`, dept: d.id, expert: d.expert, heading: 0 };
    scene.add(m);
    return m;
  });

  // the player: visitor badge grey-blue + golden plumbob (you are not org staff)
  const player = minifig({ shirt: 0x444a5a, hair: 0x2c2320, plumbob: 0xf2c14e });
  player.position.set(0, 0, 12);
  scene.add(player);

  // cheap idle animation: plumbobs spin, bats flap-bob, flag sways, walkers get a
  // gait bob, beacons pulse their dept status, memo bubbles pop and fade
  const bobs = [player, ...npcs].map((m) => m.getObjectByName("plumbob")).filter(Boolean);
  const walkers = [player, ...npcs].map((m) => ({
    body: m.getObjectByName("body"), grp: m, lastX: m.position.x, lastZ: m.position.z,
  }));
  function animate(dt, t) {
    for (const b of bobs) {
      b.rotation.y += dt * 2.2;
      b.position.y = 2.45 + Math.sin(t * 2) * 0.06;
    }
    // gait: bob + slight forward lean while the group is actually moving
    for (const w of walkers) {
      const moved = Math.hypot(w.grp.position.x - w.lastX, w.grp.position.z - w.lastZ);
      w.lastX = w.grp.position.x; w.lastZ = w.grp.position.z;
      const moving = moved > 0.002;
      if (w.body) {
        w.body.position.y = moving ? Math.abs(Math.sin(t * 9)) * 0.1 : w.body.position.y * 0.8;
        w.body.rotation.x = moving ? 0.09 : w.body.rotation.x * 0.8;
      }
    }
    // dept beacons: working = green pulse, blocked = urgent red pulse, idle = dark
    for (const { mesh, status } of beacons.values()) {
      const m = mesh.material;
      if (status === "working") {
        m.emissive.setHex(0x39e75f);
        m.emissiveIntensity = 0.55 + Math.sin(t * 3) * 0.25;
      } else if (status === "blocked") {
        m.emissive.setHex(0xe0431f);
        m.emissiveIntensity = 0.7 + Math.sin(t * 8) * 0.3;
      } else {
        m.emissive.setHex(0x000000);
      }
    }
    // memo bubbles rise + fade
    for (const m of memoPool) {
      if (!m.visible) continue;
      m.userData.life -= dt;
      m.position.y += dt * 0.9;
      m.material.opacity = Math.max(0, Math.min(1, m.userData.life));
      if (m.userData.life <= 0) m.visible = false;
    }
    bats.children.forEach((bat, i) => {
      bat.position.y += Math.sin(t * 3 + i) * dt * 0.8;
      bat.rotation.z += dt * (i % 2 ? 1 : -1);
    });
    flag.rotation.y = Math.sin(t * 1.4) * 0.18;
    // Earth twin board: satellites + weather redraw at 2Hz (cheap 256x128 canvas)
    earthTimer += dt;
    if (earthTimer > 0.5) { earthTimer = 0; drawEarthMap(t); }
  }

  return { player, npcs, terminals, buildings, animate,
           updateProject, setDeptStatus, flashMemo, updateHubPanels };
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
