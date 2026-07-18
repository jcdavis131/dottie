"""JobBench-style delegation-dossier corpus (phases 3/4/5).

Modeled on the real JobBench benchmark (job-bench.github.io: 1,500+
professionals rating "what work do you want delegated", ~28 occupations
across seven domains, tasks framed as small dossiers of heterogeneous,
CONTRADICTORY inputs -- CSVs, memos, dated reports -- graded on binary,
anchored rubrics that require reconciling the contradiction, not just
producing a plausible-sounding answer).

This generator does not call out to the real benchmark or any network
resource (spec 02 forbids both); it builds synthetic dossiers in the same
spirit: every contradiction is planted by the generator itself, so the
correct reconciliation is always computable from the doc's own numbers.
Three families, one planted-contradiction mechanism each:

  * duplicate  -- a line-item table contains one accidentally duplicated
    row; a memo naively sums the raw table (including the duplicate).
    task_type="deliberate".
  * units      -- an itemized, auditable table (one unit) is contradicted
    by an unlabeled/mislabeled summary figure claiming different units.
    task_type="deliberate".
  * stale      -- two dated snapshots disagree because the underlying data
    changed between them; a memo cites the older, superseded figure.
    task_type="temporal" (the reconciliation hinges on document recency).

`concept` is the occupation slug -- the most specific entity in the doc,
per spec 02's convention.
"""

from __future__ import annotations

from typing import Iterator

from ava.datagen.base import Generator

# ---------------------------------------------------------------------------
# Occupations: (name, domain, line-item noun, value unit)
# Mirrors the real JobBench's 7 professional domains; not a literal copy of
# its occupation list.
# ---------------------------------------------------------------------------

_OCCUPATIONS = sorted([
    ("Accountant", "Business/Financial Operations", "ledger entry", "$"),
    ("HR Specialist", "Business/Financial Operations", "headcount record", "employees"),
    ("Financial Advisor", "Business/Financial Operations", "client position", "$"),
    ("Purchasing Agent", "Business/Financial Operations", "purchase order", "$"),
    ("Court Clerk", "Office/Administrative Support", "filed case", "cases"),
    ("Customer Service Rep", "Office/Administrative Support", "ticket", "tickets"),
    ("Data Entry Specialist", "Office/Administrative Support", "batch record", "records"),
    ("Secretary", "Office/Administrative Support", "logged appointment", "appointments"),
    ("Biostatistician", "Computer/Mathematical", "trial arm count", "subjects"),
    ("CS Researcher", "Computer/Mathematical", "benchmark run", "runs"),
    ("Statistician", "Computer/Mathematical", "sample count", "samples"),
    ("Web Administrator", "Computer/Mathematical", "server log entry", "requests"),
    ("Civil Engineer", "Architecture/Engineering", "work order", "hours"),
    ("Mechanical Engineer", "Architecture/Engineering", "part count", "units"),
    ("Petroleum Engineer", "Architecture/Engineering", "well reading", "barrels"),
    ("Financial Manager", "Management", "cost center entry", "$"),
    ("Supply Chain Manager", "Management", "shipment", "units"),
    ("IT Manager", "Management", "incident", "incidents"),
    ("Reporter", "Arts/Media", "cited figure", "respondents"),
    ("Technical Writer", "Arts/Media", "revision", "pages"),
    ("Producer", "Arts/Media", "budget line", "$"),
    ("Lawyer", "Other", "billed hour", "hours"),
    ("Online Merchant", "Other", "order", "orders"),
    ("Sales Agent", "Other", "closed deal", "$"),
    ("Science Teacher", "Other", "graded assignment", "points"),
])


def _slug(name: str) -> str:
    return name.lower().replace(" ", "_").replace("/", "_")


def _labels(rng, noun: str, n: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    while len(out) < n:
        label = f"{noun.capitalize()} #{rng.randint(100, 999)}"
        if label in seen:
            continue
        seen.add(label)
        out.append(label)
    return sorted(out)


def _values(rng, n: int, unit: str) -> list[int]:
    lo, hi = (2, 400) if unit in ("$", "barrels") else (1, 60)
    scale = 1000 if unit == "$" else (10 if unit in ("barrels",) else 1)
    return [rng.randint(lo, hi) * scale for _ in range(n)]


def _csv_table(labels: list[str], values: list[int], unit: str) -> str:
    lines = [f"line_item,value_{unit.strip('$') or 'usd'}"]
    for label, value in zip(labels, values):
        lines.append(f"{label},{value}")
    return "\n".join(lines)


def _fmt_val(value: int, unit: str) -> str:
    return f"${value:,}" if unit == "$" else f"{value:,} {unit}"


# ---------------------------------------------------------------------------
# Family: duplicate line item
# ---------------------------------------------------------------------------

def _duplicate_doc(rng, occ: tuple[str, str, str, str], n: int) -> tuple[str, str, str]:
    name, domain, noun, unit = occ
    labels = _labels(rng, noun, n)
    values = _values(rng, n, unit)
    true_sum = sum(values)
    dup_idx = rng.randrange(n)
    table_labels = labels + [labels[dup_idx]]
    table_values = values + [values[dup_idx]]
    naive_sum = true_sum + values[dup_idx]

    table = _csv_table(table_labels, table_values, unit)
    memo = (
        f"Internal memo -- {name} ({domain}) dossier.\n"
        f"Attached table ({n + 1} rows) was totaled directly: reported total is "
        f"{_fmt_val(naive_sum, unit)}. Please confirm this figure for sign-off."
    )
    text = (
        f"# Delegation dossier: {name}\n\n"
        f"Domain: {domain}\n"
        f"Task: reconcile the attached {noun} table against the memo's stated total.\n\n"
        f"## Source A -- raw table\n```\n{table}\n```\n\n"
        f"## Source B -- memo\n{memo}\n\n"
        f"## Reconciliation\n"
        f"Row {dup_idx + 1} (\"{labels[dup_idx]}\", {_fmt_val(values[dup_idx], unit)}) and row "
        f"{n + 1} (\"{table_labels[-1]}\", {_fmt_val(table_values[-1], unit)}) are an exact "
        f"duplicate -- same label, same value. The memo's total of {_fmt_val(naive_sum, unit)} "
        f"double-counts this row.\n"
        f"Deduped total = sum of the {n} distinct rows = {_fmt_val(true_sum, unit)}.\n"
        f"Verdict: the memo overstates the true total by "
        f"{_fmt_val(values[dup_idx], unit)} (the duplicated row's value). Corrected total to "
        f"report: {_fmt_val(true_sum, unit)}."
    )
    return text, "deliberate", _slug(name)


# ---------------------------------------------------------------------------
# Family: unit mismatch
# ---------------------------------------------------------------------------

def _units_doc(rng, occ: tuple[str, str, str, str], n: int) -> tuple[str, str, str]:
    name, domain, noun, unit = occ
    labels = _labels(rng, noun, n)
    values = _values(rng, n, unit)
    true_sum = sum(values)
    other_office = rng.choice(["Regional Office", "Field Office", "Partner Office", "Satellite Desk"])
    bad_unit_label = "thousands" if unit == "$" else f"hundreds of {unit}"
    bad_multiplier = 1000 if unit == "$" else 100

    table = _csv_table(labels, values, unit)
    summary = (
        f"{other_office} summary -- {name} dossier.\n"
        f"Stated total: {true_sum:,} (reported in {bad_unit_label})."
    )
    implied = true_sum * bad_multiplier
    text = (
        f"# Delegation dossier: {name}\n\n"
        f"Domain: {domain}\n"
        f"Task: reconcile the itemized {noun} table against the {other_office}'s summary figure.\n\n"
        f"## Source A -- itemized table (units: {unit if unit != '$' else 'dollars'})\n"
        f"```\n{table}\n```\nItemized total: {_fmt_val(true_sum, unit)}.\n\n"
        f"## Source B -- office summary\n{summary}\n\n"
        f"## Reconciliation\n"
        f"If Source B's figure of {true_sum:,} were genuinely denominated in {bad_unit_label}, "
        f"it would imply a total of {_fmt_val(implied, unit)} -- {bad_multiplier}x Source A's "
        f"itemized total, with no corresponding rows to support it. The itemized table (Source A) "
        f"is auditable line-by-line and sums correctly to {_fmt_val(true_sum, unit)}; the office "
        f"summary is the same raw number as the itemized total but was mislabeled with the wrong "
        f"unit. Verdict: trust Source A. Correct total: {_fmt_val(true_sum, unit)}, not "
        f"{_fmt_val(implied, unit)}."
    )
    return text, "deliberate", _slug(name)


# ---------------------------------------------------------------------------
# Family: stale snapshot
# ---------------------------------------------------------------------------

def _stale_doc(rng, occ: tuple[str, str, str, str], n: int) -> tuple[str, str, str]:
    name, domain, noun, unit = occ
    labels = _labels(rng, noun, n)
    values = _values(rng, n, unit)
    day_a = rng.randint(1, 20)
    day_b = day_a + rng.randint(3, 14)

    change = rng.choice(["added", "removed", "changed"])
    values_b = list(values)
    labels_b = list(labels)
    if change == "added":
        new_label = _labels(rng, noun, 1)[0]
        while new_label in labels_b:
            new_label = _labels(rng, noun, 1)[0]
        new_value = _values(rng, 1, unit)[0]
        labels_b.append(new_label)
        values_b.append(new_value)
        change_desc = f"a new row (\"{new_label}\", {_fmt_val(new_value, unit)}) was added"
    elif change == "removed":
        rm_idx = rng.randrange(n)
        change_desc = f"row \"{labels_b[rm_idx]}\" ({_fmt_val(values_b[rm_idx], unit)}) was removed"
        del labels_b[rm_idx]
        del values_b[rm_idx]
    else:
        chg_idx = rng.randrange(n)
        old_v = values_b[chg_idx]
        delta = rng.randint(1, max(1, old_v // 4)) * rng.choice([-1, 1])
        new_v = max(1, old_v + delta)
        values_b[chg_idx] = new_v
        change_desc = (
            f"row \"{labels_b[chg_idx]}\" changed from {_fmt_val(old_v, unit)} to "
            f"{_fmt_val(new_v, unit)}"
        )

    sum_a = sum(values)
    sum_b = sum(values_b)
    table_a = _csv_table(labels, values, unit)
    table_b = _csv_table(labels_b, values_b, unit)
    memo = (
        f"Status memo -- {name} dossier. As of day {day_a}, total is "
        f"{_fmt_val(sum_a, unit)}. Please sign off on this figure."
    )
    text = (
        f"# Delegation dossier: {name}\n\n"
        f"Domain: {domain}\n"
        f"Task: reconcile a status memo (dated day {day_a}) against the latest {noun} snapshot "
        f"(dated day {day_b}).\n\n"
        f"## Source A -- snapshot as of day {day_a}\n```\n{table_a}\n```\nTotal: "
        f"{_fmt_val(sum_a, unit)}.\n\n"
        f"## Source B -- snapshot as of day {day_b}\n```\n{table_b}\n```\nTotal: "
        f"{_fmt_val(sum_b, unit)}.\n\n"
        f"## Memo (cites the day {day_a} figure)\n{memo}\n\n"
        f"## Reconciliation\n"
        f"Between day {day_a} and day {day_b}, {change_desc}, so the total moved from "
        f"{_fmt_val(sum_a, unit)} to {_fmt_val(sum_b, unit)}. The memo cites the day {day_a} "
        f"figure, which is {day_b - day_a} days stale as of the day {day_b} snapshot. "
        f"Verdict: sign off on the current total, {_fmt_val(sum_b, unit)}, not the memo's "
        f"{_fmt_val(sum_a, unit)}; flag the memo as superseded."
    )
    return text, "temporal", _slug(name)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class WorkflowJobBenchGenerator(Generator):
    name = "jobbench"
    phases = (3, 4, 5)

    # (weight, builder, source, item-count range at phase 3, at phase 5,
    #  phase-4 growth params (start_n, step, target_chars, max_n)).
    #
    # Occupation-dependent value/label lengths (e.g. "$"-scaled dollar amounts
    # vs. small integer counts) make a fixed phase-4 item count land anywhere
    # from ~4000 to ~10000 chars depending which occupation gets drawn -- too
    # wide a spread to hit spec 02's 6000-12000 char long-doc band with a
    # single randint(lo, hi). Instead phase 4 GROWS the item count (more
    # RNG-drawn rows, same deterministic construction) until the rendered doc
    # clears the char floor, capped so it never runs away past the ceiling.
    # `_stale_doc` renders two full tables (~2x chars/item of the other two
    # families) so its start/step/cap are roughly half.
    _FAMILIES = [
        (0.40, _duplicate_doc, "workflow/jobbench_duplicate", (3, 6), (4, 8), (220, 40, 6200, 600)),
        (0.35, _units_doc, "workflow/jobbench_units", (3, 6), (4, 8), (220, 40, 6200, 600)),
        (0.25, _stale_doc, "workflow/jobbench_stale", (3, 6), (4, 8), (100, 20, 6200, 300)),
    ]

    _PHASE_MIX = [
        (0.60, 3),
        (0.15, 4),
        (0.25, 5),
    ]

    _OCCUPATIONS_LIST = _OCCUPATIONS

    def generate(self, target_bytes: int) -> Iterator[dict]:
        fam_cum, fam_total = [], 0.0
        for w, *_ in self._FAMILIES:
            fam_total += w
            fam_cum.append(fam_total)

        phase_cum, phase_total = [], 0.0
        for w, _ in self._PHASE_MIX:
            phase_total += w
            phase_cum.append(phase_total)

        produced = 0
        while produced < target_bytes:
            r = self.rng.random() * fam_total
            fi = 0
            while r > fam_cum[fi]:
                fi += 1
            _, builder, source, p3_range, p5_range, p4_growth = self._FAMILIES[fi]

            r2 = self.rng.random() * phase_total
            pi = 0
            while r2 > phase_cum[pi]:
                pi += 1
            _, phase = self._PHASE_MIX[pi]

            occ = self._OCCUPATIONS_LIST[self.rng.randrange(len(self._OCCUPATIONS_LIST))]
            if phase == 4:
                start_n, step, target_chars, max_n = p4_growth
                n = start_n
                text, task_type, concept = builder(self.rng, occ, n)
                while len(text) < target_chars and n < max_n:
                    n = min(n + step, max_n)
                    text, task_type, concept = builder(self.rng, occ, n)
            else:
                lo, hi = p3_range if phase == 3 else p5_range
                n = self.rng.randint(lo, hi)
                text, task_type, concept = builder(self.rng, occ, n)

            d = self.doc(text=text, task_type=task_type, concept=concept, phase=phase, source=source)
            produced += len(d["text"].encode("utf-8"))
            yield d


if __name__ == "__main__":
    from ava.datagen.base import run_cli

    run_cli(WorkflowJobBenchGenerator)
