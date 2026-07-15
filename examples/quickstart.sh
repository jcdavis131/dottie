#!/bin/bash
# Quickstart for BigBang CLI — agents/tools/services only, no finance
bb --help
bb doctor
bb vector list
bb family brain
bb ava status
bb agent bus
bb mcp manifest
bb --json vector list | python3 -m json.tool
