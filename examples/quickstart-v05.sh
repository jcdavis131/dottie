#!/bin/bash
set -e
# BigBang v0.5 — Ava co-dev daily driver
echo "=== BigBang CLI v0.5 — Ava + Write + Lab ==="

bb system doctor
bb --json write scan -t "In today's digital landscape, it's important to note that our cutting-edge solution harnesses the power of AI — crafting a rich tapestry" | python3 -m json.tool | head -n 20

echo "--- write check BEFORE 100 AFTER 0 ---"
bb --json write check -t "In today's digital landscape, it's important to note that our cutting-edge solution harnesses the power of AI — crafting a rich tapestry of innovation, leveraging holistic synergy." | python3 -m json.tool | tail -n 15

echo "--- lab ---"
bb --json lab ideas | python3 -m json.tool | head -n 20
bb --json lab shield | python3 -m json.tool | head -n 20
bb --json lab mrr --trials 2 --note "hill-climb v0.5 test"

echo "--- brain ---"
bb --json brain goals | python3 -m json.tool | head -n 20
bb --json brain sync

echo "--- ava routing (now write/lab/brain) ---"
bb --json ava route "check my draft for ai slop"
bb --json ava route "show mrr for turnover shield"
bb --json ava route "my goals"

echo "--- agent planning ---"
bb --json agent run "generate authentic email for Turnover Shield plumbing owner"
bb --json agent run "check slop in docs and report MRR"

echo "--- MCP manifest (bb_write, bb_lab, bb_brain now) ---"
bb --json mcp manifest | python3 -m json.tool | head -n 60

echo "✅ BigBang v0.5 ready — tool you use for everything + tool you give to Ava"
