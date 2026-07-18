#!/bin/bash
set -e
# Quickstart v0.3 — One CLI to rule all tools, security first
echo "=== BigBang CLI v0.3.0 Sovereign ==="
bb --help
bb system doctor
bb secrets list
bb tools list || echo "no tools yet"
bb tools add demo-api --type openapi --url https://petstore.swagger.io/v2/swagger.json --tags demo,api
bb tools list
bb tools search demo
bb --json tools list | python3 -m json.tool | head -n 30
bb system policy | head -n 50
bb mcp manifest | python3 -m json.tool | head -n 50
bb system audit --n 5
bb agent run "check Vector Hoops and list tools"
