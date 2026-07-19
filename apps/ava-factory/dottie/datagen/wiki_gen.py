"""WikiGenerator: comprehensive, interlinked LLM-wiki corpora (optical-ready).

Structure follows Karpathy's LLM-wiki pattern
(gist.github.com/karpathy/442a6bf555914893e9891c11519de94f): entity pages,
concept pages, an ``index.md`` catalog, and an append-only ``log.md`` -- all
cross-referenced with ``[[wiki links]]``. Each generated wiki is a synthetic
star-system atlas whose every number is COMPUTED, not templated:

  * orbital period from Kepler's third law  P = a^1.5   (solar-mass star)
  * equilibrium temperature  T = 278K * L^0.25 / sqrt(a)
  * classification (rocky vs giant) from the luminosity-scaled snow line
  * concept-page aggregates (counts, mean orbits) recomputed from members

so the same fact appears consistently on the star page, the planet page, the
concept page, and the index -- a factual graph the model can only fit by
actually binding entities to attributes. Query docs ("which planet has the
longest year?") are answerable from the pages, giving cross-page reasoning
supervision in the same corpus.

These docs are plain text through the normal shard pipeline. The optical arm
comes free: ava/pipeline/pxpipe.py renders any page deterministically into
512x512 page images / 1024-dim patch vectors at train time, so (screenshot,
text) pairs never need to be stored.

Doc mapping:
  entity/concept/index/log pages -> phase 2 (foundation), task automatic
  query+answer docs              -> phase 3 (reasoning),  task deliberate
  pointing docs (where-on-page)  -> phase 3 (reasoning),  task deliberate
  whole-wiki book                -> phase 4 (long ctx),   task automatic
"""

from __future__ import annotations

from typing import Iterator

from dottie.datagen.base import Generator
# Importing the renderer here is deliberate: pxpipe is numpy-only and a pure
# function of text, so re-rendering an atlas inside generate() is CPU-cheap
# and keeps the generator byte-deterministic (same seed -> same docs).
from dottie.pipeline.pxpipe import GLYPH, PAGE_SIDE, ROWS, render_pages

_SYL_A = ("Ker", "Vol", "Ash", "Bel", "Cyn", "Dor", "Er", "Fen", "Gal", "Hel",
          "Ith", "Jov", "Kel", "Lum", "Mar", "Nex", "Oph", "Pra", "Quel", "Ryn")
_SYL_B = ("adar", "beris", "corin", "dessa", "elion", "faris", "gorna", "hale",
          "ione", "kara", "lith", "moor", "nara", "opis", "prime", "quess",
          "rion", "senna", "thar", "una")
_CLASSES = (("G", 0.6, 1.5), ("K", 0.1, 0.6), ("M", 0.01, 0.1),
            ("F", 1.5, 5.0), ("A", 5.0, 25.0))
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _link(title: str) -> str:
    return f"[[{title}]]"


class _Planet:
    def __init__(self, name: str, orbit_au: float, radius_e: float,
                 moons: int, lum: float):
        self.name = name
        self.orbit_au = round(orbit_au, 2)
        # Kepler III, solar-mass star: P^2 = a^3
        self.period_y = round(self.orbit_au ** 1.5, 2)
        self.temp_k = round(278.0 * (lum ** 0.25) / (self.orbit_au ** 0.5))
        self.snow_line = round(2.7 * (lum ** 0.5), 2)
        self.kind = "rocky planet" if self.orbit_au < self.snow_line else "gas giant"
        self.radius_e = round(radius_e if self.kind == "rocky planet"
                              else radius_e * 6.0, 1)
        self.moons = moons if self.kind == "rocky planet" else moons + 8


class WikiGenerator(Generator):
    name = "wiki"
    phases = (2, 3, 4)

    # -- world building -----------------------------------------------------

    def _system(self) -> tuple[str, str, float, list[_Planet]]:
        rng = self.rng
        star = rng.choice(_SYL_A) + rng.choice(_SYL_B)
        cls, lo, hi = rng.choice(_CLASSES)
        lum = round(rng.uniform(lo, hi), 2)
        n = rng.randint(3, 7)
        orbits = sorted(round(rng.uniform(0.2, 18.0), 2) for _ in range(n))
        planets = []
        for i, a in enumerate(orbits):
            pname = f"{star} {'bcdefgh'[i]}"
            planets.append(_Planet(pname, a, rng.uniform(0.3, 1.8),
                                   rng.randint(0, 3), lum))
        return star, cls, lum, planets

    # -- page builders (pure functions of the system) -------------------------

    def _star_page(self, star, cls, lum, planets) -> str:
        rows = [f"# {star}", "",
                f"Class: {cls}. Luminosity: {lum} L_sun. "
                f"Known planets: {len(planets)}.", "",
                f"{star} is a class-{cls} star with a luminosity of {lum} "
                f"L_sun. Its snow line lies at {planets[0].snow_line} AU; "
                f"worlds inside it are rocky, worlds beyond it accrete into "
                f"gas giants.", "", "## Planets", ""]
        rows += [f"- {_link(p.name)} — {p.kind}, {p.orbit_au} AU"
                 for p in planets]
        rows += ["", "See also: " + _link(f"{star} system index")]
        return "\n".join(rows)

    def _planet_page(self, star, planets, i) -> str:
        p = planets[i]
        nbrs = []
        if i > 0:
            nbrs.append(f"Inward of it orbits {_link(planets[i - 1].name)}")
        if i < len(planets) - 1:
            nbrs.append(f"Beyond it lies {_link(planets[i + 1].name)}")
        rows = [f"# {p.name}", "",
                f"Type: {p.kind}. Orbit: {p.orbit_au} AU. "
                f"Period: {p.period_y} yr. Radius: {p.radius_e} R_earth. "
                f"Equilibrium temperature: {p.temp_k} K. Moons: {p.moons}.", "",
                f"{p.name} is a {p.kind} of the star {_link(star)}. It "
                f"completes one orbit every {p.period_y} years at "
                f"{p.orbit_au} AU, with an equilibrium temperature of "
                f"{p.temp_k} K." + ("" if not nbrs else " " + "; ".join(nbrs) + "."),
                "", "See also: " + _link(f"{star} system index")]
        return "\n".join(rows)

    def _concept_page(self, star, planets, kind) -> str | None:
        members = [p for p in planets if p.kind == kind]
        if not members:
            return None
        mean_au = round(sum(p.orbit_au for p in members) / len(members), 2)
        title = f"{kind.capitalize()}s of {star}"
        rows = [f"# {title}", "",
                f"The {star} system contains {len(members)} {kind}s, at a "
                f"mean orbital distance of {mean_au} AU.", ""]
        rows += [f"- {_link(p.name)} ({p.orbit_au} AU, {p.moons} moons)"
                 for p in members]
        return "\n".join(rows)

    def _index_page(self, star, titles_summaries) -> str:
        rows = [f"# {star} system index", "",
                "Catalog of every page in this wiki, one line each.", ""]
        rows += [f"- {_link(t)} — {s}" for t, s in titles_summaries]
        return "\n".join(rows)

    def _log_page(self, star, titles) -> str:
        rng = self.rng
        y, m, d = rng.randint(2024, 2026), rng.randint(0, 11), rng.randint(1, 27)
        rows = [f"# {star} wiki log", ""]
        for i, t in enumerate(titles):
            day = min(27, d + i)
            rows.append(f"## [{y}-{_MONTHS[m]}-{day:02d}] ingest | {t}")
        return "\n".join(rows)

    def _query_docs(self, star, planets) -> list[tuple[str, str]]:
        longest = max(planets, key=lambda p: p.period_y)
        hottest = max(planets, key=lambda p: p.temp_k)
        moons = sum(p.moons for p in planets)
        return [
            (f"Q: Which planet of {star} has the longest year, and how long "
             f"is it?\nSearching {_link(f'{star} system index')} -> comparing "
             f"the period field of {len(planets)} planet pages.\n"
             f"A: {_link(longest.name)}, at {longest.period_y} years "
             f"({longest.orbit_au} AU; Kepler: {longest.orbit_au}^1.5).",
             longest.name),
            (f"Q: What is the hottest world orbiting {star}, and what is the "
             f"total moon count of the system?\nReading every planet page "
             f"listed in {_link(f'{star} system index')}.\n"
             f"A: {_link(hottest.name)} at {hottest.temp_k} K; the system's "
             f"{len(planets)} planets carry {moons} moons in total.",
             hottest.name),
        ]

    def _locate_orbit_line(self, pages, planet):
        """(page_idx, row_px, width_px, line_text) of the rendered line that
        states this planet's ``Orbit: <a> AU`` fact.

        Anchored on the planet's own ``# <name>`` heading first: orbit values
        are rounded to 2 dp and CAN collide across planets of one system, so
        a bare substring search could point at another planet's infobox. The
        heading is unique in the atlas (index/log lines mention titles but
        never as a bare ``# <name>`` line) and always fits one 64-col line."""
        needle = f"Orbit: {planet.orbit_au} AU"
        heading = f"# {planet.name}"
        seen_heading = False
        for page_idx, page in enumerate(pages):
            for row_px, _col_px, width_px, line_text in page.line_boxes:
                if not seen_heading:
                    seen_heading = line_text.strip() == heading
                elif needle in line_text:
                    return page_idx, row_px, width_px, line_text
        # Unreachable by construction (the infobox always states the orbit);
        # fail loudly rather than emit an untrue pointer into a shard.
        raise ValueError(f"orbit line for {planet.name} not rendered")

    def _pointing_doc(self, star, planets, atlas) -> str:
        """Visual-primitives pointing doc (specs/12 item 2, DeepSeek-style
        grounding): state WHERE on the rendered page a fact sits. Every
        page/line/pixel value is read back from the actual render_pages
        output -- computed, never templated -- so the pointer is true by
        construction. The intro prose keeps the doc over the curator's
        50-word Gopher floor (target >= 60) with no pipe tables."""
        pages = render_pages(atlas)
        blocks = [
            f"The atlas of the {star} system renders deterministically onto "
            f"{len(pages)} monospace pages of {PAGE_SIDE} by {PAGE_SIDE} "
            f"pixels, {ROWS} lines to the page and {GLYPH} pixel rows to the "
            f"line. Every rendered line carries a bounding box, so any "
            f"stated fact can be pinned to the page it sits on, the line "
            f"index within that page, and the exact pixel row where the "
            f"glyphs are drawn."]
        # First and last planet: a deterministic pick that consumes no rng
        # state, so adding pointing docs cannot shift the random stream of
        # later systems. Systems always have >= 3 planets, so the two differ.
        for p in (planets[0], planets[-1]):
            page_idx, row_px, width_px, line_text = \
                self._locate_orbit_line(pages, p)
            blocks.append(
                f"Q: On the rendered atlas of the {star} system, where is "
                f"the orbit of {p.name} stated?\n"
                f"Looking at page {page_idx}, scanning line boxes for the "
                f"orbit field of {p.name}.\n"
                f"A: page {page_idx}, line {row_px // GLYPH} (pixel row "
                f"{row_px}), which reads: {line_text.strip()}. The full box "
                f"spans {width_px} pixels from column 0.")
        return "\n\n".join(blocks)

    # -- generator entry point ------------------------------------------------

    def generate(self, target_bytes: int) -> Iterator[dict]:
        produced = 0
        volume: list[str] = []          # every 3rd system also emits a long
        volume_star = ""                # p4 "collected volume" of 3 atlases
        n_systems = 0
        while produced < target_bytes:
            star, cls, lum, planets = self._system()
            pages: list[tuple[str, str, str]] = []      # (title, summary, text)
            pages.append((star, f"class-{cls} star, {len(planets)} planets",
                          self._star_page(star, cls, lum, planets)))
            for i, p in enumerate(planets):
                pages.append((p.name, f"{p.kind}, {p.orbit_au} AU",
                              self._planet_page(star, planets, i)))
            for kind in ("rocky planet", "gas giant"):
                cp = self._concept_page(star, planets, kind)
                if cp:
                    pages.append((f"{kind.capitalize()}s of {star}",
                                  f"{kind}s overview", cp))
            index = self._index_page(star, [(t, s) for t, s, _ in pages])
            log = self._log_page(star, [t for t, _, _ in pages])

            # ONE atlas doc per wiki, not per-page micro-docs: the curator's
            # Gopher prose gate (ava/pipeline/clean.py) rejects docs under 50
            # words, and the first deployment shipped 695,842 page-docs of
            # which it kept exactly zero. Bundling is also what seq-1024
            # window packing wants.
            atlas = "\n\n".join([index] + [t for _, _, t in pages] + [log])
            d = self.doc(text=atlas, task_type="automatic",
                         concept=f"{star.lower()} atlas", phase=2,
                         source=self.name)
            produced += len(atlas)
            yield d

            queries = self._query_docs(star, planets)
            qa = "\n\n".join(q for q, _ in queries)
            d = self.doc(text=qa, task_type="deliberate",
                         concept=queries[0][1].lower(), phase=3,
                         source=self.name)
            produced += len(qa)
            yield d

            # Pointing doc: re-render THIS atlas and state where two orbit
            # facts sit on the page (page / line / pixel row / box width),
            # giving the optical arm DeepSeek-style grounding supervision.
            pointing = self._pointing_doc(star, planets, atlas)
            d = self.doc(text=pointing, task_type="deliberate",
                         concept=f"{star.lower()} pointing", phase=3,
                         source=self.name)
            produced += len(pointing)
            yield d

            n_systems += 1
            volume.append(atlas)
            if n_systems % 3 == 1:
                volume_star = star
            if len(volume) == 3:
                vol = "\n\n\n".join(volume)
                d = self.doc(text=vol, task_type="automatic",
                             concept=f"{volume_star.lower()} volume", phase=4,
                             source=self.name)
                produced += len(vol)
                volume = []
                yield d
