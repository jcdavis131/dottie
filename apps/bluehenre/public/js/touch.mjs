// Mobile-first touch input (BLUEHENRE SPEC "Presentation & input").
// The joystick MATH is pure and bare-node testable; only createTouchControls
// touches the DOM. Touch is the default input; keyboard is the desktop
// enhancement — main.mjs merges both every frame.

export const SPRINT_AT = 0.85; // full-ish deflection sprints (common mobile idiom)

/** Pure joystick state from a drag offset in px.
 * radius = usable stick travel; dead = deadzone as a fraction of radius.
 * Returns {x, z, mag, sprint}: x/z in [-1,1] (screen-up = -z, i.e. forward),
 * deadzone-rescaled so movement starts smoothly at the deadzone edge. */
export function stickState(dx, dy, radius = 56, dead = 0.15) {
  if (!(radius > 0)) throw new RangeError(`bad radius ${radius}`);
  let mag = Math.hypot(dx, dy) / radius;
  if (mag > 1) mag = 1;
  if (mag <= dead) return { x: 0, z: 0, mag: 0, sprint: false };
  const scaled = (mag - dead) / (1 - dead); // 0 at deadzone edge -> 1 at rim
  const len = Math.hypot(dx, dy);
  return {
    x: (dx / len) * scaled,
    z: (dy / len) * scaled, // screen down = +z (toward camera), matching WASD S
    mag: scaled,
    sprint: scaled >= SPRINT_AT,
  };
}

/** Build the touch UI and wire it. Caller decides WHETHER to call this
 * (main.mjs gates on pointer:coarse). Returns { getStick, setTerminal, setRunOver, destroy }.
 * All handlers are the same functions the keyboard uses — one action system. */
export function createTouchControls(root, { onAbility, onRouter, onObserve, onSwap, onReset }) {
  const el = document.createElement("div");
  el.id = "touch";
  el.innerHTML = `
    <div id="stick"><div id="nub"></div></div>
    <div id="actions">
      <button data-a="ability">E</button>
      <button data-a="router">Q</button>
      <button data-a="observe">V</button>
      <button data-a="reset" hidden>R</button>
    </div>
    <div id="personas" hidden>
      <button data-p="0">1</button><button data-p="1">2</button><button data-p="2">3</button>
    </div>`;
  root.appendChild(el);

  let stick = { x: 0, z: 0, mag: 0, sprint: false };
  const pad = el.querySelector("#stick");
  const nub = el.querySelector("#nub");
  let origin = null;
  const R = 56;

  const move = (t) => {
    const s = stickState(t.clientX - origin[0], t.clientY - origin[1], R);
    stick = s;
    nub.style.transform = `translate(${s.x * R * 0.6}px, ${s.z * R * 0.6}px)`;
  };
  pad.addEventListener("touchstart", (e) => {
    e.preventDefault();
    const t = e.changedTouches[0];
    origin = [t.clientX, t.clientY];
    move(t);
  }, { passive: false });
  pad.addEventListener("touchmove", (e) => {
    e.preventDefault();
    if (origin) move(e.changedTouches[0]);
  }, { passive: false });
  const end = (e) => {
    e.preventDefault();
    origin = null;
    stick = { x: 0, z: 0, mag: 0, sprint: false };
    nub.style.transform = "translate(0,0)";
  };
  pad.addEventListener("touchend", end, { passive: false });
  pad.addEventListener("touchcancel", end, { passive: false });

  const acts = { ability: onAbility, router: onRouter, observe: onObserve, reset: onReset };
  for (const b of el.querySelectorAll("#actions button"))
    b.addEventListener("touchstart", (e) => { e.preventDefault(); acts[b.dataset.a]?.(); }, { passive: false });
  for (const b of el.querySelectorAll("#personas button"))
    b.addEventListener("touchstart", (e) => { e.preventDefault(); onSwap?.(Number(b.dataset.p)); }, { passive: false });

  const personasEl = el.querySelector("#personas");
  const resetBtn = el.querySelector('[data-a="reset"]');
  return {
    getStick: () => stick,
    setTerminal: (on) => { personasEl.hidden = !on; },
    setRunOver: (on) => { resetBtn.hidden = !on; },
    destroy: () => el.remove(),
  };
}
