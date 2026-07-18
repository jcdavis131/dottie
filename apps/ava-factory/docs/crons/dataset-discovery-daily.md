---
id: dataset-discovery-daily
enabled: true
mode: task
schedule:
  kind: daily
  timezone: UTC
  time: "14:00:00"
metadata:
  created_by: dataset_discovery
  note: HOME only, solo project
---
# Dataset Discovery — Daily 14:00 UTC (Based on Eval Weaknesses)
# Solo personal project, no connection to employer, built with public/free-tier only

Purpose: Discover additional datasets to fill gaps identified by evals (currently only one data source synthetic Phi B). Reads frontier_eval_results.json, branch_eval_results.json, latest-log.html to find weak domains (e.g., finance weak -> need financial datasets).

Steps:
1. cd ~/workspace/ava-agi-factory-v6-4
2. Run discovery:
   python scripts/dataset_discovery.py --dry-run --eval-file branch_eval_results.json --out your_files/ava-agi/dataset_discovery/
   - Parses eval results: if cap_score <0.9 or test pass=False, marks domain weak
   - Maps weak domains to HF dataset queries via DOMAIN_TO_DATASET_QUERIES
     - finance -> financial_phrasebank, convfinqa, finqa, fiqa, bizbench
     - bio -> pubmed_qa, medmcqa, medqa, chemprot
     - code -> the_stack, code_search_net, humaneval, mbpp
     - math -> metamath-qa, gsm8k, proof_pile, open-web-math
     - safety -> anthropic/hh-rlhf, beaver_tails
   - Searches HF Hub public API https://huggingface.co/api/datasets/ (free, no key) for license (MIT/Apache2/CC0/CC-BY ok)
   - Does NOT auto-download massive data in Hatch VM (limited disk), but prepares download manifests
3. Outputs:
   - your_files/ava-agi/dataset_discovery/candidates_{date}.json: name, source (hf/github/arxiv), license, tokens estimate, relevance score, url, download method, license_ok, downloads, likes
   - data/discovery/needs.json: what domains need more tokens based on eval failures, e.g., {"finance": {"current_score":0.45, "tokens_needed":"500M-2B", "top_candidates":[...]}}
   - your_files/ava-agi/dataset_discovery/download_candidates_{date}.sh: bash script with curl/wget/python -m datasets commands for Alienware RTX 4090 to run (not in VM)
4. Log to your_files/ava-agi/runs/discovery-{date}.log
5. If finance/bio weakest (<0.6), trigger alert file your_files/ava-agi/alerts/data-need-{date}.json

Downstream (Alienware, NOT Hatch VM):
  bash your_files/ava-agi/dataset_discovery/download_candidates_*.sh
  # Then ingest:
  python scripts/ingest_hf.py --dataset financial_phrasebank --out data/raw/finance/ --filter reward>0.8
  ./scripts/local_train.sh python streaming_data.py --use_raw data/raw/finance/ --pack

Compliance:
- HOME only, free public APIs, no keys, license check (avoid CC-BY-NC)
- No work Drive upload
- Disclaimer: Solo personal project

Example weak mapping:
- If branch_eval safety_blackmail fails -> need safety data
- If frontier finance <0.6 -> need convfinqa + finance-alpaca 500M tokens
- If code weak -> need the_stack 1B tokens
