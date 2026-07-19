#!/usr/bin/env python3
"""
PDF to Ava Wiki Ingest — 2h poll
Solo personal project, no connection to employer, built with public/free-tier only

Poll Drive folder Ava/Papers/Inbox (id 10tYYtiJsmxdqFy0b3V7FbLP0J9_g7MM5) for new PDFs and ingest.

- Lists PDFs via hatch_gws_cli drive files list with q "'10tYYtiJsmxdqFy0b3V7FbLP0J9_g7MM5' in parents and trashed=false and mimeType='application/pdf'"
- Downloads new PDFs only (dedupe via ~/.openwiki/wiki/papers/.ingest_state.json tracking drive_file_id + sha256)
- Local extraction via PyMuPDF/fitz -> pdfminer -> pdftotext (privacy: no paper content sent externally)
- Summarization: tries local Ollama qwen3:32b at http://localhost:11434/api/generate, else deterministic extractive fallback
- Concept mapping via ava/memory/openwiki_adapter.py for S2 Slow hl=300, plus Ava J-Space tags S1 Fast/S2 Slow/Critic/Planner
- Writes markdown to ~/.openwiki/wiki/papers/<slug>.md with YAML frontmatter
- Adds backlinks to existing wiki pages and Ava experiments
- Git adds + commits in ~/.openwiki repo with message "wiki(pdf): <slug>"
"""

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import datetime
from typing import Dict, List

DRIVE_FOLDER_ID = "10tYYtiJsmxdqFy0b3V7FbLP0J9_g7MM5"
WIKI_PAPERS_DIR = pathlib.Path.home() / ".openwiki" / "wiki" / "papers"
STATE_PATH = WIKI_PAPERS_DIR / ".ingest_state.json"
FACTORY_ROOT = pathlib.Path.home() / "workspace" / "ava-agi-factory-v6-4"

def run_gws_list():
    cmd = [
        "hatch_gws_cli", "drive", "files", "list",
        "--format", "json",
        "--params", json.dumps({
            "q": f"'{DRIVE_FOLDER_ID}' in parents and trashed=false and mimeType='application/pdf'",
            "pageSize": 20
        })
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Drive list failed: {result.stderr}", file=sys.stderr)
        return []
    try:
        data = json.loads(result.stdout)
        return data.get("files", [])
    except Exception as e:
        print(f"Parse drive list failed: {e} {result.stdout[:500]}", file=sys.stderr)
        return []

def load_state() -> Dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except:
            return {}
    return {}

def save_state(state: Dict):
    WIKI_PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))

def download_pdf(file_id: str, dest: pathlib.Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "hatch_gws_cli", "drive", "files", "get",
        "--params", json.dumps({"fileId": file_id, "alt": "media"}),
        "-o", str(dest)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not dest.exists():
        # try alternative: files get with output
        print(f"Download failed for {file_id}: {result.stderr}", file=sys.stderr)
        return False
    return True

def sha256_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()

def extract_text(pdf_path: pathlib.Path) -> str:
    text = ""
    # Try PyMuPDF
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        for page in doc:
            text += page.get_text() + "\n"
        if len(text.strip()) > 100:
            print(f"Extracted via PyMuPDF {len(text)} chars")
            return text
    except Exception as e:
        print(f"fitz failed: {e}")
    # pdfminer
    try:
        from pdfminer.high_level import extract_text as pdfminer_extract
        text = pdfminer_extract(str(pdf_path))
        if len(text.strip()) > 100:
            print(f"Extracted via pdfminer {len(text)} chars")
            return text
    except Exception as e:
        print(f"pdfminer failed: {e}")
    # pdftotext
    try:
        result = subprocess.run(["pdftotext", str(pdf_path), "-"], capture_output=True, text=True)
        if result.returncode == 0 and len(result.stdout) > 100:
            print(f"Extracted via pdftotext {len(result.stdout)} chars")
            return result.stdout
    except Exception as e:
        print(f"pdftotext failed: {e}")
    return text

def summarize_local(text: str, title: str) -> str:
    # Try Ollama qwen3:32b
    prompt = f"Summarize this research paper '{title}' - extract contributions, methods, results, and relevance to Ava AGI Factory J-Space memory (S1 Fast, S2 Slow hl=300, Critic, Planner). Keep concise, 200 words max. Text excerpt:\n\n{text[:8000]}"
    try:
        import requests
        for host in ["http://localhost:11434", "http://host.docker.internal:11434"]:
            try:
                resp = requests.post(f"{host}/api/generate", json={
                    "model": "qwen3:32b",
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": 400}
                }, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    summary = data.get("response", "")
                    if len(summary) > 50:
                        print(f"Summarized via Ollama {host} qwen3:32b")
                        return summary.strip()
            except Exception as e:
                print(f"Ollama {host} failed: {e}")
                continue
    except Exception as e:
        print(f"requests/Ollama not available: {e}")

    # Fallback deterministic extractive
    sentences = re.split(r'(?<=[.!?])\s+', text)
    # heuristic: first 5, plus sentences containing contrib/method/result keywords
    keywords = ["contribut", "method", "approach", "result", "experiment", "conclusion", "propose", "memory", "J-space", "verbaliz", "training", "curriculum"]
    selected = sentences[:6]
    for s in sentences[6:]:
        low = s.lower()
        if any(k in low for k in keywords) and len(s) > 20:
            selected.append(s)
        if len(selected) >= 20:
            break
    summary = " ".join(selected)[:2000]
    # Structure
    return f"""## Contributions
{selected[0] if selected else text[:300]}

## Methods
{" ".join([s for s in selected if 'method' in s.lower() or 'approach' in s.lower()][:3]) or 'Extractive fallback - methods section not clearly detected.'}

## Results
{" ".join([s for s in selected if 'result' in s.lower() or 'experiment' in s.lower()][:3]) or 'Extractive fallback - results not clearly detected.'}

## Full Extractive Summary
{summary}
"""

def slugify(name: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return s[:60]

def concept_map_via_adapter(text: str, title: str) -> tuple[List[str], List[str]]:
    ava_tags = ["OpenWiki", "S2 Slow"]
    concepts = []
    try:
        sys.path.insert(0, str(FACTORY_ROOT))
        from dottie.memory.openwiki_adapter import scan_wiki, parse_wiki_file
        wiki_pages = scan_wiki(limit=50)
        # extract concepts from current text via _extract_concepts if available, else heuristic
        concepts = [p.title for p in wiki_pages[:5]]
        # Tag heuristics
        low = (title + " " + text[:2000]).lower()
        if "j-space" in low or "j space" in low or "memory" in low:
            ava_tags.append("J-Space")
        if "training" in low or "loop" in low or "curriculum" in low:
            ava_tags.extend(["S1 Fast", "Planner"])
        if "synthetic" in low or "data" in low:
            ava_tags.append("AGI-Factory")
        if "critic" in low or "evaluat" in low:
            ava_tags.append("Critic")
        # ensure uniqueness
        ava_tags = list(dict.fromkeys(ava_tags))
        return ava_tags, concepts
    except Exception as e:
        print(f"openwiki_adapter failed: {e}")
        # fallback tags
        low = (title + text[:2000]).lower()
        if "memory" in low:
            ava_tags.append("J-Space")
        if "training" in low:
            ava_tags.append("S1 Fast")
        return list(dict.fromkeys(ava_tags + ["J-Space", "S2 Slow"])), ["Ava AGI Factory", "Verbalizable Memory"]

def list_experiments() -> List[str]:
    exp_dir = FACTORY_ROOT / "experiments"
    if not exp_dir.exists():
        exp_dir = FACTORY_ROOT / "dottie" / "experiments"
    exps = []
    if exp_dir.exists():
        for f in exp_dir.glob("*.md"):
            exps.append(f.name)
    # fallback list from repo
    if not exps:
        exps = ["branch_eval_results.json", "frontier_eval_results.json"]
    return exps[:5]

def write_wiki_page(slug_base: str, title: str, source_pdf: str, drive_file_id: str, sha256: str, summary: str, ava_tags: List[str], concepts: List[str], text_len: int) -> pathlib.Path:
    sha_short = sha256[:6]
    slug = f"{slug_base}-{sha_short}"
    WIKI_PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    path = WIKI_PAPERS_DIR / f"{slug}.md"
    exps = list_experiments()
    backlinks = "\n".join([f"- [[{c}]]" for c in concepts[:5]])
    exp_links = "\n".join([f"- experiment: {e}" for e in exps[:3]])
    now = datetime.datetime.utcnow().isoformat() + "Z"
    frontmatter = f"""---
title: "{title}"
source_pdf: "{source_pdf}"
drive_file_id: "{drive_file_id}"
sha256: "{sha256}"
ingested_at: "{now}"
ava_tags: [{', '.join(ava_tags)}]
concepts: [{', '.join(concepts[:5])}]
text_length: {text_len}
---

"""
    body = f"""{frontmatter}
# {title}

*Source:* `{source_pdf}` (Drive ID `{drive_file_id}`)
*SHA256:* `{sha256}` | *Ingested:* {now}

## Summary
{summary}

## Ava J-Space Mapping
- S2 Slow hl=300 verbalizable memory concepts: {', '.join(concepts[:5])}
- Tags: {', '.join(ava_tags)}
- Relevance: This paper maps to S2 Slow deliberative workspace for long-term reportable concepts, with connections to S1 Fast reactive and Critic/Planner.

## Backlinks
{backlinks}

## Related Ava Experiments
{exp_links}
- [[Ava Training Loop]]
- [[Verbalizable Memory]]

## Extracted Metadata
- Drive folder: Ava/Papers/Inbox (10tYYtiJsmxdqFy0b3V7FbLP0J9_g7MM5)
- Local wiki path: {path}
- Privacy: local parsing only (PyMuPDF/pdfminer/pdftotext), no external send unless local Ollama qwen3:32b used.

---
Solo personal project, no connection to employer, built with public/free-tier only
"""
    path.write_text(body, encoding='utf-8')
    return path

def git_commit(slug: str, path: pathlib.Path):
    repo_root = pathlib.Path.home() / ".openwiki"
    try:
        subprocess.run(["git", "-C", str(repo_root), "add", str(path)], check=False)
        subprocess.run(["git", "-C", str(repo_root), "add", str(STATE_PATH)], check=False)
        subprocess.run(["git", "-C", str(repo_root), "commit", "-m", f"wiki(pdf): {slug}"], check=False, capture_output=True)
        print(f"Git committed {slug}")
    except Exception as e:
        print(f"Git commit failed: {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=3)
    args = parser.parse_args()

    print(f"Polling Drive folder {DRIVE_FOLDER_ID} (Ava/Papers/Inbox)")
    files = run_gws_list()
    print(f"Found {len(files)} PDFs in Drive")
    state = load_state()
    print(f"Existing state entries: {len(state)}")

    new_files = []
    for f in files:
        fid = f.get("id")
        if fid in state:
            print(f"Skipping already ingested {f.get('name')} ({fid})")
            continue
        new_files.append(f)

    if not new_files:
        print("No new PDFs to ingest.")
        print(f"State file: {STATE_PATH}")
        if STATE_PATH.exists():
            print(STATE_PATH.read_text()[:2000])
        # git log
        subprocess.run(["git", "-C", str(pathlib.Path.home()/".openwiki"), "log", "--oneline", "-n", "10"])
        return

    tmp_dir = pathlib.Path("/tmp/pdf_ingest")
    tmp_dir.mkdir(exist_ok=True)

    count = 0
    for f in new_files[:args.max]:
        fid = f["id"]
        name = f["name"]
        print(f"\n--- Processing {name} ({fid}) ---")
        tmp_pdf = tmp_dir / f"{fid}.pdf"
        if not download_pdf(fid, tmp_pdf):
            print(f"Failed download {fid}")
            continue
        sha = sha256_file(tmp_pdf)
        # check sha dup
        dup = False
        for v in state.values():
            if v.get("sha256") == sha:
                print(f"Skipping duplicate sha256 {sha} for {name}")
                dup = True
                break
        if dup:
            # record fid as alias to existing to avoid reprocessing
            state[fid] = {"drive_file_id": fid, "source_pdf": name, "sha256": sha, "duplicate_of": sha}
            save_state(state)
            continue

        text = extract_text(tmp_pdf)
        if len(text.strip()) < 50:
            print(f"Extraction too short for {name}, skipping")
            continue

        title = name.replace(".pdf", "").replace("-", " ").title()
        summary = summarize_local(text, title)
        ava_tags, concepts = concept_map_via_adapter(text, title)
        slug_base = slugify(title)

        wiki_path = write_wiki_page(slug_base, title, name, fid, sha, summary, ava_tags, concepts, len(text))

        # update state
        state[fid] = {
            "drive_file_id": fid,
            "source_pdf": name,
            "sha256": sha,
            "wiki_path": str(wiki_path),
            "slug": wiki_path.stem,
            "ingested_at": datetime.datetime.utcnow().isoformat() + "Z",
            "ava_tags": ava_tags
        }
        save_state(state)
        git_commit(wiki_path.stem, wiki_path)
        count += 1
        print(f"Ingested {name} -> {wiki_path}")

    print(f"\nDone. Ingested {count} new PDFs.")
    save_state(state)
    # log final
    print(f"State now {len(state)} entries")
    subprocess.run(["git", "-C", str(pathlib.Path.home()/".openwiki"), "log", "--oneline", "-n", "10"])

if __name__ == "__main__":
    main()
