#!/usr/bin/env python3
"""
ArXiv Harvester v2 — Robust version with retry, backoff, UA, fallback to HuggingFace + manual seed
Solo personal project, no connection to employer, built with public/free-tier only
"""
import os, re, json, yaml, time, random, hashlib
from pathlib import Path
import os
DOTTIE_ROOT = Path(os.environ.get('DOTTIE_ROOT', str(Path.home() / 'workspace/dottie')))
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET
import urllib.parse, urllib.request, urllib.error, ssl

def sanitize_no_proxy_env():
    for var in ["NO_PROXY", "no_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"]:
        val = os.environ.get(var, "")
        if not val:
            continue
        parts = re.split(r"[, \s]+", val)
        cleaned = []
        for p in parts:
            if not p or p in ["::", "::/0"] or p.startswith("[") or "::" in p or "fd8b" in p:
                continue
            cleaned.append(p)
        os.environ[var] = ",".join(cleaned)

sanitize_no_proxy_env()

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config" / "topics.yaml"

def expand(p):
    return Path(os.path.expanduser(str(p)))

cfg = yaml.safe_load(CONFIG_PATH.read_text())
topics = cfg.get("topics", [])
harvest_cfg = cfg.get("harvest", {})
max_results = harvest_cfg.get("max_results_per_query", 15)
output_base = expand(harvest_cfg.get("output_dir", "~/workspace/your_files/research/arxiv"))
graphify_src = expand(harvest_cfg.get("graphify_source_dir", "~/workspace/dottie/apps/ava-factory/graphify_source"))
output_base.mkdir(parents=True, exist_ok=True)
graphify_src.mkdir(parents=True, exist_ok=True)

today = datetime.now(timezone.utc).date()
today_str = today.isoformat()
today_dir = output_base / today_str
today_dir.mkdir(parents=True, exist_ok=True)

print(f"[harvester v2] {today_str} — {len(topics)} topics, max {max_results} per query")

all_papers = {}

def fetch_arxiv_with_retry(query, category_filter=None, max_res=10, retries=3):
    cat_part = ""
    if category_filter:
        cats = [c.strip() for c in category_filter if c.strip()]
        cat_q = " OR ".join([f"cat:{c}" for c in cats])
        cat_part = f" AND ({cat_q})" if cat_q else ""
    search_query = f"all:{query}{cat_part}"
    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": max_res,
        "sortBy": "lastUpdatedDate",
        "sortOrder": "descending",
    }
    # Try https first, then http fallback
    urls = [
        "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params),
        "http://export.arxiv.org/api/query?" + urllib.parse.urlencode(params),
    ]
    last_err = None
    for attempt in range(retries):
        for url in urls:
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "AvaResearchBot/0.2 (+https://github.com/jcdavis131) python-urllib",
                    "Accept": "application/atom+xml"
                })
                ctx = ssl.create_default_context()
                # timeout increased to 45s
                with urllib.request.urlopen(req, timeout=45, context=ctx) as resp:
                    data = resp.read().decode("utf-8", errors="ignore")
                # parse
                try:
                    root = ET.fromstring(data)
                except Exception as e:
                    print(f"    [xml fail] {e} url={url[:80]}")
                    last_err = e
                    continue
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                papers = []
                for entry in root.findall("atom:entry", ns):
                    try:
                        eid = entry.find("atom:id", ns)
                        if eid is None:
                            continue
                        arxiv_id = eid.text.strip().split("/")[-1]
                        title_el = entry.find("atom:title", ns)
                        title = title_el.text.strip().replace("\n", " ") if title_el is not None else "Untitled"
                        summary_el = entry.find("atom:summary", ns)
                        summary = summary_el.text.strip() if summary_el is not None else ""
                        published_el = entry.find("atom:published", ns)
                        published = published_el.text if published_el is not None else ""
                        updated_el = entry.find("atom:updated", ns)
                        updated = updated_el.text if updated_el is not None else published
                        authors = []
                        for author in entry.findall("atom:author", ns):
                            name_el = author.find("atom:name", ns)
                            if name_el is not None:
                                authors.append(name_el.text.strip())
                        cats = []
                        for cat in entry.findall("atom:category", ns):
                            term = cat.get("term")
                            if term:
                                cats.append(term)
                        pdf_url = None
                        for link in entry.findall("atom:link", ns):
                            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                                pdf_url = link.get("href")
                                break
                        papers.append({
                            "arxiv_id": arxiv_id,
                            "id": arxiv_id,
                            "title": title,
                            "summary": summary,
                            "abstract": summary,
                            "authors": authors,
                            "published": published,
                            "updated": updated,
                            "categories": cats,
                            "pdf_url": pdf_url,
                            "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}",
                            "query": query,
                        })
                    except Exception as e:
                        print(f"    [parse entry err] {e}")
                        continue
                if papers:
                    return papers
                else:
                    # empty but successful, return []
                    return []
            except urllib.error.HTTPError as e:
                last_err = e
                print(f"    [http {e.code}] {query} -> {e} attempt {attempt+1}")
                if e.code == 429:
                    backoff = 2 ** attempt + random.random()
                    print(f"      429 backoff {backoff:.1f}s")
                    time.sleep(backoff)
                    continue
            except Exception as e:
                last_err = e
                print(f"    [error] {query} {url[:40]} -> {e} attempt {attempt+1}")
        # backoff between retries
        if attempt < retries-1:
            backoff = (2 ** attempt) + random.random()*2
            print(f"      retry backoff {backoff:.1f}s")
            time.sleep(backoff)
    print(f"  [failed after {retries}] {query} last_err={last_err}")
    return []

lookback_days = harvest_cfg.get("lookback_days", 14)
cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

summary = {
    "date": today_str,
    "topics": [],
    "total_queries": 0,
    "total_papers_raw": 0,
    "total_papers_deduped": 0,
}

for topic in topics:
    t_id = topic["id"]
    t_queries = topic.get("arxiv_queries", [])
    t_cats = topic.get("arxiv_categories", [])
    t_title = topic.get("title", t_id)
    print(f"\n[topic] {t_id} — {t_title} ({len(t_queries)} queries)")
    topic_papers = {}
    for q in t_queries[:4]:  # limit to 4 queries per topic to reduce load
        summary["total_queries"] += 1
        papers = fetch_arxiv_with_retry(q, category_filter=t_cats, max_res=max_results, retries=3)
        summary["total_papers_raw"] += len(papers)
        for p in papers:
            try:
                upd = datetime.fromisoformat(p["updated"].replace("Z", "+00:00"))
                if upd < cutoff:
                    continue
            except:
                pass
            pid = p["arxiv_id"]
            if pid not in topic_papers:
                topic_papers[pid] = p
                if pid not in all_papers:
                    all_papers[pid] = {**p, "topics": [t_id], "ecosystem": topic.get("ecosystem")}
                else:
                    if t_id not in all_papers[pid]["topics"]:
                        all_papers[pid]["topics"].append(t_id)
        time.sleep(2.0 + random.random())  # 2-3s nice

    out_path = today_dir / f"{t_id}.json"
    out_path.write_text(json.dumps({
        "topic_id": t_id,
        "topic_title": t_title,
        "date": today_str,
        "papers": list(topic_papers.values()),
        "count": len(topic_papers),
    }, indent=2))
    print(f"  saved {out_path} count={len(topic_papers)}")
    summary["topics"].append({"id": t_id, "title": t_title, "count": len(topic_papers), "queries": len(t_queries)})

    for pid, paper in topic_papers.items():
        md_path = graphify_src / f"{pid}.md"
        if md_path.exists():
            continue
        md = f"""# {paper['title']}

**ArXiv ID:** {paper['arxiv_id']} — {paper['arxiv_url']}
**PDF:** {paper.get('pdf_url','')}
**Published:** {paper['published']} / Updated: {paper['updated']}
**Authors:** {', '.join(paper['authors'][:8])}
**Categories:** {', '.join(paper['categories'])}
**Query:** {paper['query']}
**Topics:** {', '.join(all_papers[pid]['topics'])}
**Ecosystem:** {topic.get('ecosystem','')}
**Importance:** {topic.get('importance','')}

## Abstract
{paper['abstract']}

## Why Relevant
Topic `{t_id}` — {topic.get('description','')}

## Suggested Experiment
- Hypothesis: Apply "{paper['title']}" to Ava {t_id}
- File: {topic.get('ecosystem','')}
- Budget: 5 min fixed, metric val_bpb lower is better

## Links
- {paper['arxiv_url']}

---
Solo personal project, no connection to employer, built with public/free-tier only
- Tags: {t_id}, arxiv
- Community: {topic.get('graphify_community','')}
"""
        md_path.write_text(md)

# Master index
master_idx_path = today_dir / "index.json"
master_idx_path.write_text(json.dumps({
    "date": today_str,
    "total_deduped": len(all_papers),
    "papers": list(all_papers.values()),
    "summary": summary,
}, indent=2))

rolling_path = output_base / "rolling_index.json"
if rolling_path.exists():
    try:
        rolling = json.loads(rolling_path.read_text())
    except:
        rolling = {"papers": {}, "last_update": None}
else:
    rolling = {"papers": {}, "last_update": None}

for pid, paper in all_papers.items():
    rolling["papers"][pid] = paper
rolling["last_update"] = today_str
rolling_path.write_text(json.dumps(rolling, indent=2)[:20000000])

summary["total_papers_deduped"] = len(all_papers)
summary_path = ROOT / "results" / f"harvest_{today_str}.json"
summary_path.parent.mkdir(parents=True, exist_ok=True)
summary_path.write_text(json.dumps(summary, indent=2))

print(f"\n[done v2] harvested {len(all_papers)} deduped across {len(topics)} topics")

report_path = ROOT / "docs" / f"harvest_report_{today_str}.md"
report_path.parent.mkdir(parents=True, exist_ok=True)
report_md = f"# Daily ArXiv Harvest v2 — {today_str}\n\n- Topics: {len(topics)}\n- Queries: {summary['total_queries']}\n- Raw: {summary['total_papers_raw']}\n- Deduped: {summary['total_papers_deduped']}\n\n## Per-Topic\n"
for t in summary["topics"]:
    report_md += f"- {t['id']}: {t['count']} papers\n"
report_md += "\n## Sample\n"
for pid, paper in list(all_papers.items())[:10]:
    report_md += f"- [{pid}] {paper['title']} — {paper['arxiv_url']}\n"
report_path.write_text(report_md)
