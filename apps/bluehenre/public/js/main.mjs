// LIMBIC vertical slice — glue: input, loop, HUD, honest NPC chat.
import * as THREE from "three";
import { buildWorld, tickNpcs, onTerminal, nearestNpc } from "./world.mjs";
import { createBandwidth, spend, tick as bwTick, resetRun } from "./bandwidth.mjs";
import { PERSONAS, createPlayer, hotSwap } from "./persona.mjs";
import { createRouter, remember, route } from "./router.mjs";

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

const hud = document.getElementById("hud");
const log = document.getElementById("log");
const say = (line) => {
  const p = document.createElement("p");
  p.textContent = line; // textContent only — no markup injection from any source
  log.prepend(p);
  while (log.childNodes.length > 8) log.lastChild.remove();
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
  say(sp.ok ? `now ${PERSONAS[target].label}` : `swap denied: ${sp.reason}`);
});

// E = persona ability on the nearest NPC; chat goes through the HONEST proxy
addEventListener("keydown", async (e) => {
  if (e.key.toLowerCase() !== "e") return;
  const npc = nearestNpc(world.player, world.npcs);
  if (!npc) return say("no NPC in range");
  const action = PERSONAS[me.persona].ability;
  const sp = spend(bw, action, me.persona);
  if (!sp.ok) return say(`${action} denied: ${sp.reason}`);
  const q = `${action} request from ${PERSONAS[me.persona].label}`;
  remember(router, npc.userData.npcId, q);
  say(`${action} → ${npc.userData.npcId} (cost ${sp.cost}) …`);
  try {
    const r = await fetch("/api/npc-chat", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ npc: npc.userData.npcId, dept: npc.userData.dept, prompt: q }),
    });
    const d = await r.json();
    // Provenance-honest: the server marks source "dottie" or "offline"; we show which.
    say(`${npc.userData.npcId} [${d.source}]: ${d.reply}`);
  } catch {
    say(`${npc.userData.npcId} [offline]: chat backend unreachable`);
  }
});

let last = performance.now();
function frame(now) {
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;

  const sprint = keys.has("shift");
  const v = sprint ? 14 : 7;
  const p = world.player.position;
  if (keys.has("w")) p.z -= v * dt;
  if (keys.has("s")) p.z += v * dt;
  if (keys.has("a")) p.x -= v * dt;
  if (keys.has("d")) p.x += v * dt;
  if (sprint && (keys.has("w") || keys.has("a") || keys.has("s") || keys.has("d")))
    spend(bw, "move_fast", me.persona);

  tickNpcs(world.npcs, dt);
  bwTick(bw, dt * 2);

  camera.position.set(p.x, 14, p.z + 18);
  camera.lookAt(p.x, 0, p.z);

  const term = onTerminal(world.player, world.terminals);
  hud.textContent =
    `${PERSONAS[me.persona].label} | bandwidth ${bw.value.toFixed(0)}/${bw.max}` +
    (term ? " | TERMINAL: 1=auditor 2=cipher 3=architect" : "") +
    (bw.runOver ? " | RUN OVER — R resets (session wipes)" : " | E=ability near NPC, Shift=sprint");
  if (bw.runOver && keys.has("r")) {
    const stats = resetRun(bw);
    say(`run reset — spent ${stats.spentTotal.toFixed(0)} bandwidth. Session memory wiped.`);
  }

  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
say("LIMBIC slice up. WASD to move. Router: " + router.kind);
