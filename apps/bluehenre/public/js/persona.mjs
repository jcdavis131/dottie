// Personas + terminal-gated hot-swap (BLUEHENRE SPEC "Playable personas").
// Pure logic — the 3D layer only reports whether the player stands on a terminal.

// The player is a CONSULTANT the company hired to advance the project (SPEC
// "Concept"); the three hats keep their original keys + ability verbs so every
// quest/pipeline contract is untouched — only the framing changed.
export const PERSONAS = {
  auditor: {
    label: "Discovery Consultant",
    ability: "interview",
    blurb: "runs discovery — interviews staff, surfaces what is really blocking",
  },
  cipher: {
    label: "Systems Cipher",
    ability: "decode",
    blurb: "debugs the stack — decodes logs, checksums and locked context",
  },
  architect: {
    label: "Delivery Architect",
    ability: "replan",
    blurb: "re-plans schedules, compute and process to unblock delivery",
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
