# Solo personal project, no connection to employer, built with public/free-tier only
"""RFT ETL: parsing, segmentation, redaction, reward components, schema validation, export."""

import json
from datetime import UTC, datetime, timedelta

from bigbang.plugins.rft.etl import (
    REDACTED,
    RFT_SCHEMA_VERSION,
    export_dataset,
    iter_records,
    parse_audit_lines,
    redact,
    reward_components,
    segment_episodes,
    to_rft_record,
    validate_record,
)

T0 = datetime(2026, 7, 17, 12, 0, 0, tzinfo=UTC)


def audit_line(
    offset_s=0, command="tasks list", args=None, status="ok", duration_ms=40
):
    return json.dumps(
        {
            "ts": (T0 + timedelta(seconds=offset_s)).isoformat(),
            "command": command,
            "args": args or {"tasklist": "@default"},
            "status": status,
            "duration_ms": duration_ms,
        }
    )


class TestParsing:
    def test_malformed_and_partial_lines_skipped(self):
        lines = [audit_line(0), "not json", '{"command": "x"}', "", audit_line(5)]
        events = parse_audit_lines(lines)
        assert len(events) == 2

    def test_events_sorted_by_ts(self):
        events = parse_audit_lines([audit_line(60), audit_line(0)])
        assert events[0]["ts"] < events[1]["ts"]


class TestRedaction:
    def test_secret_keys_masked(self):
        out = redact({"api_key": "abc123", "GITHUB_TOKEN": "tkn", "query": "hello"})
        assert out["api_key"] == REDACTED and out["GITHUB_TOKEN"] == REDACTED
        assert out["query"] == "hello"

    def test_secret_shaped_values_masked_anywhere(self):
        out = redact(
            {"note": "sk-abcdefghijklmnop", "nested": [{"v": "ghp_ABCDEFGH1234"}]}
        )
        assert out["note"] == REDACTED and out["nested"][0]["v"] == REDACTED

    def test_embedded_secret_in_command_redacted(self):
        # The bug: anchored ^...$ regex missed secrets inside a longer string.
        cmd = "curl -H 'Authorization: Bearer sk-abc123def456ghij' https://api.x.com"
        out = redact({"cmd": cmd})
        assert "sk-abc123def456ghij" not in out["cmd"] and REDACTED in out["cmd"]
        assert "https://api.x.com" in out["cmd"]  # non-secret parts preserved

    def test_parse_redacts_command_and_status(self):
        line = json.dumps(
            {
                "ts": T0.isoformat(),
                "command": "auth login token=ghp_ABCDEFGH1234",
                "args": {},
                "status": "ok",
                "duration_ms": 5,
            }
        )
        ev = parse_audit_lines([line])[0]
        assert "ghp_ABCDEFGH1234" not in ev["command"] and REDACTED in ev["command"]

    def test_embedded_secret_flagged_by_validator(self):
        ep = segment_episodes(parse_audit_lines([audit_line(0)]))[0]
        record = to_rft_record(ep)
        record["steps"][0]["args"]["blob"] = (
            "log line with token sk-abc123def456ghij embedded"
        )
        assert any("secret" in p for p in validate_record(record))

    def test_parse_applies_redaction(self):
        events = parse_audit_lines([audit_line(0, args={"password": "hunter2"})])
        assert events[0]["args"]["password"] == REDACTED


class TestSegmentation:
    def test_gap_splits_episodes(self):
        lines = [
            audit_line(0),
            audit_line(30),
            audit_line(30 + 400),
            audit_line(30 + 430),
        ]
        episodes = segment_episodes(parse_audit_lines(lines), gap_seconds=300)
        assert [len(e.steps) for e in episodes] == [2, 2]

    def test_step_indices_and_ids_stable(self):
        episodes = segment_episodes(parse_audit_lines([audit_line(0), audit_line(10)]))
        again = segment_episodes(parse_audit_lines([audit_line(0), audit_line(10)]))
        assert [s.t for s in episodes[0].steps] == [0, 1]
        assert episodes[0].episode_id == again[0].episode_id  # deterministic


class TestRewardComponents:
    def test_terminal_ok_and_fraction(self):
        lines = [audit_line(0, status="error"), audit_line(10, status="ok")]
        ep = segment_episodes(parse_audit_lines(lines))[0]
        rc = reward_components(ep)
        assert rc["r_task_terminal_ok"] == 1.0 and rc["fraction_ok"] == 0.5

    def test_terminal_failure_zero(self):
        ep = segment_episodes(parse_audit_lines([audit_line(0, status="error")]))[0]
        assert reward_components(ep)["r_task_terminal_ok"] == 0.0

    def test_redundant_consecutive_calls_counted(self):
        lines = [
            audit_line(0),
            audit_line(5),
            audit_line(10, command="rtx status"),
            audit_line(15),
        ]
        ep = segment_episodes(parse_audit_lines(lines))[0]
        assert (
            reward_components(ep)["redundant_steps"] == 1
        )  # only the first identical pair

    def test_length_signals_raw_not_weighted(self):
        lines = [audit_line(0, duration_ms=100), audit_line(5, duration_ms=250)]
        rc = reward_components(segment_episodes(parse_audit_lines(lines))[0])
        assert rc["num_steps"] == 2 and rc["total_duration_ms"] == 350


class TestSchema:
    def test_valid_record_passes(self):
        ep = segment_episodes(parse_audit_lines([audit_line(0), audit_line(5)]))[0]
        assert validate_record(to_rft_record(ep)) == []

    def test_version_and_missing_key_flagged(self):
        ep = segment_episodes(parse_audit_lines([audit_line(0)]))[0]
        record = to_rft_record(ep)
        record["schema_version"] = "0.9.0"
        del record["outcome"]
        problems = validate_record(record)
        assert any("schema_version" in p for p in problems)
        assert any("outcome" in p for p in problems)

    def test_unredacted_secret_rejected(self):
        ep = segment_episodes(parse_audit_lines([audit_line(0)]))[0]
        record = to_rft_record(ep)
        record["steps"][0]["args"]["leak"] = "ghp_ABCDEFGH1234"
        assert any("secret" in p for p in validate_record(record))


class TestExport:
    def test_end_to_end(self, tmp_path):
        audit = tmp_path / "audit.jsonl"
        audit.write_text(
            "\n".join(
                [
                    audit_line(0),
                    audit_line(20),
                    "garbage",
                    audit_line(500),
                    audit_line(510, status="error"),
                    audit_line(2000),  # single-step episode -> dropped by min_steps=2
                ]
            )
        )
        out = tmp_path / "rft.jsonl"
        summary = export_dataset(audit, out, gap_seconds=300, min_steps=2)
        assert summary["records_written"] == 2 and summary["dropped_short"] == 1
        records = list(iter_records(out))
        assert all(r["schema_version"] == RFT_SCHEMA_VERSION for r in records)
        assert records[1]["outcome"]["terminal_ok"] is False

    def test_missing_audit_file_yields_empty_dataset(self, tmp_path):
        summary = export_dataset(tmp_path / "absent.jsonl", tmp_path / "rft.jsonl")
        assert summary["records_written"] == 0


class TestCli:
    def test_export_and_stats_commands(self, tmp_path):
        from typer.testing import CliRunner

        from bigbang.plugins.rft.cli import app

        audit = tmp_path / "audit.jsonl"
        audit.write_text("\n".join([audit_line(0), audit_line(10)]))
        out = tmp_path / "ds.jsonl"
        runner = CliRunner()
        r1 = runner.invoke(
            app, ["export", "--audit-file", str(audit), "--out", str(out)]
        )
        assert r1.exit_code == 0 and out.exists()
        r2 = runner.invoke(app, ["stats", "--dataset", str(out)])
        assert r2.exit_code == 0
        r3 = runner.invoke(app, ["schema"])
        assert r3.exit_code == 0
