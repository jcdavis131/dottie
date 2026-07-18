#!/bin/bash
# bb write pre-commit hook installer + batch example
# Solo personal project, no connection to employer, built with public/free-tier only

echo "Installing bb write pre-commit guard..."
bb write hook --install

echo "Scanning docs/"
bb --json write batch docs/ --glob "*.md" | python3 -m json.tool | tail -n 20

echo "Example: fix all md if HUMAN_LIKE after deterministic pass"
# bb --json write batch . --fix

echo "Manual file check:"
echo "In today's digital landscape, it's important to note..." | bb --json write check --file /dev/stdin | python3 -m json.tool | tail -n 10

echo "Generate authentic pitch (no slop, real sources):"
bb --json write generate "Turnover Shield cold email for plumbing owner Austin — specific, no buzzwords, one story" --no-ollama | python3 -m json.tool | tail -n 20
