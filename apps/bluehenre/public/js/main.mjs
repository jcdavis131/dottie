// BLUEHENRE — glue: input, loop, HUD, quests, ecosystem, honest NPC chat.
import * as THREE from "three";
import { buildWorld, onTerminal, nearestNpc } from "./world.mjs";
import { createBandwidth, spend, tick as bwTick, resetRun } from "./bandwidth.mjs";
import { PERSONAS, createPlayer, hotSwap } from "./persona.mjs";
import { createRouter, remember, route, wipe } from "./router.mjs";
import { createEcosystem, tickEcosystem } from "./ecosystem.mjs";
import { createQuestLog, advance, briefs, ORG } from "./quests.mjs";
import { createRun, record, recordQuestComplete, extractRun } from "./workflow.mjs";

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(70, innerWidth / innerHeight, 0.1, 300);
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(innerWidth, innerHeight);
document.body.appendChild(renderer.domElement);
addEventListener("resize", () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

const world = buildWorld(scene);
const bw = createBandwidth(100);
const me = createPlayer("auditor");
const router = createRouter(world.npcs.map((n) => n.userData.npcId));
// P2: NPCs follow org circuits (home → Great Hall → peer) instead of random wander
const eco = createEcosystem(world.npcs.map((n) => n.userData.dept));
const questLog = createQuestLog();
let run = createRun(Number(localStorage.getItem("bluehenre.runId") || 1));

const hud = document.getElementById("hud");
const questsEl = document.getElementById("quests");
const log = document.getElementById("log");
const say = (line) => {
  const p = document.createElement("p");
  p.textContent = line; // textContent only — no markup injection from any source
  log.prepend(p);
  while (log.childNodes.length > 8) log.lastChild.remove();
};

const renderQuests = () => {
  questsEl.textContent = briefs(questLog)
    .map((b) => `▢ ${b.quest}: ${b.next}`)
    .concat(questLog.completed.map((q) => `✓ ${q}`))
    .join("\n") || "all quest lines complete";
};

const keys = new Set();
addEventListener("keydown", (e) => keys.add(e.key.toLowerCase()));
addEventListener("keyup", (e) => keys.delete(e.key.toLowerCase()));

// persona hot-swap: keys 1/2/3, only on a terminal, costs bandwidth
const order = Object.keys(PERSONAS);
addEventListener("keydown", (e) => {
  const i = ["1", "2", "3"].indexOf(e.key);
  if (i === -1) return;
  const target = order[i];
  const term = onTerminal(world.player, world.terminals);
  const sw = hotSwap(me, target, { onTerminal: term });
  if (!sw.ok) return say(`swap → ${target}: ${sw.reason}`);
  const sp = spend(bw, "hot_swap", me.persona);
  record(run, { action: "hot_swap", persona: me.persona, ok: sp.ok, cost: sp.cost });
  say(sp.ok ? `now ${PERSONAS[target].label}` : `swap denied: ${sp.reason}`);
});

// E = persona ability on the nearest NPC: spends bandwidth, advances quests,
// records the workflow event, and chats through the HONEST proxy.
addEventListener("keydown", async (e) => {
  if (e.key.toLowerCase() !== "e") return;
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

  const prompt = `${action} request from ${PERSONAS[me.persona].label}`;
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
});

// Q = query the memory router (what does the org remember about my probes?)
addEventListener("keydown", (e) => {
  if (e.key.toLowerCase() !== "q") return;
  const hits = route(router, "request interview decode replan sync status");
  say(hits.length
    ? `router[${hits[0].kind}]: ${hits.slice(0, 4).map((h) => `${h.npcId}:${h.score}`).join("  ")}`
    : "router: no org memories match");
});

// V = observe mode (RollerCoaster-Tycoon view): pull up to a slow aerial orbit and
// just WATCH the org at work — circuits, hall meetings, memo traffic. Player input
// is parked; the ecosystem keeps running because it never depended on the player.
let observe = false;
let orbitA = 0;
addEventListener("keydown", (e) => {
  if (e.key.toLowerCase() !== "v") return;
  observe = !observe;
  say(observe ? "observe mode — the org runs itself; V to return" : "back on the ground");
});

// Run-end reset — extract THEN wipe, honestly reporting validated vs discarded.
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
  say(`fresh run #${run.runId} — spent ${stats.spentTotal.toFixed(0)} bw last run; ${wiped.wiped} memories wiped`);
}

let last = performance.now();
let resetLatch = false;
function frame(now) {
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;

  const p = world.player.position;
  if (!observe) {
    const sprint = keys.has("shift");
    const v = sprint ? 14 : 7;
    if (keys.has("w")) p.z -= v * dt;
    if (keys.has("s")) p.z += v * dt;
    if (keys.has("a")) p.x -= v * dt;
    if (keys.has("d")) p.x += v * dt;
    if (sprint && (keys.has("w") || keys.has("a") || keys.has("s") || keys.has("d")))
      spend(bw, "move_fast", me.persona);
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
  }
  bwTick(bw, dt * 2);

  if (observe) {
    // tycoon view: slow aerial orbit of the whole campus
    orbitA += dt * 0.12;
    camera.position.set(Math.cos(orbitA) * 70, 55, Math.sin(orbitA) * 70);
    camera.lookAt(0, 0, 0);
  } else {
    camera.position.set(p.x, 14, p.z + 18);
    camera.lookAt(p.x, 0, p.z);
  }

  const term = onTerminal(world.player, world.terminals);
  hud.textContent = observe
    ? `${ORG.name} campus | OBSERVE MODE — the org at work (${eco.memos} memos so far) | V=return`
    : `${ORG.name} campus | ${PERSONAS[me.persona].label} | bandwidth ${bw.value.toFixed(0)}/${bw.max}` +
      (term ? " | TERMINAL: 1=auditor 2=cipher 3=architect" : "") +
      (bw.runOver ? " | RUN OVER — R resets (session wipes)" : " | E=ability Q=router V=observe Shift=sprint");
  if (bw.runOver && keys.has("r") && !resetLatch) {
    resetLatch = true;
    endRun().finally(() => (resetLatch = false));
  }

  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
renderQuests();
say(`${ORG.name}: "${ORG.mission}" — ${ORG.platform}`);
say(`run #${run.runId} started. WASD to move. Router: ${router.kind}`);
