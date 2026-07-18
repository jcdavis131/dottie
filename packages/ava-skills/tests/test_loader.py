# Solo personal project, no connection to employer, built with public/free-tier only
"""loader: frontmatter parsing, topo sort (+cycle fallback), wRRF determinism,
describe()/manifest consistency, Tier-A-first graph execution."""

from pathlib import Path

from conftest import SKILLS_DIR, load_skill_module
from skills.loader import SkillLoader, _parse_frontmatter, describe_from_manifest


class TestFrontmatterParsing:
    def test_parses_yaml_frontmatter(self):
        text = (
            "---\n"
            "name: demo\n"
            "description: a demo skill\n"
            "triggers:\n- alpha\n- beta\n"
            "half_life: 42\n"
            "---\n"
            "# Body\ncontent here\n"
        )
        meta, body = _parse_frontmatter(text)
        assert meta["name"] == "demo"
        assert meta["triggers"] == ["alpha", "beta"]
        assert int(meta["half_life"]) == 42
        assert body.startswith("# Body")

    def test_no_frontmatter_returns_empty_meta(self):
        meta, body = _parse_frontmatter("just a plain document")
        assert meta == {}
        assert body == "just a plain document"

    def test_every_manifest_parses_with_required_fields(self):
        for md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
            meta, _ = _parse_frontmatter(md.read_text(encoding="utf-8"))
            assert meta.get("name") == md.parent.name, md
            for field in ("description", "j_space_target", "half_life", "triggers", "version"):
                assert field in meta, f"{md} missing {field}"
            # honesty fields introduced by the manifest cleanup
            assert meta.get("provider") == "none", f"{md} claims an LLM provider it does not use"
            assert meta.get("connectors") == [], f"{md} claims connectors it does not use"


class TestTopoSort:
    def test_requires_and_precedes_respected(self):
        loader = SkillLoader()
        order = loader.topological_sort()
        assert sorted(order) == sorted(loader.skills.keys())
        idx = {n: i for i, n in enumerate(order)}
        for name, sk in loader.skills.items():
            for req in sk.requires:
                if req in idx:
                    assert idx[req] < idx[name], f"{req} must precede {name}"
            for succ in sk.precedes:
                if succ in idx:
                    assert idx[name] < idx[succ], f"{name} must precede {succ}"

    def test_cycle_falls_back_to_all_skills(self, tmp_path):
        for a, b in (("aaa", "bbb"), ("bbb", "aaa")):
            d = tmp_path / a
            d.mkdir()
            (d / "SKILL.md").write_text(
                f"---\nname: {a}\ndescription: cyclic\ntriggers: []\n"
                f"requires:\n- {b}\nversion: 1.0.0\n---\nbody\n"
            )
        loader = SkillLoader(skills_dir=tmp_path)
        order = loader.topological_sort()
        # cycle: neither can be topologically placed, but both must still appear
        assert sorted(order) == ["aaa", "bbb"]


class TestWrrfRerank:
    FIXED = {"trigger": 0.6, "hl": 0.15, "graph": 0.25}

    def test_deterministic_with_fixed_weights(self):
        loader = SkillLoader()
        a = loader.wrrf_rerank("inspect jspace safety", weights=dict(self.FIXED))
        b = loader.wrrf_rerank("inspect jspace safety", weights=dict(self.FIXED))
        assert a == b
        # and stable across a fresh loader over the same manifests
        c = SkillLoader().wrrf_rerank("inspect jspace safety", weights=dict(self.FIXED))
        assert a == c

    def test_scores_sorted_descending_and_cover_all_skills(self):
        loader = SkillLoader()
        ranked = loader.wrrf_rerank("memory shard mint", weights=dict(self.FIXED))
        names = [n for n, _ in ranked]
        scores = [s for _, s in ranked]
        assert sorted(names) == sorted(loader.skills.keys())
        assert scores == sorted(scores, reverse=True)

    def test_broadcast_signal_removed(self):
        loader = SkillLoader()
        # default weights must not reference the removed constant broadcast signal
        assert loader.wrrf_rerank("anything")  # runs without a 'broadcast' weight key


class TestDescribeManifestConsistency:
    def test_every_skill_describe_matches_frontmatter(self):
        for d in sorted(p for p in SKILLS_DIR.iterdir() if (p / "skill.py").exists()):
            mod = load_skill_module(d.name)
            assert hasattr(mod, "describe"), f"{d.name} has no describe()"
            desc = mod.describe()
            expected = describe_from_manifest(d)
            assert desc == expected, f"{d.name} describe() drifted from SKILL.md"


class TestRunWithGraphTierA:
    def test_safety_scanner_runs_first_when_in_graph(self, monkeypatch):
        loader = SkillLoader()
        executed = []

        def fake_run(name, **kwargs):
            executed.append(name)
            return {"skill": name, "pass": True}

        monkeypatch.setattr(loader, "run", fake_run)
        # query that pulls in skills requiring safety-scanner
        loader.run_with_graph("safety check then inspect jspace")
        assert "safety-scanner" in executed, "Tier A gate missing from resolved graph"
        assert executed[0] == "safety-scanner", f"Tier A must execute first, got {executed}"
