"""
scout rft — workflow-trace ETL: audit.jsonl -> RFT training dataset
Solo personal project, no connection to employer, built with public/free-tier only
"""
import json
from pathlib import Path

import typer

from bigbang.core.audit import AUDIT_FILE
from bigbang.core.output import emit
from bigbang.plugins.rft.etl import (
    RFT_RECORD_SCHEMA,
    RFT_SCHEMA_VERSION,
    export_dataset,
    iter_records,
    validate_record,
)

app = typer.Typer(name="rft", help="🎓 RFT — turn audit.jsonl workflow traces into training datasets",
                  no_args_is_help=True)

DEFAULT_OUT = Path.home() / ".local" / "share" / "bigbang" / "rft" / "rft_dataset.jsonl"


@app.command("export")
def export(
    audit_file: Path = typer.Option(AUDIT_FILE, help="Source audit.jsonl"),
    out: Path = typer.Option(DEFAULT_OUT, help="Output RFT dataset JSONL"),
    gap_seconds: float = typer.Option(300.0, help="Idle gap that splits episodes"),
    min_steps: int = typer.Option(2, help="Drop episodes shorter than this"),
):
    """Segment audit traces into episodes, redact secrets, annotate reward components, write JSONL."""
    summary = export_dataset(audit_file, out, gap_seconds=gap_seconds, min_steps=min_steps)
    emit(summary, command="rft export")


@app.command("stats")
def stats(dataset: Path = typer.Option(DEFAULT_OUT, help="RFT dataset JSONL to summarize")):
    """Summarize an exported dataset: episode/step counts, terminal-ok rate, redundancy."""
    if not dataset.exists():
        emit({"error": f"no dataset at {dataset}; run `scout rft export` first"}, command="rft stats")
        raise typer.Exit(1)
    n = steps = terminal_ok = redundant = invalid = 0
    for record in iter_records(dataset):
        n += 1
        if validate_record(record):
            invalid += 1
            continue
        rc = record["reward_components"]
        steps += rc["num_steps"]
        terminal_ok += int(rc["r_task_terminal_ok"])
        redundant += rc["redundant_steps"]
    emit({
        "schema_version": RFT_SCHEMA_VERSION,
        "records": n,
        "invalid_records": invalid,
        "total_steps": steps,
        "terminal_ok_rate": round(terminal_ok / n, 4) if n else 0.0,
        "redundant_steps": redundant,
        "dataset": str(dataset),
    }, command="rft stats")


@app.command("schema")
def schema():
    """Print the versioned JSON Schema for RFT records (consumer contract)."""
    emit({"schema_version": RFT_SCHEMA_VERSION, "json_schema": RFT_RECORD_SCHEMA},
         command="rft schema")


if __name__ == "__main__":
    app()
