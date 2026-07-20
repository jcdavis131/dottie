# Solo personal project, no connection to employer, built with public/free-tier only
"""detect.py — collection allowlist, ignore patterns, size cap."""

from pathlib import Path

from personal_graphify.detect import collect_files, group_by_type, is_collectible


class TestIsCollectible:
    def test_known_extensions(self):
        assert is_collectible(Path("a.py"))
        assert is_collectible(Path("b.TS"))
        assert is_collectible(Path("doc.md"))
        assert is_collectible(Path("img.png"))

    def test_known_extensionless_names(self):
        assert is_collectible(Path("Dockerfile"))
        assert is_collectible(Path("Makefile"))
        assert is_collectible(Path("justfile"))

    def test_skipped(self):
        assert not is_collectible(Path("LICENSE"))
        assert not is_collectible(Path("random_binary"))
        assert not is_collectible(Path("app.exe"))
        assert not is_collectible(Path("data.parquet"))
        assert not is_collectible(Path("Cargo.lock"))


class TestCollectFiles:
    def test_collects_and_ignores(self, tmp_path):
        root = tmp_path / "repo"
        (root / "src").mkdir(parents=True)
        (root / "node_modules" / "pkg").mkdir(parents=True)
        (root / "src" / "main.py").write_text("print(1)\n")
        (root / "src" / "notes.md").write_text("# hi\n")
        (root / "Dockerfile").write_text("FROM python\n")
        (root / "LICENSE").write_text("MIT\n")
        (root / "blob.bin").write_text("xx")
        (root / "node_modules" / "pkg" / "index.js").write_text("x")
        (root / ".gitignore").write_text("secret.py\n")
        (root / "secret.py").write_text("token = 'x'\n")

        names = {f.name for f in collect_files(root)}
        assert {"main.py", "notes.md", "Dockerfile"} <= names
        assert "LICENSE" not in names
        assert "blob.bin" not in names
        assert "index.js" not in names  # node_modules pruned
        assert "secret.py" not in names  # .gitignore honored
        assert ".gitignore" not in names  # extensionless, not allowlisted

    def test_size_cap_5mb(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        big = root / "big.py"
        with open(big, "wb") as f:
            f.seek(5 * 1024 * 1024)
            f.write(b"#")
        (root / "small.py").write_text("x = 1\n")
        names = {f.name for f in collect_files(root)}
        assert "small.py" in names
        assert "big.py" not in names

    def test_max_files_cap(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        for i in range(10):
            (root / f"f{i}.py").write_text("pass\n")
        assert len(collect_files(root, max_files=4)) == 4


class TestGroupByType:
    def test_groups(self, tmp_path):
        files = [Path("a.py"), Path("b.md"), Path("c.png")]
        groups = group_by_type(files)
        assert groups["code"] == [Path("a.py")]
        assert Path("b.md") in groups["docs"]
        assert groups["media"] == [Path("c.png")]
