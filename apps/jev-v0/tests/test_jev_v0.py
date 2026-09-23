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
    answer_from_probabilities,
    checkpoint_identity,
    load_fixtures,
    load_schema,
    reject_forbidden_content,
    untrained_answer,
    validate_record,
    validate_request,
)
from serve_decide import (
    DEFAULT_PORT,
    SIDECAR_PORT,
    DecideServer,
    checkpoint_info,
    decide,
)
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


class _Peaked:
    """A stand-in predictor: 0.7 on the first option. Tests the serving path, not a model."""

    def probabilities(self, state, question):
        from decision_io import option_keys

        keys = option_keys(question)
        rest = 0.3 / (len(keys) - 1)
        return {k: (0.7 if i == 0 else rest) for i, k in enumerate(keys)}


class CheckpointServingTests(unittest.TestCase):
    def test_port_owner_is_the_sidecar(self) -> None:
        self.assertEqual(SIDECAR_PORT, 8770)
        self.assertEqual(DEFAULT_PORT, 8771)

    def test_answer_from_probabilities_uses_shape_concentration(self) -> None:
        choice = {"type": "choice", "instructions": "x", "criteria": {"a": "A", "b": "B"}}
        ans = answer_from_probabilities(choice, {"a": 0.2, "b": 0.8})
        self.assertEqual(ans["choice"], "b")
        self.assertAlmostEqual(ans["shape_concentration"], 0.8)
        self.assertNotIn("confidence", json.dumps(ans))
        score = {"type": "score", "instructions": "x", "criteria": ["lo", "mid", "hi"]}
        self.assertAlmostEqual(answer_from_probabilities(score, {"0": 0.0, "1": 0.5, "2": 0.5})["score"], 1.5)
        noul = {"type": "noul", "instructions": "x"}
        self.assertAlmostEqual(answer_from_probabilities(noul, {"true": 3.0, "false": 1.0})["noul"], 0.75)
        with self.assertRaises(SchemaError):
            answer_from_probabilities(choice, {"a": 1.0})

    def test_decide_with_a_predictor_is_pointer_mode(self) -> None:
        payload = {
            "schema": SCHEMA_ID,
            "state": {"message": "x"},
            "questions": {"team": {"type": "choice", "instructions": "Which?", "criteria": {"a": "A", "b": "B"}}},
        }
        body = decide(payload, model="ck", mode="pointer-lora", predictor=_Peaked())
        self.assertEqual(body["mode"], "pointer-lora")
        self.assertEqual(body["answers"]["team"]["choice"], "a")
        self.assertAlmostEqual(body["answers"]["team"]["shape_concentration"], 0.7)

    def test_checkpoint_info_reads_gate_only_for_these_bytes(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            ck = Path(tmp)
            (ck / "pointer.pt").write_bytes(b"weights")
            info = checkpoint_info(ck)
            self.assertFalse(info["gate_passed"])
            sha = checkpoint_identity(ck)
            self.assertEqual(info["checkpoint_sha256"], sha)
            (ck / "eval_summary.json").write_text(json.dumps({"gate_passed": True, "artifact_sha256": sha}))
            self.assertTrue(checkpoint_info(ck)["gate_passed"])
            (ck / "pointer.pt").write_bytes(b"retrained")
            self.assertFalse(checkpoint_info(ck)["gate_passed"])

    def test_pointer_checkpoint_layout_is_checked_without_torch(self) -> None:
        import tempfile

        from pointer_infer import check_layout

        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(SchemaError):
            check_layout(Path(tmp))
        self.assertNotIn("torch", sys.modules)

    def test_health_reports_checkpoint_identity(self) -> None:
        server = DecideServer("127.0.0.1", 0, model="ck", mode="pointer-lora", predictor=_Peaked(),
                              checkpoint_info={"checkpoint_sha256": "f" * 64, "gate_passed": False})
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        conn = HTTPConnection(*server.server_address[:2], timeout=2)
        try:
            conn.request("GET", "/health")
            health = json.loads(conn.getresponse().read().decode())
            self.assertEqual(health["mode"], "pointer-lora")
            self.assertEqual(health["checkpoint_sha256"], "f" * 64)
            self.assertFalse(health["gate_passed"])
        finally:
            conn.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


class _FakeCausalLM:
    """Torch-free stand-in: hidden row i depends only on tokens 0..i (causal), and
    the cache is a mutable list the encoder extends in place, like a real KV cache."""

    CLOSE, DECIDE = 1, 2

    def __init__(self) -> None:
        self.encoded_tokens = 0

    def tokenize(self, text: str) -> list[int]:
        import re

        out: list[int] = []
        for part in re.split(r"(</opt>|<decide>)", text):
            if part == "</opt>":
                out.append(self.CLOSE)
            elif part == "<decide>":
                out.append(self.DECIDE)
            else:
                out.extend(ord(c) + 10 for c in part)
        return out

    def encode(self, ids: list[int], past: list[int] | None) -> tuple[list[tuple[int, int]], list[int]]:
        cache = past if past is not None else [0, 0]  # [position, running hash]
        rows = []
        for tok in ids:
            cache[1] = (cache[1] * 31 + tok * (cache[0] + 1)) % 1_000_003
            cache[0] += 1
            rows.append((cache[1], cache[0]))
        self.encoded_tokens += len(ids)
        return rows, cache

    @staticmethod
    def score(query: tuple[int, int], keys: list[tuple[int, int]]) -> list[float]:
        return [((query[0] ^ k[0]) % 97) / 10.0 for k in keys]


class SharedPrefixScorerTests(unittest.TestCase):
    def _questions(self) -> dict:
        return load_fixtures()[0]["questions"]

    def _scorer(self, lm: _FakeCausalLM):
        from pointer_infer import SharedPrefixScorer

        return SharedPrefixScorer(tokenize=lm.tokenize, encode=lm.encode, copy_past=list, score=lm.score,
                                  close_id=lm.CLOSE, decide_id=lm.DECIDE)

    def test_prefix_once_equals_each_branch_encoded_whole(self) -> None:
        from pointer_infer import softmax
        from train_pointer_lora import _render_branch

        state = {"goal_features": {"n_words": 7}, "context": {"digest": "d" * 64, "items": []}}
        questions = {**self._questions(), "extra": {"type": "noul", "instructions": "Is it safe?"}}
        lm = _FakeCausalLM()
        got = self._scorer(lm).probabilities_many(state, questions)
        shared_cost = lm.encoded_tokens
        state_text = json.dumps(state, ensure_ascii=True, sort_keys=True)
        whole_cost = 0
        for qid, q in questions.items():
            text, keys = _render_branch(state_text, q)
            ref_lm = _FakeCausalLM()
            ids = ref_lm.tokenize(text)
            rows, _ = ref_lm.encode(ids, None)
            whole_cost += len(ids)
            opts = [rows[i] for i, t in enumerate(ids) if t == ref_lm.CLOSE]
            dec = rows[ids.index(ref_lm.DECIDE)]
            want = dict(zip(keys, softmax(ref_lm.score(dec, opts)), strict=True))
            self.assertEqual(set(got[qid]), set(want))
            for k in want:
                self.assertAlmostEqual(got[qid][k], want[k], places=12)
        self.assertLess(shared_cost, whole_cost)  # the state was encoded once, not per question
        self.assertNotIn("torch", sys.modules)

    def test_shared_prefix_never_crosses_a_boundary_token(self) -> None:
        from pointer_infer import shared_prefix_len

        self.assertEqual(shared_prefix_len([[5, 6, 1, 7], [5, 6, 1, 7]], {1, 2}), 2)
        self.assertEqual(shared_prefix_len([[5, 6, 7], [5, 6, 7]], set()), 2)  # a suffix always remains
        self.assertEqual(shared_prefix_len([[5, 6], [9, 6]], set()), 0)
        self.assertEqual(shared_prefix_len([], set()), 0)

    def test_decide_uses_probabilities_many_when_offered(self) -> None:
        calls = []

        class _Many:
            def probabilities_many(self, state, questions):
                calls.append(sorted(questions))
                from decision_io import option_keys

                return {qid: {k: 1.0 / len(option_keys(q)) for k in option_keys(q)} for qid, q in questions.items()}

            def probabilities(self, state, question):  # pragma: no cover - must not be used
                raise AssertionError("per-question path used")

        record = load_fixtures()[0]
        body = decide({"schema": SCHEMA_ID, "state": record["state"], "questions": record["questions"]},
                      model="m", mode="pointer-lora", predictor=_Many())
        self.assertEqual(len(calls), 1)
        self.assertEqual(set(body["answers"]), set(record["questions"]))

    def test_server_keeps_the_connection_alive(self) -> None:
        server = DecideServer("127.0.0.1", 0, model="u", mode="untrained")
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        conn = HTTPConnection(*server.server_address[:2], timeout=2)
        try:
            record = load_fixtures()[0]
            raw = json.dumps({"schema": SCHEMA_ID, "state": record["state"], "questions": record["questions"]})
            for _ in range(3):
                conn.request("POST", "/decide", body=raw, headers={"Content-Type": "application/json"})
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                resp.read()
                self.assertFalse(resp.will_close)
            sock = conn.sock
            conn.request("GET", "/health")
            conn.getresponse().read()
            self.assertIs(conn.sock, sock)  # same socket: keep-alive held
        finally:
            conn.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
