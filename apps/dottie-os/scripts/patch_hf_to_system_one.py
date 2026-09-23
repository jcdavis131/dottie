#!/usr/bin/env python3
"""Surgical patch: wire UltraData pack_v2 into hf_to_system_one.py (UTF-8 no BOM).

Idempotent. Does not invent nimble generators. Does not touch LIVE/champion.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

MARKER = "# --- ultradata_curriculum pack_v2 wire (auto) ---"

IMPORT_BLOCK = f"""
{MARKER}
try:
    from sidecar.curation.ultradata_curriculum import (  # type: ignore
        curate_ultradata_agent,
        curate_ultradata_code,
        curate_ultradata_math,
        curate_pack_v2,
    )
except ImportError:
    from ultradata_curriculum import (  # type: ignore
        curate_ultradata_agent,
        curate_ultradata_code,
        curate_ultradata_math,
        curate_pack_v2,
    )
"""

DISPATCH_BLOCK = f'''
    {MARKER} dispatch
    if args.dataset in ("pack_v2", "ultradata_pack_v2"):
        staging = Path(getattr(args, "out_dir", None) or getattr(args, "staging", None) or "registry/datasets/staging")
        if not staging.is_absolute():
            staging = Path.cwd() / staging
        agent_n = int(getattr(args, "agent_n", 400) or 400)
        code_n = int(getattr(args, "code_n", 300) or 300)
        math_n = int(getattr(args, "math_n", 200) or 200)
        n = getattr(args, "n", None)
        if n:
            scale = float(n) / 400.0
            agent_n = max(300, min(500, int(400 * scale)))
            code_n = max(200, min(400, int(300 * scale)))
            math_n = max(150, min(300, int(200 * scale)))
        summary = curate_pack_v2(
            staging,
            agent_n=agent_n,
            code_n=code_n,
            math_n=math_n,
            curate_all_fn=globals().get("curate_all"),
        )
        print(json.dumps(summary, indent=2))
        return
    if args.dataset in ("ultradata_agent", "agent"):
        rows = curate_ultradata_agent(int(getattr(args, "n", 400) or 400))
        out = Path(getattr(args, "out", None) or "registry/datasets/staging/curated_ultradata_agent.jsonl")
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\\n")
        print({{"wrote": str(out), "n": len(rows)}})
        return
    if args.dataset in ("ultradata_code", "code"):
        rows = curate_ultradata_code(int(getattr(args, "n", 300) or 300))
        out = Path(getattr(args, "out", None) or "registry/datasets/staging/curated_ultradata_code.jsonl")
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\\n")
        print({{"wrote": str(out), "n": len(rows)}})
        return
    if args.dataset in ("ultradata_math", "math"):
        rows = curate_ultradata_math(int(getattr(args, "n", 200) or 200))
        out = Path(getattr(args, "out", None) or "registry/datasets/staging/curated_ultradata_math.jsonl")
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\\n")
        print({{"wrote": str(out), "n": len(rows)}})
        return
'''


def _ensure_imports(text: str, changed: list[str]) -> str:
    if MARKER in text and "curate_pack_v2" in text:
        return text
    m = re.search(r"(^from __future__ import[^\n]*\n)", text, re.M)
    if m:
        text = text[: m.end()] + "\n" + IMPORT_BLOCK + text[m.end() :]
    else:
        text = IMPORT_BLOCK + "\n" + text
    changed.append("import")
    return text


def _ensure_std_imports(text: str, changed: list[str]) -> str:
    if "import json" not in text:
        text = "import json\n" + text
        changed.append("import_json")
    if "from pathlib import Path" not in text and "import pathlib" not in text:
        text = "from pathlib import Path\n" + text
        changed.append("import_path")
    return text


def _ensure_choices(text: str, changed: list[str]) -> str:
    extras = ["pack_v2", "ultradata_agent", "ultradata_code", "ultradata_math"]

    def repl(match: re.Match) -> str:
        block = match.group(0)
        if "pack_v2" in block:
            return block
        m = re.search(r"choices\s*=\s*\[([^\]]*)\]", block)
        if not m:
            return block
        inner = m.group(1).strip()
        prefix = ", ".join(f'"{e}"' for e in extras)
        new_inner = prefix + (", " + inner if inner else "")
        new_block = block[: m.start(1)] + new_inner + block[m.end(1) :]
        return new_block

    new_text, n = re.subn(
        r"add_argument\([^\)]*--dataset[^\)]*\)",
        repl,
        text,
        count=1,
        flags=re.S,
    )
    if n and new_text != text:
        changed.append("argparse_choices")
    return new_text


def _ensure_cap_args(text: str, changed: list[str]) -> str:
    if "--agent-n" in text:
        return text
    new_text, n = re.subn(
        r"(\n)([ \t]*)(args\s*=\s*parser\.parse_args\(\))",
        (
            r"\1\2parser.add_argument('--agent-n', type=int, default=400)\n"
            r"\2parser.add_argument('--code-n', type=int, default=300)\n"
            r"\2parser.add_argument('--math-n', type=int, default=200)\n"
            r"\1\2\3"
        ),
        text,
        count=1,
    )
    if n:
        changed.append("cap_args")
    return new_text


def _ensure_dispatch(text: str, changed: list[str]) -> str:
    if MARKER + " dispatch" in text:
        return text
    # Insert AFTER parse_args()
    m = re.search(r"([ \t]*)args\s*=\s*parser\.parse_args\(\)[^\n]*\n", text)
    if not m:
        # fallback: end of main before if __name__
        m2 = re.search(r"\nif __name__", text)
        if not m2:
            raise SystemExit("cannot find parse_args() or __main__ to insert dispatch")
        text = text[: m2.start()] + "\n" + DISPATCH_BLOCK + text[m2.start() :]
        changed.append("dispatch_fallback")
        return text
    insert_at = m.end()
    text = text[:insert_at] + DISPATCH_BLOCK + text[insert_at:]
    changed.append("dispatch")
    return text


def patch(path: Path) -> dict:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    text = raw.decode("utf-8")
    changed: list[str] = []
    text = _ensure_imports(text, changed)
    text = _ensure_std_imports(text, changed)
    text = _ensure_choices(text, changed)
    text = _ensure_cap_args(text, changed)
    text = _ensure_dispatch(text, changed)
    out = text.encode("utf-8")
    path.write_bytes(out)
    return {"path": str(path), "changed": changed, "bytes": len(out), "bom": False}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--target",
        type=Path,
        default=Path(r"C:\Users\jcdav\workspace\dottie-os\sidecar\curation\hf_to_system_one.py"),
    )
    args = ap.parse_args()
    if not args.target.is_file():
        raise SystemExit(f"missing target: {args.target}")
    bak = args.target.with_suffix(args.target.suffix + ".bak_pre_pack_v2")
    if not bak.exists():
        bak.write_bytes(args.target.read_bytes())
    info = patch(args.target)
    print(info)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
