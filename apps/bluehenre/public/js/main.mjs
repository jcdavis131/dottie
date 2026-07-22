// BLUEHENRE — glue: input (touch-first + keyboard), loop, HUD, quests, ecosystem,
// honest NPC chat. Mobile-first per SPEC "Presentation & input": touch is the
// default; keyboard is the desktop enhancement; both drive the SAME handlers.
import * as THREE from "three";
import { buildWorld, onTerminal, nearestNpc } from "./world.mjs";
import { createBandwidth, spend, tick as bwTick, resetRun } from "./bandwidth.mjs";
import { PERSONAS, createPlayer, hotSwap } from "./persona.mjs";
import { createRouter, remember, route, wipe } from "./router.mjs";
import { createEcosystem, tickEcosystem } from "./ecosystem.mjs";
import { createQuestLog, advance, briefs, ORG } from "./quests.mjs";
import { createRun, record, recordQuestComplete, extractRun } from "./workflow.mjs";
import { createTouchControls } from "./touch.mjs";
import { createPipeline, tickPipeline, resolveBlocker, statusLine } from "./pipeline.mjs";
import { twinLine } from "./twin.mjs";

const coarse = matchMedia("(pointer: coarse)").matches; // phone/tablet = default profile

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(70, innerWidth / innerHeight, 0.1, 400);
// 32-bit PS1 presentation (SPEC visual bar): render at 1/PIXEL_SCALE internal
// resolution (~320p-class, a generation finer than the SNES pass) and let CSS
// upscale nearest-neighbor. Materials keep dithering:true; the PS1 facet+wobble
// pass below completes the look.
const PIXEL_SCALE = 2;
const renderer = new THREE.WebGLRenderer({ antialias: false });
renderer.setPixelRatio(1);
const sizeToPixelGrid = () => {
  renderer.setSize(Math.floor(innerWidth / PIXEL_SCALE), Math.floor(innerHeight / PIXEL_SCALE), false);
  renderer.domElement.style.width = "100%";
  renderer.domElement.style.height = "100%";
};
sizeToPixelGrid();
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.12;
document.body.appendChild(renderer.domElement);
addEventListener("resize", () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  sizeToPixelGrid();
});

const world = buildWorld(scene);
// perf budget (SPEC): phones get the 1024 shadow map, desktop keeps 2048
if (coarse)
  scene.traverse((o) => { if (o.isDirectionalLight && o.shadow) o.shadow.mapSize.set(1024, 1024); });

// ---- 32-bit PS1 pass (SPEC visual bar) --------------------------------------
// One sweep over every material in the built scene: faceted Gouraud-style
// shading (flatShading — spheres/cylinders show their polys like real PSX
// geometry) + the signature vertex wobble: clip-space positions snap to a
// coarse 320x240 virtual grid, so geometry jitters subtly as the camera moves.
const PS1_SNAP = `#include <project_vertex>
  {
    vec2 ps1Grid = vec2(320.0, 240.0);
    gl_Position.xy = floor(gl_Position.xy / gl_Position.w * ps1Grid + 0.5) / ps1Grid * gl_Position.w;
  }`;
scene.traverse((o) => {
  if (!o.isMesh) return;
  for (const m of Array.isArray(o.material) ? o.material : [o.material]) {
    if ("flatShading" in m) m.flatShading = true;
    m.dithering = true;
    m.onBeforeCompile = (s) => {
      s.vertexShader = s.vertexShader.replace("#include <project_vertex>", PS1_SNAP);
    };
    m.customProgramCacheKey = () => "ps1"; // shared snap variant, dedupe programs
    m.needsUpdate = true;
  }
});
const bw = createBandwidth(100);
const me = createPlayer("auditor");
const router = createRouter(world.npcs.map((n) => n.userData.npcId));
// P2: NPCs follow org circuits (home → Great Hall → peer) instead of random wander
const eco = createEcosystem(world.npcs.map((n) => n.userData.dept));
const questLog = createQuestLog();
let run = createRun(Number(localStorage.getItem("bluehenre.runId") || 1));
// The Project: each run is a fresh consulting engagement, seeded by run id so a
// replayed run meets the same blockers (SPEC "The Project").
let pl = createPipeline(run.runId);
// REAL twin telemetry (SPEC "the Dottie digital twin"): poll the status endpoint;
// numbers render ONLY when source is "local" — twinLine enforces the doctrine.
let twin = null;
async function fetchTwin() {
  try {
    const r = await fetch("/api/twin-status");
    const s = await r.json();
    twin = { ...s, line: twinLine(s) };
  } catch {
    twin = { source: "offline", line: twinLine(null) };
  }
  world.updateProject(pl, twin);
}
fetchTwin();
setInterval(fetchTwin, 60_000);
world.updateProject(pl, twin);

const hud = document.getElementById("hud");
const questsPanel = document.getElementById("quests");
const questsEl = document.getElementById("questbody");
const log = document.getElementById("log");
const say = (line) => {
  const p = document.createElement("p");
  p.textContent = line; // textContent only — no markup injection from any source
  log.prepend(p);
  while (log.childNodes.length > (coarse ? 4 : 8)) log.lastChild.remove();
};

const renderQuests = () => {
  questsEl.textContent = briefs(questLog)
    .map((b) => `▢ ${b.quest}: ${b.next}`)
    .concat(questLog.completed.map((q) => `✓ ${q}`))
    .join("\n") || "all quest lines complete";
};
// quest tracker: collapsed-by-default on phones, tap the chip to toggle
if (coarse) questsPanel.classList.add("collapsed");
const toggleQuests = (e) => { e.preventDefault(); questsPanel.classList.toggle("collapsed"); };
const questsToggle = document.getElementById("queststoggle");
questsToggle.addEventListener("click", toggleQuests);
questsToggle.addEventListener("touchstart", toggleQuests, { passive: false });

const keys = new Set();
addEventListener("keydown", (e) => keys.add(e.key.toLowerCase()));
addEventListener("keyup", (e) => keys.delete(e.key.toLowerCase()));

// ---- ONE action system: these handlers serve keyboard AND touch --------------

const order = Object.keys(PERSONAS);
function swapTo(i) {
  const target = order[i];
  if (!target) return;
  const term = onTerminal(world.player, world.terminals);
  const sw = hotSwap(me, target, { onTerminal: term });
  if (!sw.ok) return say(`swap → ${target}: ${sw.reason}`);
  const sp = spend(bw, "hot_swap", me.persona);
  record(run, { action: "hot_swap", persona: me.persona, ok: sp.ok, cost: sp.cost });
  say(sp.ok ? `now ${PERSONAS[target].label}` : `swap denied: ${sp.reason}`);
}

async function useAbility() {
  const npc = nearestNpc(world.player, world.npcs);
  if (!npc) return say("no NPC in range");
  const action = PERSONAS[me.persona].ability;
  const dept = npc.userData.dept;
  const sp = spend(bw, action, me.persona);
  record(run, { action, persona: me.persona, dept, ok: sp.ok,
                cost: sp.cost, note: sp.ok ? "" : sp.reason });
  if (!sp.ok) return say(`${action} denied: ${sp.reason}`);

  const q = advance(questLog, { persona: me.persona, action, dept });
  for (const a of q.advanced) say(`quest ${a.quest}: step ${a.step + 1} done`);
  for (const c of q.completed) {
    recordQuestComplete(run, c);
    say(`QUEST COMPLETE: ${c} — workflow marked for extraction at run end`);
  }
  renderQuests();

  // consulting: the same ability attempt can clear the project's active blocker
  const rb = resolveBlocker(pl, { persona: me.persona, action, dept });
  if (rb.ok) {
    bw.value = Math.min(bw.max, bw.value + rb.retainer);
    record(run, { action: "resolve_blocker", persona: me.persona, dept, ok: true, cost: -rb.retainer });
    say(`BLOCKER CLEARED — retainer +${rb.retainer} bandwidth. The org resumes.`);
    world.updateProject(pl, twin);
  } else if (pl.blocker && dept === pl.blocker.dept) {
    say(`blocker unmoved: ${rb.reason}`);
  }

  const prompt = `${action} request from ${PERSONAS[me.persona].label} to the resident expert on ${npc.userData.expert ?? dept}`;
  remember(router, npc.userData.npcId, prompt);
  say(`${action} → ${npc.userData.npcId} (cost ${sp.cost}) …`);
  try {
    const r = await fetch("/api/npc-chat", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ npc: npc.userData.npcId, dept, prompt }),
    });
    const d = await r.json();
    // Provenance-honest: the server marks source "dottie" or "offline"; we show which.
    say(`${npc.userData.npcId} [${d.source}]: ${d.reply}`);
  } catch {
    say(`${npc.userData.npcId} [offline]: chat backend unreachable`);
  }
}

function queryRouter() {
  const hits = route(router, "request interview decode replan sync status");
  say(hits.length
    ? `router[${hits[0].kind}]: ${hits.slice(0, 4).map((h) => `${h.npcId}:${h.score}`).join("  ")}`
    : "router: no org memories match");
}

// V = observe mode (RollerCoaster-Tycoon view): pull up to a slow aerial orbit and
// just WATCH the org at work — circuits, hall meetings, memo traffic. Player input
// is parked; the ecosystem keeps running because it never depended on the player.
let observe = false;
let orbitA = 0;
function toggleObserve() {
  observe = !observe;
  say(observe ? "observe mode — the org runs itself; V to return" : "back on the ground");
}

// Run-end reset — extract THEN wipe, honestly reporting validated vs discarded.
let resetLatch = false;
async function endRun() {
  const extraction = extractRun(run);
  const wiped = wipe(router); // the wipe is real now, not just a log line
  say(`run #${run.runId} over — ${extraction.validated ? "VALIDATED" : "discarded"}: ${extraction.reason}`);
  try {
    const r = await fetch("/api/extract-run", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(extraction),
    });
    const d = await r.json();
    say(`extraction: ${d.detail}`);
  } catch {
    say("extraction: server unreachable — transcript lost with the session (honest wipe)");
  }
  const stats = resetRun(bw);
  run = createRun(run.runId + 1);
  localStorage.setItem("bluehenre.runId", String(run.runId));
  pl = createPipeline(run.runId); // a fresh engagement for the new run
  world.updateProject(pl, twin);
  say(`fresh run #${run.runId} — spent ${stats.spentTotal.toFixed(0)} bw last run; ${wiped.wiped} memories wiped`);
}
function tryReset() {
  if (!bw.runOver || resetLatch) return;
  resetLatch = true;
  endRun().finally(() => (resetLatch = false));
}

// keyboard bindings → the shared handlers
addEventListener("keydown", (e) => {
  const i = ["1", "2", "3"].indexOf(e.key);
  if (i !== -1) return swapTo(i);
  const k = e.key.toLowerCase();
  if (k === "e") useAbility();
  else if (k === "q") queryRouter();
  else if (k === "v") toggleObserve();
});

// touch controls: rendered ONLY on coarse pointers (SPEC mobile-first)
const touch = coarse
  ? createTouchControls(document.body, {
      onAbility: useAbility, onRouter: queryRouter,
      onObserve: toggleObserve, onSwap: swapTo, onReset: tryReset,
    })
  : null;

let last = performance.now();
let boardTimer = 0;
function frame(now) {
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;

  const p = world.player.position;
  if (!observe) {
    // merge keyboard + joystick into one analog move vector (unit-clamped)
    const stick = touch ? touch.getStick() : { x: 0, z: 0, mag: 0, sprint: false };
    let mx = (keys.has("d") ? 1 : 0) - (keys.has("a") ? 1 : 0) + stick.x;
    let mz = (keys.has("s") ? 1 : 0) - (keys.has("w") ? 1 : 0) + stick.z;
    const len = Math.hypot(mx, mz);
    if (len > 1) { mx /= len; mz /= len; }
    const sprint = keys.has("shift") || stick.sprint;
    const v = sprint ? 14 : 7;
    p.x += mx * v * dt;
    p.z += mz * v * dt;
    if (sprint && len > 0.05) spend(bw, "move_fast", me.persona);
  }

  // P2 ecosystem: circuits drive the meshes; memos land in BOTH buckets.
  // This never depends on the player — which is exactly what observe mode shows.
  const exchanges = tickEcosystem(eco, dt);
  world.npcs.forEach((n, i) => {
    n.position.x = eco.npcs[i].pos[0];
    n.position.z = eco.npcs[i].pos[1];
  });
  for (const x of exchanges) {
    remember(router, x.a, x.memo);
    remember(router, x.b, x.memo);
    // observe mode narrates ALL org traffic; on the ground you only overhear some
    if (observe || Math.random() < 0.3) say(`overheard: ${x.memo}`);
    // a memo bubble pops where the two NPCs met
    const ai = eco.npcs.findIndex((n) => n.id === x.a);
    if (ai >= 0) world.flashMemo(eco.npcs[ai].pos[0], eco.npcs[ai].pos[1]);
  }
  bwTick(bw, dt * 2);

  // The Project: NPCs at their home post do the work; the consultant clears blockers.
  const atPost = eco.npcs
    .filter((n) => Math.hypot(n.pos[0] - n.stops[0][0], n.pos[1] - n.stops[0][1]) < 3)
    .map((n) => n.dept);
  for (const e of tickPipeline(pl, dt, atPost)) {
    if (e.type === "blocked")
      say(`PROJECT BLOCKED @ ${e.dept}: ${e.label} — needs ${e.persona}/${e.action}`);
    else if (e.type === "stage_done") say(`project: ${e.stage} stage complete`);
    else if (e.type === "shipped") {
      recordQuestComplete(run, `ship_${pl.model}`);
      say(`🚢 ${pl.model} SHIPPED — engagement validated; end the run to extract it`);
    }
    world.updateProject(pl, twin);
  }
  // dept beacons mirror the pipeline every frame: done/idle dark, current green/red
  pl.stages.forEach((s, i) => {
    world.setDeptStatus(s.dept,
      i === pl.stage ? (pl.blocker ? "blocked" : "working") : "idle");
  });
  boardTimer += dt;
  if (boardTimer > 0.5 && !pl.shipped && !pl.blocker) { boardTimer = 0; world.updateProject(pl, twin); }

  world.animate?.(dt, now / 1000); // plumbobs, bats, the flag — pure set dressing

  if (observe) {
    // tycoon view: slow aerial orbit of the whole campus
    orbitA += dt * 0.12;
    camera.position.set(Math.cos(orbitA) * 70, 55, Math.sin(orbitA) * 70);
    camera.lookAt(0, 0, 0);
  } else {
    // portrait-aware follow framing: taller + farther when the screen is upright
    const portrait = camera.aspect < 1;
    camera.position.set(p.x, portrait ? 18 : 14, p.z + (portrait ? 23 : 18));
    camera.lookAt(p.x, 0, p.z);
  }

  const term = onTerminal(world.player, world.terminals);
  touch?.setTerminal(term && !bw.runOver);
  touch?.setRunOver(bw.runOver);
  hud.textContent = observe
    ? `${ORG.name} — ${ORG.hq} | OBSERVE — the org at work (${eco.memos} memos) | ${statusLine(pl)} | V=return`
    : `${statusLine(pl)} | ${PERSONAS[me.persona].label} | bw ${bw.value.toFixed(0)}/${bw.max}` +
      (term ? (coarse ? " | TERMINAL: tap 1/2/3" : " | TERMINAL: 1=auditor 2=cipher 3=architect") : "") +
      (bw.runOver ? (coarse ? " | RUN OVER — tap R (session wipes)" : " | RUN OVER — R resets (session wipes)")
                  : (coarse ? "" : " | E=ability Q=router V=observe Shift=sprint"));
  if (bw.runOver && keys.has("r")) tryReset();

  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
renderQuests();
say(`${ORG.name}: "${ORG.mission}" — ${ORG.platform}`);
say(`engagement #${run.runId}: the org is building ${pl.model} — watch the board, clear its blockers`);
say(coarse
  ? `you are the hired consultant. Left stick walks (full tilt sprints); E=your hat's move. Router: ${router.kind}`
  : `you are the hired consultant. WASD to move; E=your hat's move. Router: ${router.kind}`);
