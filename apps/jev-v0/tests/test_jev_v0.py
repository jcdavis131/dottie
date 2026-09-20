"""Stdlib-only checks for the jev-v0 System One spike.

No torch, no network downloads, no --go. Run with:

    python3 -m unittest apps.jev-v0.tests.test_jev_v0
    python3 -m unittest discover -s apps/jev-v0/tests -v
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

APP = Path(__file__).resolve().parents[1]
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from decision_io import (
    SCHEMA_ID,
    SchemaError,
    load_fixtures,
    load_schema,
    reject_forbidden_content,
    untrained_answer,
    validate_record,
    validate_request,
)
from serve_decide import DecideServer, decide
from train_pointer_lora import dry_run
from train_pointer_lora import main as train_main


class SchemaAndFixturesTests(unittest.TestCase):
    def test_schema_id_is_frozen(self) -> None:
        schema = load_schema()
        self.assertEqual(schema["$id"], SCHEMA_ID)
        self.assertEqual(SCHEMA_ID, "jev-decision-schema-1.0.0")

    def test_fixtures_validate_and_cover_all_types(self) -> None:
        records = load_fixtures()
        self.assertEqual(len(records), 8)
        types = {
            question["type"] for record in records for question in record["questions"].values()
        }
        self.assertEqual(types, {"choice", "score", "noul"})

    def test_rejects_virus_content(self) -> None:
        with self.assertRaisesRegex(SchemaError, "forbidden content"):
            reject_forbidden_content({"state": {"message": "this sample contains a computer virus"}})

    def test_rejects_schema_drift(self) -> None:
        with self.assertRaisesRegex(SchemaError, "frozen"):
            validate_request(
                {
                    "schema": "jev-decision-schema-2.0.0",
                    "state": {"ticket": "x"},
                    "questions": {"ok": {"type": "noul", "instructions": "Is this a ticket?"}},
                }
            )

    def test_label_must_be_in_offered_set(self) -> None:
        record = {
            "schema": SCHEMA_ID,
            "id": "bad",
            "state": {"ticket": "x"},
            "questions": {
                "team": {
                    "type": "choice",
                    "instructions": "Which team?",
                    "criteria": {"billing": "Charges", "other": "None of these"},
                }
            },
            "labels": {"team": {"type": "choice", "choice": "sales"}},
        }
        with self.assertRaisesRegex(SchemaError, "not in the offered set"):
            validate_record(record)


class DryRunTests(unittest.TestCase):
    def test_dry_run_is_torch_free(self) -> None:
        self.assertNotIn("torch", sys.modules)
        buffer = io.StringIO()
        old = sys.stdout
        sys.stdout = buffer
        try:
            rc = train_main(["--dry-run"])
        finally:
            sys.stdout = old
        self.assertEqual(rc, 0)
        report = json.loads(buffer.getvalue())
        self.assertTrue(report["ok"])
        self.assertTrue(report["dry_run"])
        self.assertFalse(report["training"])
        self.assertFalse(report["torch_imported"])
        self.assertEqual(report["architecture"]["pivot"], "small+LoRA+pointer heads")
        self.assertIn("train_1b", report["architecture"]["not"])
        self.assertIn("TypeSafe parity", report["architecture"]["not"])
        self.assertNotIn("torch", sys.modules)

    def test_dry_run_helper_matches_cli(self) -> None:
        report = dry_run(
            schema_path=APP / "schema" / "decision_schema.json",
            fixtures_path=APP / "fixtures" / "synthetic_decisions.jsonl",
            base_model="Qwen/Qwen2.5-0.5B",
        )
        self.assertEqual(report["records"], 8)
        self.assertGreaterEqual(report["question_types"]["choice"], 1)
        self.assertGreaterEqual(report["question_types"]["noul"], 1)
        self.assertGreaterEqual(report["question_types"]["score"], 1)


class DecideTests(unittest.TestCase):
    def test_untrained_decide_is_typed(self) -> None:
        body = decide(
            {
                "schema": SCHEMA_ID,
                "state": {"ticket": "TD-1001", "message": "Charged twice."},
                "questions": {
                    "team": {
                        "type": "choice",
                        "instructions": "Which team should handle this ticket?",
                        "criteria": {
                            "billing": "Charges and refunds",
                            "technical": "Bugs and outages",
                            "other": "None of these",
                        },
                    },
                    "urgent": {
                        "type": "noul",
                        "instructions": "Does the sender ask for help today?",
                    },
                },
            },
            model="jev-v0-untrained",
            mode="untrained",
        )
        self.assertEqual(body["schema"], SCHEMA_ID)
        self.assertEqual(body["mode"], "untrained")
        self.assertNotIn("confidence", json.dumps(body))
        team = body["answers"]["team"]
        self.assertEqual(team["type"], "choice")
        self.assertAlmostEqual(sum(team["probabilities"].values()), 1.0)
        self.assertEqual(body["answers"]["urgent"]["type"], "noul")
        self.assertGreaterEqual(body["answers"]["urgent"]["noul"], 0.0)
        self.assertLessEqual(body["answers"]["urgent"]["noul"], 1.0)

    def test_untrained_answer_covers_score_expectation(self) -> None:
        answer = untrained_answer(
            {
                "type": "score",
                "instructions": "How severe?",
                "criteria": ["Cosmetic", "Workaround exists", "Blocking"],
            }
        )
        self.assertAlmostEqual(answer["score"], 1.0)
        self.assertNotIn("confidence", json.dumps(answer))

    def test_health_and_decide_on_loopback(self) -> None:
        server = DecideServer("127.0.0.1", 0, model="jev-v0-untrained", mode="untrained")
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address[:2]
        conn = HTTPConnection(host, port, timeout=2)
        try:
            conn.request("GET", "/health")
            health = json.loads(conn.getresponse().read().decode())
            self.assertTrue(health["ok"])
            self.assertEqual(health["schema"], SCHEMA_ID)
            self.assertIn("train_1b", health["not"])

            payload = {
                "schema": SCHEMA_ID,
                "state": {"ticket": "TD-9", "message": "Layout shift on the settings page."},
                "questions": {
                    "severity": {
                        "type": "score",
                        "instructions": "How severe is the reported issue?",
                        "criteria": ["Cosmetic", "Workaround exists", "Blocking"],
                    }
                },
            }
            raw = json.dumps(payload).encode()
            conn.request(
                "POST", "/decide", body=raw, headers={"Content-Type": "application/json"}
            )
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            body = json.loads(response.read().decode())
            self.assertEqual(body["answers"]["severity"]["type"], "score")
            self.assertEqual(set(body["answers"]["severity"]["legend"]), {"0", "1", "2"})

            conn.request("POST", "/decide", body=b"{}", headers={"Content-Type": "application/json"})
            rejected = conn.getresponse()
            self.assertEqual(rejected.status, 422)
        finally:
            conn.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
