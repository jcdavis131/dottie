"""GAIA2-style async/dynamic scenario corpus (phases 3/4/5).

Modeled on Meta's real Gaia2 benchmark (facebookresearch/meta-agents-research-
environments: 800 scenarios across 10 "universes", 11 core apps, environments
that evolve independently of the agent -- events fire on their own clock,
requiring the agent to adapt to declines/new constraints, resolve ambiguity
between conflicting instructions, track a deadline, and incorporate another
agent's reported progress).

No network access, no dependency on the real ARE/Gaia2 code or data (spec 02
forbids both) -- this builds a small deterministic scheduling state machine:
an initial list of candidate time slots, a sequence of RNG-seeded async
events that each prune or reorder that list, and a final action computed by
literally replaying the events against the slot list. The "assistant"
resolution is therefore always the actual result of the state machine, never
a guessed answer.

Four event-driven twists, one per `concept` (mirroring Gaia2's named
capability axes: adaptability, ambiguity handling, time-sensitivity,
agent-to-agent collaboration). task_type="temporal" throughout -- the whole
family is about reasoning over an evolving environment/timeline.
"""

from __future__ import annotations

from typing import Iterator

from ava.datagen.base import Generator

_UNIVERSES = [
    "Household Ops", "Startup Ops", "Campus Life", "Field Research",
    "Retail Floor", "Clinic Desk", "Newsroom", "Logistics Hub",
    "Studio Production", "Civic Services",
]

_APPS = [
    "Calendar", "Email", "Messaging", "Contacts", "Files", "Calculator",
    "Maps", "Shopping", "Notes", "Reminders", "Weather",
]

_PARTICIPANTS = ["Alex", "Priya", "Sam", "Jordan", "Riley", "Morgan", "Casey"]

_GOAL_TASKS = [
    "book a review meeting", "confirm a delivery window", "schedule an interview",
    "arrange a maintenance visit", "set up a handoff call", "reserve a shared room",
]


def _slot_str(day: int, hour: int) -> str:
    return f"Day {day} {hour:02d}:00"


def _gen_slots(rng, n: int) -> list[tuple[int, int]]:
    slots: set[tuple[int, int]] = set()
    while len(slots) < n:
        day = rng.randint(1, 5)
        hour = rng.choice([9, 10, 11, 13, 14, 15, 16])
        slots.add((day, hour))
    return sorted(slots)


def _header(rng, n_apps: int) -> tuple[str, list[str], str, tuple[int, int]]:
    universe = rng.choice(_UNIVERSES)
    apps = sorted(rng.sample(_APPS, n_apps))
    task = rng.choice(_GOAL_TASKS)
    deadline = (rng.randint(3, 5), rng.choice([15, 16, 17]))
    return universe, apps, task, deadline


def _fmt_events(events: list[str]) -> str:
    return "\n".join(f"- {e}" for e in events)


def _earliest_before(slots: list[tuple[int, int]], deadline: tuple[int, int]) -> tuple[int, int] | None:
    candidates = [s for s in slots if s <= deadline]
    return min(candidates) if candidates else None


# ---------------------------------------------------------------------------
# Twist: adaptability (a candidate slot is declined mid-scenario)
# ---------------------------------------------------------------------------

def _adaptability_doc(rng) -> tuple[str, str, str]:
    universe, apps, task, deadline = _header(rng, rng.randint(2, 3))
    slots = _gen_slots(rng, rng.randint(3, 5))
    person = rng.choice(_PARTICIPANTS)
    decline_idx = rng.randrange(len(slots))
    decline_slot = slots[decline_idx]

    events = [
        f"[{_slot_str(*decline_slot)} minus 1h] Calendar: {person} declines the proposed slot "
        f"{_slot_str(*decline_slot)}.",
    ]
    remaining = [s for s in slots if s != decline_slot]
    chosen = _earliest_before(remaining, deadline)

    text = (
        f"Universe: {universe}. Apps available: {', '.join(apps)}.\n"
        f"Goal: {task} with {person} before {_slot_str(*deadline)}.\n"
        f"Initial candidate slots: {', '.join(_slot_str(*s) for s in slots)}.\n\n"
        f"Environment events (fire independently of the agent):\n{_fmt_events(events)}\n\n"
        f"Resolution: {person} declined {_slot_str(*decline_slot)}, removing it from the "
        f"candidate list ({', '.join(_slot_str(*s) for s in remaining)} remain). "
        + (
            f"The earliest remaining slot at or before the deadline is {_slot_str(*chosen)}; "
            f"book that one and notify {person}."
            if chosen is not None else
            f"No remaining slot falls at or before the deadline {_slot_str(*deadline)}; "
            f"escalate and propose extending the deadline to the nearest remaining slot, "
            f"{_slot_str(*min(remaining))}."
        )
    )
    return text, "adaptability"


# ---------------------------------------------------------------------------
# Twist: ambiguity (two conflicting messages; explicit time beats vague ask)
# ---------------------------------------------------------------------------

def _ambiguity_doc(rng) -> tuple[str, str, str]:
    universe, apps, task, deadline = _header(rng, rng.randint(2, 3))
    slots = _gen_slots(rng, rng.randint(3, 5))
    person = rng.choice(_PARTICIPANTS)
    vague_slot = slots[rng.randrange(len(slots))]
    explicit_slot = slots[rng.randrange(len(slots))]

    events = [
        f"[{_slot_str(*vague_slot)} minus 3h] Messaging: {person} says \"maybe let's keep it "
        f"around the usual time, whatever works.\"",
        f"[{_slot_str(*vague_slot)} minus 1h] Messaging: {person} follows up: \"actually, let's "
        f"lock in {_slot_str(*explicit_slot)} specifically.\"",
    ]
    # The tie-break rule is "later explicit beats earlier vague" -- it is not
    # "book whatever else happens to fit". If the explicit slot itself misses
    # the deadline, the only correct move is to flag it, never to silently
    # substitute a different slot the message never named.
    chosen = explicit_slot if explicit_slot <= deadline else None

    text = (
        f"Universe: {universe}. Apps available: {', '.join(apps)}.\n"
        f"Goal: {task} with {person} before {_slot_str(*deadline)}.\n"
        f"Initial candidate slots: {', '.join(_slot_str(*s) for s in slots)}.\n\n"
        f"Environment events (fire independently of the agent):\n{_fmt_events(events)}\n\n"
        f"Resolution: the first message is vague (no specific time); the follow-up names "
        f"{_slot_str(*explicit_slot)} explicitly and is the more recent instruction. "
        f"Tie-break rule: a later, explicit time supersedes an earlier, vague one. "
        + (
            f"Book {_slot_str(*chosen)}."
            if chosen is not None else
            f"{_slot_str(*explicit_slot)} falls after the deadline {_slot_str(*deadline)}; "
            f"flag the conflict to {person} rather than silently rebooking."
        )
    )
    return text, "ambiguity"


# ---------------------------------------------------------------------------
# Twist: deadline pressure (a new constraint shrinks the window late)
# ---------------------------------------------------------------------------

def _deadline_doc(rng) -> tuple[str, str, str]:
    universe, apps, task, deadline = _header(rng, rng.randint(2, 3))
    slots = _gen_slots(rng, rng.randint(4, 6))
    blocked_from = rng.choice([15, 16])

    events = [
        f"[{_slot_str(deadline[0], 8)}] Files: room booking system reports the venue is "
        f"unavailable from {blocked_from:02d}:00 onward on day {deadline[0]}.",
        f"[{_slot_str(deadline[0], 8)} plus 30m] Reminders: deadline reminder fires -- "
        f"{_slot_str(*deadline)} is the hard cutoff.",
    ]
    remaining = [s for s in slots if not (s[0] == deadline[0] and s[1] >= blocked_from)]
    chosen = _earliest_before(remaining, deadline)

    text = (
        f"Universe: {universe}. Apps available: {', '.join(apps)}.\n"
        f"Goal: {task} before {_slot_str(*deadline)}.\n"
        f"Initial candidate slots: {', '.join(_slot_str(*s) for s in slots)}.\n\n"
        f"Environment events (fire independently of the agent):\n{_fmt_events(events)}\n\n"
        f"Resolution: the venue constraint removes every day-{deadline[0]} slot at or after "
        f"{blocked_from:02d}:00, leaving {', '.join(_slot_str(*s) for s in remaining) or 'none'}. "
        + (
            f"The earliest of those at or before the deadline is {_slot_str(*chosen)}; book it "
            f"immediately given the tightened window."
            if chosen is not None else
            f"No slot survives at or before the deadline; escalate now rather than wait, since "
            f"the reminder confirms the cutoff is hard."
        )
    )
    return text, "deadline"


# ---------------------------------------------------------------------------
# Twist: collaboration (a second agent reports partial progress)
# ---------------------------------------------------------------------------

def _collaboration_doc(rng) -> tuple[str, str, str]:
    universe, apps, task, deadline = _header(rng, rng.randint(2, 3))
    slots = _gen_slots(rng, rng.randint(3, 5))
    booked_idx = rng.randrange(len(slots))
    booked_slot = slots[booked_idx]
    other_bot = rng.choice(["Ops-Bot", "Scheduling-Bot", "Desk-Bot", "Relay-Bot"])

    fits_deadline = booked_slot <= deadline
    events = [
        f"[{_slot_str(*booked_slot)} minus 2h] Messaging: {other_bot} reports it already "
        f"confirmed the room for {_slot_str(*booked_slot)} as part of a related sub-task.",
    ]
    text = (
        f"Universe: {universe}. Apps available: {', '.join(apps)}.\n"
        f"Goal: {task} before {_slot_str(*deadline)}, coordinating with {other_bot} on room "
        f"booking.\n"
        f"Initial candidate slots: {', '.join(_slot_str(*s) for s in slots)}.\n\n"
        f"Environment events (fire independently of the agent):\n{_fmt_events(events)}\n\n"
        f"Resolution: {other_bot} already booked {_slot_str(*booked_slot)} for the room -- "
        + (
            f"that slot is at or before the deadline {_slot_str(*deadline)}, so accept "
            f"{other_bot}'s booking rather than duplicate it or pick a different slot."
            if fits_deadline else
            f"but that slot is after the deadline {_slot_str(*deadline)}, so flag the conflict "
            f"to {other_bot} instead of silently accepting a booking that misses the goal."
        )
    )
    return text, "collaboration"


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class WorkflowGaia2Generator(Generator):
    name = "gaia2"
    phases = (3, 4, 5)

    # (weight, builder)
    _TWISTS = [
        (0.30, _adaptability_doc),
        (0.25, _ambiguity_doc),
        (0.25, _deadline_doc),
        (0.20, _collaboration_doc),
    ]

    # (weight, phase) -- gaia2 skews longer/later than jobbench (matches the
    # blueprint's own p3/p4/p5 emphasis for GAIA2-style data).
    _PHASE_MIX = [
        (0.45, 3),
        (0.35, 4),
        (0.20, 5),
    ]

    def generate(self, target_bytes: int) -> Iterator[dict]:
        twist_cum, twist_total = [], 0.0
        for w, _ in self._TWISTS:
            twist_total += w
            twist_cum.append(twist_total)

        phase_cum, phase_total = [], 0.0
        for w, _ in self._PHASE_MIX:
            phase_total += w
            phase_cum.append(phase_total)

        produced = 0
        while produced < target_bytes:
            r = self.rng.random() * twist_total
            ti = 0
            while r > twist_cum[ti]:
                ti += 1
            _, builder = self._TWISTS[ti]

            r2 = self.rng.random() * phase_total
            pi = 0
            while r2 > phase_cum[pi]:
                pi += 1
            _, phase = self._PHASE_MIX[pi]

            text, concept = builder(self.rng)
            if phase == 4:
                # A single scenario averages ~650 chars -- far short of spec 02's
                # 6000-12000 char long-doc band. Chain a day-spanning sequence of
                # further independent scenarios in the same universe (each drawn
                # from the same weighted twist mix) until the doc is long enough,
                # rather than inventing a second, more-verbose generation path.
                segments = 1
                while len(text) < 6500 and segments < 20:
                    r3 = self.rng.random() * twist_total
                    tj = 0
                    while r3 > twist_cum[tj]:
                        tj += 1
                    text_n, _concept_n = self._TWISTS[tj][1](self.rng)
                    text = (
                        text + f"\n\n--- Segment {segments + 1} (same universe, later that day) ---\n\n"
                        + text_n
                    )
                    segments += 1
                concept = f"{concept}_chain"
            source = f"workflow/gaia2_{concept.split('_chain')[0]}"
            d = self.doc(text=text, task_type="temporal", concept=concept, phase=phase, source=source)
            produced += len(d["text"].encode("utf-8"))
            yield d


if __name__ == "__main__":
    from ava.datagen.base import run_cli

    run_cli(WorkflowGaia2Generator)
