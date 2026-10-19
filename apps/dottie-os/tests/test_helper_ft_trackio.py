"""Fake/in-memory Trackio checks for HELPER FT. Stdlib only. No HF Hub, no GPU.

    python3 -m unittest discover -s apps/dottie-os/tests -p 'test_helper_ft_trackio.py' -v
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

TESTS = Path(__file__).resolve().parent
LAB = TESTS.parents[0] / "scripts" / "lab"
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from test_ultradata_factory import (  # noqa: E402
    _cli_args,
    _fresh_kickoff_body,
    _start_hq_http_mock,
    _stop_hq_http_mock,
    _write_helper_pack,
    helper_ft_kickoff,
    kick_helper_ft,
)
import helper_ft_trackio  # noqa: E402


class FakeTrackio:
    """In-memory wandb-compatible stand-in. Never touches the network."""

    def __init__(self, *, raise_on: str | None = None) -> None:
        self.raise_on = raise_on
        self.inits: list[dict] = []
        self.logs: list[dict] = []
        self.finishes: list[bool] = []

    def _maybe_raise(self, label: str) -> None:
        if self.raise_on in {label, "all"}:
            raise RuntimeError(f"trackio {label} boom")

    def init(self, *args: object, **kwargs: object) -> "FakeTrackio":
        del args
        self._maybe_raise("init")
        self.inits.append(dict(kwargs))
        return self

    def log(self, data: dict, step: int | None = None, **kwargs: object) -> None:
        del kwargs
        self._maybe_raise("log")
        self.logs.append({"data": dict(data), "step": step})

    def finish(self) -> None:
        self._maybe_raise("finish")
        self.finishes.append(True)


class HelperFtTrackioTests(unittest.TestCase):
    def setUp(self) -> None:
        helper_ft_trackio.reset_for_tests()
        self.fake = FakeTrackio()
        helper_ft_trackio._trackio_mod = self.fake
        self.kickoff_calls: list[dict] = []
        _start_hq_http_mock(self)

        def fake_post(body: dict, url: str | None = None) -> dict:
            del url
            self.kickoff_calls.append(body)
            return {"ok": True, "checkpoint_id": "ckpt-trackio"}

        self._orig_post = kick_helper_ft.post_kickoff
        kick_helper_ft.post_kickoff = fake_post

    def tearDown(self) -> None:
        kick_helper_ft.post_kickoff = self._orig_post
        _stop_hq_http_mock(self)
        helper_ft_trackio.reset_for_tests()
        for name in kick_helper_ft._FORBIDDEN_PIN_ENV:
            os.environ.pop(name, None)
        os.environ.pop(helper_ft_trackio.DIR_ENV, None)
        os.environ.pop(helper_ft_trackio.ENABLE_ENV, None)
        os.environ.pop("TRACKIO_DIR", None)
        os.environ.pop("TRACKIO_SPACE_ID", None)

    def _pin(self, manifest: dict, **overrides: object) -> dict:
        from test_ultradata_factory import _cam_pin

        pin = _cam_pin(manifest, **overrides)
        self.hq_pins[manifest["pack_id"]] = pin
        return pin

    def _init_config(self) -> dict:
        self.assertTrue(self.fake.inits, "trackio.init was not called")
        return self.fake.inits[0].get("config") or {}

    def test_parse_trainer_losses_from_hf_and_kv_lines(self) -> None:
        rows = helper_ft_trackio.parse_trainer_losses(
            "\n".join(
                [
                    "{'loss': 0.42, 'epoch': 1.0, 'step': 3}",
                    "loss=0.31 epoch=2 step=6",
                    "eval_loss=0.28 step=6",
                    "no metrics on this line",
                ]
            )
        )
        self.assertEqual(rows[0]["loss"], 0.42)
        self.assertEqual(rows[0]["step"], 3)
        self.assertEqual(rows[1]["loss"], 0.31)
        self.assertEqual(rows[1]["epoch"], 2.0)
        self.assertEqual(rows[2]["eval_loss"], 0.28)

    def test_init_config_contains_three_shas_and_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            log_path = Path(tmp) / "runs" / "helper_ft.log"
            evidence = kick_helper_ft.kick(dest, log_path=log_path)
            storage = log_path.parent / "trackio"
            self.assertTrue(storage.is_dir())
            self.assertFalse((Path(tmp) / "trust").exists())
        config = self._init_config()
        self.assertEqual(self.fake.inits[0]["project"], "dottie-helper-ft")
        self.assertEqual(self.fake.inits[0]["name"], evidence["run_id"])
        self.assertEqual(config["run_id"], evidence["run_id"])
        self.assertEqual(config["sha256_pack"], manifest["sha256_pack"])
        self.assertEqual(config["sha256_train"], manifest["sha256_train"])
        self.assertEqual(config["sha256_holdout"], manifest["sha256_holdout"])
        self.assertEqual(config["pack_id"], manifest["pack_id"])
        self.assertEqual(config["rows_total"], 2)
        self.assertEqual(config["rows_train"], 1)
        self.assertEqual(config["rows_holdout"], 1)
        self.assertEqual(config["host"], evidence["host"])
        self.assertIn("git_head", config)
        self.assertNotIn("space_id", self.fake.inits[0])
        self.assertNotIn("server_url", self.fake.inits[0])
        logged_results = [row["data"].get("result") for row in self.fake.logs]
        self.assertIn("MATCH", logged_results)
        evidence_shas = [row["data"].get("sha256_evidence") for row in self.fake.logs]
        self.assertTrue(any(isinstance(item, str) and len(item) == 64 for item in evidence_shas))
        self.assertTrue(self.fake.finishes)

    def test_losses_are_logged(self) -> None:
        def start(pack_dir: Path, evidence: dict, log_path: Path) -> dict:
            del pack_dir, evidence, log_path
            return {
                "ok": True,
                "stdout": "{'loss': 0.42, 'epoch': 1.0, 'step': 3}\nloss=0.31 epoch=2 step=6\n",
            }

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            evidence = kick_helper_ft.kick(dest, start_training=start)
        losses = [row["data"] for row in self.fake.logs if "loss" in row["data"] or "eval_loss" in row["data"]]
        self.assertTrue(any(row.get("loss") == 0.42 and row.get("step") == 3 for row in losses))
        self.assertTrue(any(row.get("loss") == 0.31 and row.get("step") == 6 for row in losses))
        self.assertEqual(evidence["ok"], True)

    def test_eval_scores_attach(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            evidence = kick_helper_ft.kick(dest)
            ok = kick_helper_ft.log_eval_scores(
                evidence["run_id"],
                {
                    "Choice": 0.91,
                    "Score": 0.82,
                    "Noul": 0.73,
                    "halt_recall": 0.64,
                    "over-halt": 2,
                    "veto_fail": 1,
                },
            )
        self.assertTrue(ok)
        attached = [row["data"] for row in self.fake.logs if row["data"].get("eval_attached") == 1]
        self.assertEqual(len(attached), 1)
        self.assertEqual(attached[0]["choice"], 0.91)
        self.assertEqual(attached[0]["score"], 0.82)
        self.assertEqual(attached[0]["noul"], 0.73)
        self.assertEqual(attached[0]["halt_recall"], 0.64)
        self.assertEqual(attached[0]["over_halt"], 2)
        self.assertEqual(attached[0]["veto_fail"], 1)
        self.assertEqual(attached[0]["run_id"], evidence["run_id"])
        self.assertTrue(any(init.get("name") == evidence["run_id"] for init in self.fake.inits))

    def test_refused_kick_logs_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            _write_helper_pack(dest)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
            rc = kick_helper_ft.main(_cli_args(dest))
        self.assertEqual(rc, 1)
        self.assertEqual(ctx.exception.field, "cam-pin")
        self.assertEqual(self.kickoff_calls, [])
        refused = [row["data"] for row in self.fake.logs if row["data"].get("status") == "refused"]
        self.assertTrue(refused)
        self.assertEqual(refused[0]["field"], "cam-pin")
        self.assertTrue(any(init.get("config", {}).get("status") == "refused" for init in self.fake.inits))

    def test_pin_env_refuse_logs_refused_run(self) -> None:
        os.environ["CAM_PIN"] = "{}"
        with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
            kick_helper_ft.kick(Path("."))
        self.assertEqual(ctx.exception.field, "CAM_PIN")
        refused = [row["data"] for row in self.fake.logs if row["data"].get("status") == "refused"]
        self.assertTrue(refused)
        self.assertEqual(refused[0]["field"], "CAM_PIN")

    def test_trackio_raise_does_not_change_match(self) -> None:
        helper_ft_trackio._trackio_mod = FakeTrackio(raise_on="all")
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                evidence = kick_helper_ft.kick(dest)
        self.assertTrue(evidence["ok"])
        self.assertEqual(evidence["checkpoint_integrity_status"], "MATCH")
        self.assertGreaterEqual(len(self.kickoff_calls), 1)
        self.assertTrue(any("trackio" in str(item.message).lower() for item in caught))

    def test_trackio_raise_does_not_change_refuse(self) -> None:
        helper_ft_trackio._trackio_mod = FakeTrackio(raise_on="all")
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            _write_helper_pack(dest)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(ctx.exception.field, "cam-pin")
        self.assertEqual(self.kickoff_calls, [])

    def test_missing_trackio_match_still_ok(self) -> None:
        helper_ft_trackio.reset_for_tests()
        helper_ft_trackio._trackio_mod = None
        real_import = helper_ft_trackio.importlib.import_module

        def no_trackio(name: str, *args: object, **kwargs: object):
            if name == "trackio":
                raise ModuleNotFoundError("trackio")
            return real_import(name, *args, **kwargs)

        with patch.object(helper_ft_trackio.importlib, "import_module", side_effect=no_trackio):
            with tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / "inbox-pack"
                dest.mkdir()
                manifest = _write_helper_pack(dest)
                self._pin(manifest)
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    evidence = kick_helper_ft.kick(dest)
        self.assertTrue(evidence["ok"])
        self.assertEqual(evidence["checkpoint_integrity_status"], "MATCH")
        self.assertTrue(any("unavailable" in str(item.message).lower() for item in caught))

    def test_handler_match_inits_and_logs_integrity(self) -> None:
        def stub(body: dict) -> dict:
            return {
                "ok": True,
                "checkpoint_id": "ckpt",
                "stdout": "{'loss': 0.11, 'step': 1, 'epoch': 0.2}\n",
            }

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            body = _fresh_kickoff_body(dest, manifest, run_id="helper-ft-handler-run")
            result = helper_ft_kickoff.handle_train_kickoff(body, launch_trainer=stub)
        self.assertTrue(result["ok"])
        config = self._init_config()
        self.assertEqual(self.fake.inits[0]["name"], "helper-ft-handler-run")
        self.assertEqual(config["run_id"], "helper-ft-handler-run")
        self.assertEqual(config["sha256_pack"], manifest["sha256_pack"])
        self.assertEqual(config["sha256_train"], manifest["sha256_train"])
        self.assertEqual(config["sha256_holdout"], manifest["sha256_holdout"])
        self.assertTrue(any(row["data"].get("loss") == 0.11 for row in self.fake.logs))
        self.assertIn("MATCH", [row["data"].get("result") for row in self.fake.logs])

    def test_handler_refuse_logs_refused(self) -> None:
        result = helper_ft_kickoff.handle_train_kickoff(
            {
                "mode": "helper-ft",
                "inbox": "latest",
                "run_id": "helper-ft-refused-run",
                "pack_id": "p",
                "evidence": {"ok": True, "pack_id": "p", "run_id": "helper-ft-refused-run"},
            }
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["field"], "inbox")
        refused = [row["data"] for row in self.fake.logs if row["data"].get("status") == "refused"]
        self.assertTrue(refused)
        self.assertEqual(refused[0]["field"], "inbox")
        self.assertEqual(self.fake.inits[0]["name"], "helper-ft-refused-run")

    def test_handler_trackio_raise_still_refuses_inbox_latest(self) -> None:
        helper_ft_trackio._trackio_mod = FakeTrackio(raise_on="all")
        result = helper_ft_kickoff.handle_train_kickoff(
            {
                "mode": "helper-ft",
                "inbox": "latest",
                "run_id": "helper-ft-refused-boom",
                "evidence": {"ok": True, "pack_id": "p", "run_id": "helper-ft-refused-boom"},
                "pack_id": "p",
            }
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["field"], "inbox")
        self.assertEqual(result["actual"], "latest")

    def test_storage_dir_env_override_and_blocks_trust(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            allowed = Path(tmp) / "track-store"
            os.environ[helper_ft_trackio.DIR_ENV] = str(allowed)
            resolved = helper_ft_trackio.resolve_storage_dir(Path(tmp) / "run")
            self.assertEqual(resolved, allowed)
            os.environ[helper_ft_trackio.DIR_ENV] = str(Path(tmp) / "apps" / "dottie-os" / "trust" / "oops")
            fallback = helper_ft_trackio.resolve_storage_dir(Path(tmp) / "run")
            self.assertEqual(fallback, Path(tmp) / "run" / "trackio")
            self.assertNotIn("/trust/", str(fallback).replace("\\", "/") + "/")

    def test_forge_runner_fallback_logs_refused(self) -> None:
        repo = Path(__file__).resolve().parents[3]
        loop_src = repo / "packages" / "dottie-loop"
        runner_path = loop_src / "scripts" / "forge_runner.py"
        if str(loop_src) not in sys.path:
            sys.path.insert(0, str(loop_src))
        spec = importlib.util.spec_from_file_location("forge_runner_trackio", runner_path)
        if spec is None or spec.loader is None:
            self.fail("cannot load forge_runner")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        with patch.object(runner, "_load_helper_ft_kickoff", return_value=None):
            payload = runner.handle_train_kickoff(
                {
                    "mode": "helper-ft",
                    "inbox": "latest",
                    "run_id": "helper-ft-forge-refuse",
                    "evidence": {"ok": True, "pack_id": "p"},
                    "pack_id": "p",
                }
            )
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["field"], "inbox")
        refused = [row["data"] for row in self.fake.logs if row["data"].get("status") == "refused"]
        self.assertTrue(refused)
        self.assertEqual(refused[0]["field"], "inbox")

    def test_local_only_strips_hub_env(self) -> None:
        os.environ["TRACKIO_SPACE_ID"] = "someone/space"
        captured = {}

        def spy_init(**kwargs: object) -> None:
            captured["kwargs"] = kwargs
            captured["space"] = os.environ.get("TRACKIO_SPACE_ID")
            captured["dir"] = os.environ.get("TRACKIO_DIR")

        helper_ft_trackio._trackio_mod = SimpleNamespace(init=spy_init, log=lambda *a, **k: None, finish=lambda: None)
        with tempfile.TemporaryDirectory() as tmp:
            ok = helper_ft_trackio.init_run(
                "helper-ft-local",
                {
                    "run_id": "helper-ft-local",
                    "sha256_pack": "a" * 64,
                    "sha256_train": "b" * 64,
                    "sha256_holdout": "c" * 64,
                },
                run_dir=Path(tmp),
            )
        self.assertTrue(ok)
        self.assertNotIn("space_id", captured["kwargs"])
        self.assertIsNone(captured["space"])
        self.assertTrue(str(captured["dir"]).endswith("trackio"))
        self.assertEqual(os.environ.get("TRACKIO_SPACE_ID"), "someone/space")

    def test_disable_env_skips_tracker(self) -> None:
        os.environ[helper_ft_trackio.ENABLE_ENV] = "0"
        helper_ft_trackio.reset_for_tests()
        helper_ft_trackio._trackio_mod = self.fake
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            evidence = kick_helper_ft.kick(dest)
        self.assertTrue(evidence["ok"])
        self.assertEqual(self.fake.inits, [])
        self.assertEqual(self.fake.logs, [])


if __name__ == "__main__":
    unittest.main()
