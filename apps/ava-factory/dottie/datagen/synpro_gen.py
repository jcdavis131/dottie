"""SynPro-lite generator: organic-looking docs diversified with faithfulness gate.

Produces templated encyclopedia-ish paragraphs (computed numbers only), then
applies ``faithful_rephrase`` so lexical diversity never invents figures.
Weight 0 in sources.yaml until enabled — does not change live mini mixture.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dottie.datagen.base import Generator
from dottie.datagen.synpro_lite import faithful_rephrase

if TYPE_CHECKING:
    from collections.abc import Iterator


def _planet_period_doc(rng) -> str:
    # Kepler-ish: T^2 proportional to a^3 with fake constant = 1 in our units.
    a = rng.randint(2, 20)
    t2 = a * a * a
    # Integer sqrt when perfect cube chain — use float sqrt for render.
    t = t2**0.5
    name = rng.choice(["Kepler-42 b", "HD-209458 b", "TOI-700 d", "TRAPPIST-1 e"])
    base = (
        f"It is worth noting that {name} orbits at semi-major axis {a} AU. "
        f"Therefore in units where the squared period equals a cubed, "
        f"T^2 = {t2} and T is approximately {t:.4f}. "
        f"In addition a large number of similar systems show the same scaling."
    )
    return base


def _econ_ratio_doc(rng) -> str:
    produce = rng.randint(120, 980)
    consume = rng.randint(80, produce)
    ratio = produce / consume
    city = rng.choice(["Riverton", "Oakvale", "Northbridge", "Portmoss"])
    base = (
        f"However {city} produced {produce} units while consuming {consume}. "
        f"In order to compare surplus, the production-to-consumption ratio is "
        f"{ratio:.4f}. Approximately {round(ratio * 100)} percent of "
        f"consumption could be covered if production were scaled to 100."
    )
    return base


class SynProLiteGenerator(Generator):
    """P2/P3 automatic arm: rephrased organic templates with numeric fidelity."""

    name = "synpro"
    phases = (2, 3)

    def generate(self, target_bytes: int) -> Iterator[dict]:
        produced = 0
        makers = (_planet_period_doc, _econ_ratio_doc)
        while produced < target_bytes:
            base = self.rng.choice(makers)(self.rng)
            variants = faithful_rephrase(base, variants=2)
            text = variants[0]
            phase = 2 if self.rng.random() < 0.55 else 3
            doc = self.doc(
                text=text,
                task_type="automatic",
                concept="synpro_lite",
                phase=phase,
                source="synth_synpro",
            )
            produced += len(doc["text"].encode("utf-8"))
            yield doc
