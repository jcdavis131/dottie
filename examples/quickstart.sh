#!/bin/bash
# Quickstart for BigBang CLI
bb --help
bb doctor
bb finance snapshot --net
bb vector list
bb family brain
bb ava status
bb --json finance snapshot | jq .
