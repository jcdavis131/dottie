// Personas + terminal-gated hot-swap (BLUEHENRE SPEC "Playable personas").
// Pure logic — the 3D layer only reports whether the player stands on a terminal.

export const PERSONAS = {
  auditor: {
    label: "External Auditor",
    ability: "interview",
    blurb: "primary lens — interviews NPCs, files findings",
  },
  cipher: {
    label: "Cipher",
    ability: "decode",
    blurb: "hacker — decodes archives, opens locked context",
  },
  architect: {
    label: "Spatial Architect",
    ability: "replan",
    blurb: "optimizer — re-plans space and compute",
  },
};

export function createPlayer(start = "auditor") {
  if (!PERSONAS[start]) throw new RangeError(`unknown persona ${start}`);
  return { persona: start, swaps: 0 };
}

/** Hot-swap is only legal on a terminal, to a real persona, that isn't current.
 * Returns {ok, reason?}. Bandwidth is charged by the caller via spend(.., "hot_swap"). */
export function hotSwap(player, target, { onTerminal }) {
  if (!PERSONAS[target]) return { ok: false, reason: `unknown persona ${target}` };
  if (!onTerminal) return { ok: false, reason: "hot-swap requires a terminal" };
  if (player.persona === target) return { ok: false, reason: "already that persona" };
  player.persona = target;
  player.swaps += 1;
  return { ok: true };
}
