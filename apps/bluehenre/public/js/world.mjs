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

const lambert = (color, extra = {}) => new THREE.MeshLambertMaterial({ color, ...extra });

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
  return canvasTexture(256, 256, (g) => {
    g.fillStyle = "#7fb765"; g.fillRect(0, 0, 256, 256);
    for (let i = 0; i < 8; i++) { // mowing stripes
      g.fillStyle = i % 2 ? "#78ae5f" : "#86bf6c";
      g.fillRect(0, i * 32, 256, 32);
    }
    const r = rng(7);
    g.fillStyle = "#6da257";
    for (let i = 0; i < 420; i++) g.fillRect(r() * 256, r() * 256, 2, 2);
    g.fillStyle = "#f2e29b"; // scattered wildflowers, hill-country style
    for (let i = 0; i < 40; i++) g.fillRect(r() * 256, r() * 256, 2, 2);
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
    new THREE.MeshLambertMaterial({ color: 0xfff2c4, emissive: 0xffe9a8, emissiveIntensity: 0.9 }));
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
  scene.background = new THREE.Color(0x9fd2ef); // big Texas sky
  scene.fog = new THREE.Fog(0x9fd2ef, 90, 230);

  // warm Texas sun + soft sky bounce
  const sun = new THREE.DirectionalLight(0xffe9c4, 2.6);
  sun.position.set(45, 70, 25);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -95, right: 95, top: 95, bottom: -95, far: 220 });
  scene.add(sun,
    new THREE.HemisphereLight(0xbfe3f7, 0xc4b48a, 0.85),
    new THREE.AmbientLight(0xe8f1f7, 0.25));

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
    new THREE.MeshPhongMaterial({ color: 0x3f8fae, shininess: 120, transparent: true, opacity: 0.9 }));
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
  boardCanvas.width = 512; boardCanvas.height = 192;
  const boardTex = new THREE.CanvasTexture(boardCanvas);
  boardTex.colorSpace = THREE.SRGBColorSpace;
  const boardGroup = new THREE.Group();
  for (const x of [-4.6, 4.6]) {
    const post = shadowed(new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.15, 4.6, 8), lambert(0x3d4148)));
    post.position.set(x, 2.3, 0);
    boardGroup.add(post);
  }
  const boardMesh = new THREE.Mesh(new THREE.BoxGeometry(10, 3.75, 0.18),
    [lambert(0x22262b), lambert(0x22262b), lambert(0x22262b), lambert(0x22262b),
     new THREE.MeshLambertMaterial({ map: boardTex, emissive: 0x8fd8ff, emissiveIntensity: 0.12, emissiveMap: boardTex }),
     lambert(0x22262b)]);
  boardMesh.position.y = 4.1;
  boardGroup.add(boardMesh);
  boardGroup.position.set(0, 0, -17); // faces the spawn/camera side
  scene.add(boardGroup);
  function updateProject(pl) {
    const g = boardCanvas.getContext("2d");
    g.fillStyle = "#101418"; g.fillRect(0, 0, 512, 192);
    g.fillStyle = "#8fd8ff"; g.font = "bold 30px system-ui, sans-serif";
    g.textAlign = "left"; g.textBaseline = "top";
    g.fillText(`PROJECT: ${pl.model}${pl.shipped ? " — SHIPPED" : ""}`, 16, 10);
    pl.stages.forEach((s, i) => {
      const y = 56 + i * 26;
      const frac = i < pl.stage ? 1 : i > pl.stage ? 0 : Math.min(1, pl.progress / s.work);
      g.font = "16px system-ui, sans-serif";
      g.fillStyle = "#d9f3ec"; g.fillText(s.label, 16, y);
      g.fillStyle = "#2c333a"; g.fillRect(170, y + 2, 300, 14);
      g.fillStyle = i === pl.stage && pl.blocker ? "#e0662a" : "#39e75f";
      g.fillRect(170, y + 2, 300 * frac, 14);
      g.fillStyle = "#9fb3c8"; g.fillText(`${Math.floor(frac * 100)}%`, 478, y);
    });
    if (pl.blocker) {
      g.fillStyle = "#e0662a"; g.font = "bold 15px system-ui, sans-serif";
      g.fillText(`BLOCKED: ${pl.blocker.label} — ${pl.blocker.persona}/${pl.blocker.action} @ ${pl.blocker.dept}`, 16, 172);
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
    const b = new THREE.Mesh(new THREE.BoxGeometry(7 + (i % 3) * 3, h, 8), lambert(0x7d97ad));
    b.position.set(-64 + i * 15, h / 2, 128);
    skyline.add(b);
    if (h === 40) { // the tallest gets a Frost-style crown + antenna
      const crown = new THREE.Mesh(new THREE.CylinderGeometry(0, 4.4, 5, 4), lambert(0x8fa9bd));
      crown.position.set(b.position.x, h + 2.5, 128); crown.rotation.y = Math.PI / 4;
      const ant = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 8, 6), lambert(0x9db4c6));
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
    m.userData = { npcId: `${d.id}-1`, dept: d.id, heading: 0 };
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
  }

  return { player, npcs, terminals, buildings, animate,
           updateProject, setDeptStatus, flashMemo };
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
