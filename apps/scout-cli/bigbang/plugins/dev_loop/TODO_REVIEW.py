# TODO: review toil PR https://github.com/jcdavis131/dottie/pull/6 — dev_loop automation (41.9/week, 5 steps, saves ~419 min/week)
# This file ensures {
  "ok": true,
  "command": "todos",
  "data": {
    "root": "/home/hatch/workspace/bigbang-cli",
    "scan_root": "/home/hatch/workspace/bigbang-cli",
    "path_filter": null,
    "type_filter": null,
    "substring_filter": null,
    "scanned_files": 833,
    "skipped_files": 2,
    "total_markers": 500,
    "todos": [
      {
        "file": "bigbang/plugins/ava/cli.py",
        "abs_path": "/home/hatch/workspace/bigbang-cli/bigbang/plugins/ava/cli.py",
        "line": 503,
        "type": "TODO",
        "marker": "todo",
        "context": "if \"task\" in q or \"todo\" in q or \"lina\" in q or \"morning\" in q or \"afternoon\" in q:",
        "plugin": "ava"
      },
      {
        "file": "bigbang/plugins/ava/cli.py",
        "abs_path": "/home/hatch/workspace/bigbang-cli/bigbang/plugins/ava/cli.py",
        "line": 514,
        "type": "TODO",
        "marker": "todo",
        "context": "\"reason\": \"task mentions tasks/todo/Lina lists — Google Tasks wired\",",
        "plugin": "ava"
      },
      {
        "file": "bigbang/plugins/ava/cli.py",
        "abs_path": "/home/hatch/workspace/bigbang-cli/bigbang/plugins/ava/cli.py",
        "line": 1255,
        "type": "BUG",
        "marker": "bug",
        "context": "# Write error log for debug",
        "plugin": "ava"
      },
      {
        "file": "bigbang/plugins/agent/cli.py",
        "abs_path": "/home/hatch/workspace/bigbang-cli/bigbang/plugins/agent/cli.py",
        "line": 247,
        "type": "TODO",
        "marker": "todo",
        "context": "\"todo\": \"scout tasks list\",",
        "plugin": "agent"
      },
      {
        "file": "bigbang/plugins/tasks/cli.py",
        "abs_path": "/home/hatch/workspace/bigbang-cli/bigbang/plugins/tasks/cli.py",
        "line": 459,
        "type": "TODO",
        "marker": "todo",
        "context": "\"\"\"Sync recent audit events into tasks — everyday 'what did I do -> todo'. Alias for sync-scout (scout-native).\"\"\"",
        "plugin": "tasks"
      },
      {
        "file": "bigbang/plugins/recipes/cli.py",
        "abs_path": "/home/hatch/workspace/bigbang-cli/bigbang/plugins/recipes/cli.py",
        "line": 66,
        "type": "TODO",
        "marker": "TODO",
        "context": "{\"label\": \"memory TODO\", \"cmd\": [\"brain\", \"memory\", \"--query\", \"TODO\", \"--n\", \"20\"], \"desc\": \"Open TODOs in memory\"},",
        "plugin": "recipes"
      },
      {
        "file": "bigbang/plugins/todos/cli.py",
        "abs_path": "/home/hatch/workspace/bigbang-cli/bigbang/plugins/todos/cli.py",
        "line": 2,
        "type": "TODO",
        "marker": "TODO",
        "context": "todos plugin — summarize TODO/FIXME/HACK markers across scout-cli and dottie monorepo.",
        "plugin": "todos"
      },
      {
        "file": "bigbang/plugins/todos/cli.py",
        "abs_path": "/home/hatch/workspace/bigbang-cli/bigbang/plugins/todos/cli.py",
        "line": 28,
        "type": "TODO",
        "marker": "TODO",
        "context": "\"📝 TODOs — summarize TODO/FIXME/HACK markers across the repo\",",
        "plugin": "todos"
      },
      {
        "file": "bigbang/plugins/todos/cli.py",
        "abs_path": "/home/hatch/workspace/bigbang-cli/bigbang/plugins/todos/cli.py",
        "line": 45,
        "type": "TODO",
        "marker": "TODO",
        "context": "r\"(?P<marker>TODO|FIXME|HACK|XXX|BUG)\\b[:\\s-]*?(?P<rest>.*)?\",",
        "plugin": "todos"
      },
      {
        "file": "bigbang/plugins/todos/cli.py",
        "abs_path": "/home/hatch/workspace/bigbang-cli/bigbang/plugins/todos/cli.py",
        "line": 294,
        "type": "TODO",
        "marker": "TODO",
        "context": "# but we also want to catch TODO in many file types, so try to read",
        "plugin": "todos"
      },
      {
        "file": "bigbang/plugins/todos/cli.py",
        "abs_path": "/home/hatch/workspace/bigbang-cli/bigbang/plugins/todos/cli.py",
        "line": 302,
        "type": "TODO",
        "marker": "TODO",
        "context": "if \"TODO\" not in text and \"FIXME\" not in text and \"HACK\" not in text and \"XXX\" not in text and \"BUG\" not in text:",
        "plugin": "todos"
      },
      {
        "file": "bigbang/plugins/todos/cli.py",
        "abs_path": "/home/hatch/workspace/bigbang-cli/bigbang/plugins/todos/cli.py",
        "line": 305,
        "type": "TODO",
        "marker": "todo",
        "context": "if \"todo\" not in low and \"fixme\" not in low and \"hack\" not in low:",
        "plugin": "todos"
      },
      {
        "file": "bigbang/plugins/todos/cli.py",
        "abs_path": "/home/hatch/workspace/bigbang-cli/bigbang/plugins/todos/cli.py",
        "line": 446,
        "type": "TODO",
        "marker": "TODO",
        "context": "help=\"Filter marker type (comma-separated): TODO,FIXME,HACK\",",
        "plugin": "todos"
      },
      {
        "file": "bigbang/plugins/todos/cli.py",
        "abs_path": "/home/hatch/workspace/bigbang-cli/bigbang/plugins/todos/cli.py",
        "line": 461,
        "type": "TODO",
        "marker": "TODO",
        "context": "\"\"\"Summarize TODO/FIXME/HACK markers.",
        "plugin": "todos"
      },
      {
        "file": "bigbang/plugins/todos/cli.py",
        "abs_path": "/home/hatch/workspace/bigbang-cli/bigbang/plugins/todos/cli.py",
        "line": 511,
        "type": "TODO",
        "marker": "TODO",
        "context": "discover=\"scout todos --path bigbang/plugins --type TODO\",",
        "plugin": "todos"
      },
      {
        "file": "bigbang/plugins/todos/cli.py",
        "abs_path": "/home/hatch/workspace/bigbang-cli/bigbang/plugins/todos/cli.py",
        "line": 524,
        "type": "FIXME",
        "marker": "FIXME",
        "context": "\"scout --json todos list --type FIXME\",",
        "plugin": "todos"
      },
      {
        "file": "bigbang/plugins/todos/cli.py",
        "abs_path": "/home/hatch/workspace/bigbang-cli/bigbang/plugins/todos/cli.py",
        "line": 540,
        "type": "TODO",
        "marker": "TODO",
        "context": "help=\"Filter marker type: TODO,FIXME,HACK (comma-separated)\",",
        "plugin": "todos"
      },
      {
        "file": "bigbang/plugins/todos/cli.py",
        "abs_path": "/home/hatch/workspace/bigbang-cli/bigbang/plugins/todos/cli.py",
        "line": 555,
        "type": "TODO",
        "marker": "TODO",
        "context": "\"\"\"List TODO/FIXME/HACK markers with grouping.\"\"\"",
        "plugin": "todos"
      },
      {
        "file": "bigbang/plugins/todos/manifest.yaml",
        "abs_path": "/home/hatch/workspace/bigbang-cli/bigbang/plugins/todos/manifest.yaml",
        "line": 3,
        "type": "TODO",
        "marker": "TODO",
        "context": "description: Summarize TODO/FIXME/HACK markers across scout-cli and dottie monorepo with grouping by plugin/type",
        "plugin": "todos"
      },
      {
        "file": "docs/llm-wiki/tasks-plugin.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/tasks-plugin.md",
        "line": 42,
        "type": "BUG",
        "marker": "bug",
        "context": "- `http_utils.sanitize_no_proxy_env()` called on import to avoid `[::1]` bug breaking underlying `httpx` if future versions switch from subprocess to direct API.",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/tasks-plugin.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/tasks-plugin.md",
        "line": 46,
        "type": "TODO",
        "marker": "todo",
        "context": "- `ava/cli.py _heuristic_route`: if `task` or `todo` or `lina` in query → `picked_tool=tasks`, `picked_command=scout tasks list` confidence 0.92",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/tasks-plugin.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/tasks-plugin.md",
        "line": 47,
        "type": "TODO",
        "marker": "todo",
        "context": "- `agent/cli.py builtin_hints`: `task→scout tasks list`, `todo→scout tasks list`, `lina→scout tasks lists`",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/tasks-plugin.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/tasks-plugin.md",
        "line": 83,
        "type": "BUG",
        "marker": "bug",
        "context": "- NO_PROXY `[::1]` bug: `sanitize_no_proxy_env()` strips brackets, prevents `httpx Invalid port ':1]'` in Hatch.",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/architecture.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/architecture.md",
        "line": 12,
        "type": "BUG",
        "marker": "bug",
        "context": "-> tasks/cli.py sanitize_no_proxy_env() (fixes Hatch [::1] bug)",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/architecture.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/architecture.md",
        "line": 27,
        "type": "TODO",
        "marker": "todo",
        "context": "-> _heuristic_route() sees \"task\"/\"todo\"/\"lina\" -> picked_tool tasks, command scout tasks list confidence 0.92",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/ecosystem-audit-2026-07-17.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/ecosystem-audit-2026-07-17.md",
        "line": 6,
        "type": "TODO",
        "marker": "TODO",
        "context": "> TODO markers, placeholder bodies, fabricated \"real\" measurements, and dangling doc",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/ecosystem-audit-2026-07-17.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/ecosystem-audit-2026-07-17.md",
        "line": 92,
        "type": "TODO",
        "marker": "TODO",
        "context": "Ecosystem-wide grep sweep (TODO/FIXME/NotImplemented/placeholder/hardcoded-literal",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/index.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/index.md",
        "line": 31,
        "type": "TODO",
        "marker": "todo",
        "context": "--scout ava route \"todo\"--> {tool: tasks, command: scout tasks list, confidence 0.92}",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/security-model.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/security-model.md",
        "line": 35,
        "type": "BUG",
        "marker": "bug",
        "context": "- `tools add` → domain extraction `urlparse(netloc)` not full URL → prevents `petstore.swagger.io/v2/swagger.json` vs `petstore.swagger.io` mismatch (bug fixed in v0.4)",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/security-model.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/security-model.md",
        "line": 44,
        "type": "TODO",
        "marker": "todo",
        "context": "- `hatch_gws_cli tasks status` returns `{\"ok\":true,\"status\":\"connected\",\"connect_url\":...,\"disconnect_url\":...}` — the audit pipeline now recursively redacts secret-bearing keys (value/token/secret/password/credential/auth/key) and secret-shaped substrings (Bearer tokens, sk-/ghp_/JWT patterns) before anything reaches audit.jsonl (`bigbang/core/output.py:_redact_for_audit`), so token-carrying conn",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AACG.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AACG.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ABEV.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ABEV.md",
        "line": 68,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ACB.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ACB.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ACP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ACP.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ACV.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ACV.md",
        "line": 68,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ADMA.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ADMA.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ADNT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ADNT.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ADP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ADP.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ADPT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ADPT.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ADSK.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ADSK.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ADT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ADT.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ADTN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ADTN.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ADTX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ADTX.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ADUS.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ADUS.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ADV.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ADV.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ADX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ADX.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ADXN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ADXN.md",
        "line": 68,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AEE.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AEE.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AEFC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AEFC.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AEG.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AEG.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AEHL.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AEHL.md",
        "line": 69,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AEIS.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AEIS.md",
        "line": 68,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AEM.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AEM.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AEMD.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AEMD.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AEO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AEO.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AEP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AEP.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AES.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AES.md",
        "line": 68,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AEYE.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AEYE.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AFB.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AFB.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AFBI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AFBI.md",
        "line": 68,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AFG.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AFG.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AFGB.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AFGB.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AFGC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AFGC.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AFGD.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AFGD.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AFGE.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AFGE.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AFL.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AFL.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AFRM.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AFRM.md",
        "line": 58,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AFYA.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AFYA.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AG.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AG.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AGCO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AGCO.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AGD.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AGD.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AGEN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AGEN.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AGI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AGI.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AGIO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AGIO.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AGM.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AGM.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AGM.A.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AGM.A.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AGMH.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AGMH.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AGNC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AGNC.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AGNCM.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AGNCM.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AGNCN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AGNCN.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AGNCO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AGNCO.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AGNCP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AGNCP.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AGRO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AGRO.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AGYS.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AGYS.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AHCO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AHCO.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AHT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AHT.md",
        "line": 69,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AI.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AIG.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AIG.md",
        "line": 58,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AIHS.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AIHS.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AIN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AIN.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AIO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AIO.md",
        "line": 69,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AIRG.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AIRG.md",
        "line": 69,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AIRT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AIRT.md",
        "line": 69,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AIRTP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AIRTP.md",
        "line": 69,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AIT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AIT.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AIV.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AIV.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AIZ.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AIZ.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AIZN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AIZN.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AJG.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AJG.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AKAM.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AKAM.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AKBA.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AKBA.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AKO.A.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AKO.A.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AKO.B.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AKO.B.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AKTS.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AKTS.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AKTX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AKTX.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALB.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALB.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALC.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALCO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALCO.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALDX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALDX.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALEC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALEC.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALG.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALG.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALGM.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALGM.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALGN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALGN.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALGS.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALGS.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALGT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALGT.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALK.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALK.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALKS.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALKS.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALL.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALL.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALLE.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALLE.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALLO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALLO.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALLT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALLT.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALLY.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALLY.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALNY.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALNY.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALOT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALOT.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALRM.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALRM.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALRS.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALRS.md",
        "line": 58,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALSN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALSN.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALT.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALTG.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALTG.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALV.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALV.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALX.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ALXO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ALXO.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AM.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AM.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMAL.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMAL.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMAT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMAT.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMBA.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMBA.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMC.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMCI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMCI.md",
        "line": 69,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMCR.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMCR.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMCX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMCX.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMD.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMD.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AME.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AME.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMG.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMG.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMGN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMGN.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMH.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMH.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMN.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMP.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMPH.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMPH.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMPY.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMPY.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMRC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMRC.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMRN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMRN.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMRX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMRX.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMSC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMSC.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMSF.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMSF.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMST.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMST.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMT.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMTB.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMTB.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMTX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMTX.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMWL.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMWL.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMX.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AMZN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AMZN.md",
        "line": 68,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AN.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ANAB.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ANAB.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ANDE.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ANDE.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ANET.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ANET.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ANF.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ANF.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ANGI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ANGI.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ANGO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ANGO.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ANIK.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ANIK.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ANIP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ANIP.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ANIX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ANIX.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ANNX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ANNX.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ANY.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ANY.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AOD.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AOD.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AON.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AON.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AOS.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AOS.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AOSL.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AOSL.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AOUT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AOUT.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AP.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_APA.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_APA.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_APAM.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_APAM.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_APD.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_APD.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_APEI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_APEI.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_APG.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_APG.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_APH.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_APH.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_API.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_API.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_APLE.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_APLE.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_APM.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_APM.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_APO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_APO.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_APOG.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_APOG.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_APP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_APP.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_APPF.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_APPF.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_APPN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_APPN.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_APPS.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_APPS.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_APRE.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_APRE.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_APTV.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_APTV.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_APVO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_APVO.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_APWC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_APWC.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_APXT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_APXT.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_APYX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_APYX.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AQB.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AQB.md",
        "line": 69,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AQMS.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AQMS.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AQN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AQN.md",
        "line": 68,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AQNB.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AQNB.md",
        "line": 68,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AQST.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AQST.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARAY.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARAY.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARCB.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARCB.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARCC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARCC.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARCO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARCO.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARCT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARCT.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARDC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARDC.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARDX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARDX.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARE.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARE.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AREC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AREC.md",
        "line": 69,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARES.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARES.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARGX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARGX.md",
        "line": 69,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARI.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARKO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARKO.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARL.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARL.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARLO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARLO.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARLP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARLP.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARMK.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARMK.md",
        "line": 58,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AROC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AROC.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AROW.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AROW.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARQT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARQT.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARRY.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARRY.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARTL.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARTL.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARTNA.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARTNA.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARTW.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARTW.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARVN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARVN.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ARW.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ARW.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ASA.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ASA.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ASAN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ASAN.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ASB.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ASB.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ASC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ASC.md",
        "line": 55,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ASG.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ASG.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ASGI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ASGI.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ASH.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ASH.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ASIX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ASIX.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ASLE.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ASLE.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ASMB.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ASMB.md",
        "line": 58,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ASML.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ASML.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ASND.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ASND.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ASO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ASO.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ASPN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ASPN.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ASPS.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ASPS.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ASRV.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ASRV.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ASTC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ASTC.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ASTE.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ASTE.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ASX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ASX.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ASYS.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ASYS.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ATAC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ATAC.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ATCX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ATCX.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ATEC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ATEC.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ATEN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ATEN.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ATEX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ATEX.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ATHE.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ATHE.md",
        "line": 68,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ATHM.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ATHM.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ATI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ATI.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ATLC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ATLC.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ATLO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ATLO.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ATNI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ATNI.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ATO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ATO.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ATOM.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ATOM.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ATOS.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ATOS.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ATRA.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ATRA.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ATRC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ATRC.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ATRO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ATRO.md",
        "line": 58,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_ATXI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_ATXI.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AUB.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AUB.md",
        "line": 58,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AUBN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AUBN.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AUDC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AUDC.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AUPH.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AUPH.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AUTL.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AUTL.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AUUD.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AUUD.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AVA.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AVA.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AVAL.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AVAL.md",
        "line": 69,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AVAV.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AVAV.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AVB.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AVB.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AVD.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AVD.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AVGO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AVGO.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AVK.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AVK.md",
        "line": 69,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AVNS.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AVNS.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AVNT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AVNT.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AVNW.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AVNW.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AVO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AVO.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AVT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AVT.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AVXL.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AVXL.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AVY.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AVY.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AWF.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AWF.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AWI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AWI.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AWK.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AWK.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AWP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AWP.md",
        "line": 68,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AWRE.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AWRE.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AX.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AXGN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AXGN.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AXON.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AXON.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AXP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AXP.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AXS.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AXS.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AXSM.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AXSM.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AXTA.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AXTA.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AXTI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AXTI.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AYI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AYI.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AZN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AZN.md",
        "line": 68,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AZO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AZO.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AZUL.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AZUL.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_AZZ.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_AZZ.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_B.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_B.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BA.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BA.md",
        "line": 58,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BABA.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BABA.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BAC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BAC.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BAH.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BAH.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BAK.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BAK.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BALL.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BALL.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BALY.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BALY.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BAM.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BAM.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BANC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BANC.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BAND.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BAND.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BANF.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BANF.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BANFP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BANFP.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BANX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BANX.md",
        "line": 68,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BAP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BAP.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BATRA.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BATRA.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BATRK.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BATRK.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BAX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BAX.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BB.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BB.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BBBY.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BBBY.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BBCP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BBCP.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BBD.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BBD.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BBDC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BBDC.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BBDO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BBDO.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BBGI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BBGI.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BBIO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BBIO.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BBN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BBN.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BBSI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BBSI.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BBVA.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BBVA.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BBW.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BBW.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BBY.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BBY.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BC.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BCAB.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BCAB.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BCAT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BCAT.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BCBP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BCBP.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BCC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BCC.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BCDA.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BCDA.md",
        "line": 58,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BCE.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BCE.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BCH.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BCH.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BCLI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BCLI.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BCML.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BCML.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BCO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BCO.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BCPC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BCPC.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BCRX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BCRX.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BCS.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BCS.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BCSF.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BCSF.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BCX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BCX.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BCYC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BCYC.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BDC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BDC.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BDJ.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BDJ.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BDN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BDN.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BDSX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BDSX.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BDTX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BDTX.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BDX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BDX.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BE.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BE.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BEAM.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BEAM.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BEAT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BEAT.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BEEM.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BEEM.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BEKE.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BEKE.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BELFA.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BELFA.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BELFB.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BELFB.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BEN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BEN.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BEP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BEP.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BEPC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BEPC.md",
        "line": 69,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BF-B.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BF-B.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BF.A.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BF.A.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BF.B.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BF.B.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BFAM.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BFAM.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BFC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BFC.md",
        "line": 68,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BFS.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BFS.md",
        "line": 58,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BFST.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BFST.md",
        "line": 58,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BG.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BG.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BGB.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BGB.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BGH.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BGH.md",
        "line": 69,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BGS.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BGS.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BGSF.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BGSF.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BGT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BGT.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BGX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BGX.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BGY.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BGY.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BH.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BH.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BH.A.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BH.A.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BHC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BHC.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BHE.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BHE.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BHF.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BHF.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BHFAL.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BHFAL.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BHFAN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BHFAN.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BHFAO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BHFAO.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BHFAP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BHFAP.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BHK.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BHK.md",
        "line": 68,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BHP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BHP.md",
        "line": 68,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BHV.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BHV.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BHVN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BHVN.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BIIB.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BIIB.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BILI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BILI.md",
        "line": 69,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BILL.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BILL.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BIO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BIO.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BIO.B.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BIO.B.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BIP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BIP.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BIPC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BIPC.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BIT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BIT.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BIVI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BIVI.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BJ.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BJ.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BJRI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BJRI.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BKD.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BKD.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BKE.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BKE.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BKH.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BKH.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BKNG.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BKNG.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BKR.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BKR.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BKSC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BKSC.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BKT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BKT.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BKYI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BKYI.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BL.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BL.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BLBD.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BLBD.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BLDP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BLDP.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BLDR.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BLDR.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BLFS.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BLFS.md",
        "line": 58,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BLIN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BLIN.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BLK.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BLK.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BLKB.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BLKB.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BLMN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BLMN.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BLNK.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BLNK.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BLRX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BLRX.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BLW.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BLW.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BLX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BLX.md",
        "line": 69,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BMA.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BMA.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BME.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BME.md",
        "line": 68,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BMEZ.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BMEZ.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BMI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BMI.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BMO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BMO.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BMRA.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BMRA.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BMRC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BMRC.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BMRN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BMRN.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BMY.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BMY.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BNED.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BNED.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BNGO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BNGO.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BNL.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BNL.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BNS.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BNS.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BNTC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BNTC.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BNTX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BNTX.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BNY.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BNY.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BOE.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BOE.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BOH.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BOH.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BOKF.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BOKF.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BOOM.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BOOM.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BOOT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BOOT.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BOSC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BOSC.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BOTJ.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BOTJ.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BOX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BOX.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BOXL.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BOXL.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BP.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BPOP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BPOP.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BPOPM.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BPOPM.md",
        "line": 59,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BPRN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BPRN.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BPTH.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BPTH.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BPYPN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BPYPN.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BPYPO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BPYPO.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BPYPP.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BPYPP.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BQ.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BQ.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BR.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BR.md",
        "line": 58,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BRC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BRC.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BREZ.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BREZ.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BRID.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BRID.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BRK-B.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BRK-B.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BRK.A.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BRK.A.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BRK.B.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BRK.B.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BRO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BRO.md",
        "line": 63,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BRT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BRT.md",
        "line": 69,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BRX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BRX.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BSAC.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BSAC.md",
        "line": 70,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BSBK.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BSBK.md",
        "line": 68,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BSCL.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BSCL.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BSET.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BSET.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BSL.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BSL.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BSM.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BSM.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BST.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BST.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BSTZ.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BSTZ.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BSVN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BSVN.md",
        "line": 67,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BSX.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BSX.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BSY.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BSY.md",
        "line": 58,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BTAI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BTAI.md",
        "line": 62,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BTBT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BTBT.md",
        "line": 68,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BTI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BTI.md",
        "line": 69,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BTO.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BTO.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BTT.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BTT.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BTZ.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BTZ.md",
        "line": 60,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BUD.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BUD.md",
        "line": 69,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BUI.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BUI.md",
        "line": 69,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BURL.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BURL.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BUSE.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BUSE.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BV.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BV.md",
        "line": 61,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BVN.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BVN.md",
        "line": 65,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BW.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BW.md",
        "line": 66,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      },
      {
        "file": "docs/llm-wiki/companies/company_BWA.md",
        "abs_path": "/home/hatch/workspace/bigbang-cli/docs/llm-wiki/companies/company_BWA.md",
        "line": 64,
        "type": "XXX",
        "marker": "XXX",
        "context": "No V2 chunks yet — run pipeline/ingest_sec_v2.py --ticker XXX --filing-types 10-K",
        "plugin": "core"
      }
    ],
    "by_type": {
      "XXX": 470,
      "TODO": 24,
      "BUG": 5,
      "FIXME": 1
    },
    "by_plugin": {
      "core": 481,
      "todos": 13,
      "ava": 3,
      "agent": 1,
      "recipes": 1,
      "tasks": 1
    },
    "by_file": {
      "bigbang/plugins/todos/cli.py": 12,
      "docs/llm-wiki/tasks-plugin.md": 4,
      "bigbang/plugins/ava/cli.py": 3,
      "docs/llm-wiki/architecture.md": 2,
      "docs/llm-wiki/ecosystem-audit-2026-07-17.md": 2,
      "docs/llm-wiki/security-model.md": 2,
      "bigbang/plugins/agent/cli.py": 1,
      "bigbang/plugins/recipes/cli.py": 1,
      "bigbang/plugins/tasks/cli.py": 1,
      "bigbang/plugins/todos/manifest.yaml": 1,
      "docs/llm-wiki/companies/company_AACG.md": 1,
      "docs/llm-wiki/companies/company_ABEV.md": 1,
      "docs/llm-wiki/companies/company_ACB.md": 1,
      "docs/llm-wiki/companies/company_ACP.md": 1,
      "docs/llm-wiki/companies/company_ACV.md": 1,
      "docs/llm-wiki/companies/company_ADMA.md": 1,
      "docs/llm-wiki/companies/company_ADNT.md": 1,
      "docs/llm-wiki/companies/company_ADP.md": 1,
      "docs/llm-wiki/companies/company_ADPT.md": 1,
      "docs/llm-wiki/companies/company_ADSK.md": 1,
      "docs/llm-wiki/companies/company_ADT.md": 1,
      "docs/llm-wiki/companies/company_ADTN.md": 1,
      "docs/llm-wiki/companies/company_ADTX.md": 1,
      "docs/llm-wiki/companies/company_ADUS.md": 1,
      "docs/llm-wiki/companies/company_ADV.md": 1,
      "docs/llm-wiki/companies/company_ADX.md": 1,
      "docs/llm-wiki/companies/company_ADXN.md": 1,
      "docs/llm-wiki/companies/company_AEE.md": 1,
      "docs/llm-wiki/companies/company_AEFC.md": 1,
      "docs/llm-wiki/companies/company_AEG.md": 1,
      "docs/llm-wiki/companies/company_AEHL.md": 1,
      "docs/llm-wiki/companies/company_AEIS.md": 1,
      "docs/llm-wiki/companies/company_AEM.md": 1,
      "docs/llm-wiki/companies/company_AEMD.md": 1,
      "docs/llm-wiki/companies/company_AEO.md": 1,
      "docs/llm-wiki/companies/company_AEP.md": 1,
      "docs/llm-wiki/companies/company_AES.md": 1,
      "docs/llm-wiki/companies/company_AEYE.md": 1,
      "docs/llm-wiki/companies/company_AFB.md": 1,
      "docs/llm-wiki/companies/company_AFBI.md": 1,
      "docs/llm-wiki/companies/company_AFG.md": 1,
      "docs/llm-wiki/companies/company_AFGB.md": 1,
      "docs/llm-wiki/companies/company_AFGC.md": 1,
      "docs/llm-wiki/companies/company_AFGD.md": 1,
      "docs/llm-wiki/companies/company_AFGE.md": 1,
      "docs/llm-wiki/companies/company_AFL.md": 1,
      "docs/llm-wiki/companies/company_AFRM.md": 1,
      "docs/llm-wiki/companies/company_AFYA.md": 1,
      "docs/llm-wiki/companies/company_AG.md": 1,
      "docs/llm-wiki/companies/company_AGCO.md": 1,
      "docs/llm-wiki/companies/company_AGD.md": 1,
      "docs/llm-wiki/companies/company_AGEN.md": 1,
      "docs/llm-wiki/companies/company_AGI.md": 1,
      "docs/llm-wiki/companies/company_AGIO.md": 1,
      "docs/llm-wiki/companies/company_AGM.A.md": 1,
      "docs/llm-wiki/companies/company_AGM.md": 1,
      "docs/llm-wiki/companies/company_AGMH.md": 1,
      "docs/llm-wiki/companies/company_AGNC.md": 1,
      "docs/llm-wiki/companies/company_AGNCM.md": 1,
      "docs/llm-wiki/companies/company_AGNCN.md": 1,
      "docs/llm-wiki/companies/company_AGNCO.md": 1,
      "docs/llm-wiki/companies/company_AGNCP.md": 1,
      "docs/llm-wiki/companies/company_AGRO.md": 1,
      "docs/llm-wiki/companies/company_AGYS.md": 1,
      "docs/llm-wiki/companies/company_AHCO.md": 1,
      "docs/llm-wiki/companies/company_AHT.md": 1,
      "docs/llm-wiki/companies/company_AI.md": 1,
      "docs/llm-wiki/companies/company_AIG.md": 1,
      "docs/llm-wiki/companies/company_AIHS.md": 1,
      "docs/llm-wiki/companies/company_AIN.md": 1,
      "docs/llm-wiki/companies/company_AIO.md": 1,
      "docs/llm-wiki/companies/company_AIRG.md": 1,
      "docs/llm-wiki/companies/company_AIRT.md": 1,
      "docs/llm-wiki/companies/company_AIRTP.md": 1,
      "docs/llm-wiki/companies/company_AIT.md": 1,
      "docs/llm-wiki/companies/company_AIV.md": 1,
      "docs/llm-wiki/companies/company_AIZ.md": 1,
      "docs/llm-wiki/companies/company_AIZN.md": 1,
      "docs/llm-wiki/companies/company_AJG.md": 1,
      "docs/llm-wiki/companies/company_AKAM.md": 1,
      "docs/llm-wiki/companies/company_AKBA.md": 1,
      "docs/llm-wiki/companies/company_AKO.A.md": 1,
      "docs/llm-wiki/companies/company_AKO.B.md": 1,
      "docs/llm-wiki/companies/company_AKTS.md": 1,
      "docs/llm-wiki/companies/company_AKTX.md": 1,
      "docs/llm-wiki/companies/company_ALB.md": 1,
      "docs/llm-wiki/companies/company_ALC.md": 1,
      "docs/llm-wiki/companies/company_ALCO.md": 1,
      "docs/llm-wiki/companies/company_ALDX.md": 1,
      "docs/llm-wiki/companies/company_ALEC.md": 1,
      "docs/llm-wiki/companies/company_ALG.md": 1,
      "docs/llm-wiki/companies/company_ALGM.md": 1,
      "docs/llm-wiki/companies/company_ALGN.md": 1,
      "docs/llm-wiki/companies/company_ALGS.md": 1,
      "docs/llm-wiki/companies/company_ALGT.md": 1,
      "docs/llm-wiki/companies/company_ALK.md": 1,
      "docs/llm-wiki/companies/company_ALKS.md": 1,
      "docs/llm-wiki/companies/company_ALL.md": 1,
      "docs/llm-wiki/companies/company_ALLE.md": 1,
      "docs/llm-wiki/companies/company_ALLO.md": 1,
      "docs/llm-wiki/companies/company_ALLT.md": 1,
      "docs/llm-wiki/companies/company_ALLY.md": 1,
      "docs/llm-wiki/companies/company_ALNY.md": 1,
      "docs/llm-wiki/companies/company_ALOT.md": 1,
      "docs/llm-wiki/companies/company_ALRM.md": 1,
      "docs/llm-wiki/companies/company_ALRS.md": 1,
      "docs/llm-wiki/companies/company_ALSN.md": 1,
      "docs/llm-wiki/companies/company_ALT.md": 1,
      "docs/llm-wiki/companies/company_ALTG.md": 1,
      "docs/llm-wiki/companies/company_ALV.md": 1,
      "docs/llm-wiki/companies/company_ALX.md": 1,
      "docs/llm-wiki/companies/company_ALXO.md": 1,
      "docs/llm-wiki/companies/company_AM.md": 1,
      "docs/llm-wiki/companies/company_AMAL.md": 1,
      "docs/llm-wiki/companies/company_AMAT.md": 1,
      "docs/llm-wiki/companies/company_AMBA.md": 1,
      "docs/llm-wiki/companies/company_AMC.md": 1,
      "docs/llm-wiki/companies/company_AMCI.md": 1,
      "docs/llm-wiki/companies/company_AMCR.md": 1,
      "docs/llm-wiki/companies/company_AMCX.md": 1,
      "docs/llm-wiki/companies/company_AMD.md": 1,
      "docs/llm-wiki/companies/company_AME.md": 1,
      "docs/llm-wiki/companies/company_AMG.md": 1,
      "docs/llm-wiki/companies/company_AMGN.md": 1,
      "docs/llm-wiki/companies/company_AMH.md": 1,
      "docs/llm-wiki/companies/company_AMN.md": 1,
      "docs/llm-wiki/companies/company_AMP.md": 1,
      "docs/llm-wiki/companies/company_AMPH.md": 1,
      "docs/llm-wiki/companies/company_AMPY.md": 1,
      "docs/llm-wiki/companies/company_AMRC.md": 1,
      "docs/llm-wiki/companies/company_AMRN.md": 1,
      "docs/llm-wiki/companies/company_AMRX.md": 1,
      "docs/llm-wiki/companies/company_AMSC.md": 1,
      "docs/llm-wiki/companies/company_AMSF.md": 1,
      "docs/llm-wiki/companies/company_AMST.md": 1,
      "docs/llm-wiki/companies/company_AMT.md": 1,
      "docs/llm-wiki/companies/company_AMTB.md": 1,
      "docs/llm-wiki/companies/company_AMTX.md": 1,
      "docs/llm-wiki/companies/company_AMWL.md": 1,
      "docs/llm-wiki/companies/company_AMX.md": 1,
      "docs/llm-wiki/companies/company_AMZN.md": 1,
      "docs/llm-wiki/companies/company_AN.md": 1,
      "docs/llm-wiki/companies/company_ANAB.md": 1,
      "docs/llm-wiki/companies/company_ANDE.md": 1,
      "docs/llm-wiki/companies/company_ANET.md": 1,
      "docs/llm-wiki/companies/company_ANF.md": 1,
      "docs/llm-wiki/companies/company_ANGI.md": 1,
      "docs/llm-wiki/companies/company_ANGO.md": 1,
      "docs/llm-wiki/companies/company_ANIK.md": 1,
      "docs/llm-wiki/companies/company_ANIP.md": 1,
      "docs/llm-wiki/companies/company_ANIX.md": 1,
      "docs/llm-wiki/companies/company_ANNX.md": 1,
      "docs/llm-wiki/companies/company_ANY.md": 1,
      "docs/llm-wiki/companies/company_AOD.md": 1,
      "docs/llm-wiki/companies/company_AON.md": 1,
      "docs/llm-wiki/companies/company_AOS.md": 1,
      "docs/llm-wiki/companies/company_AOSL.md": 1,
      "docs/llm-wiki/companies/company_AOUT.md": 1,
      "docs/llm-wiki/companies/company_AP.md": 1,
      "docs/llm-wiki/companies/company_APA.md": 1,
      "docs/llm-wiki/companies/company_APAM.md": 1,
      "docs/llm-wiki/companies/company_APD.md": 1,
      "docs/llm-wiki/companies/company_APEI.md": 1,
      "docs/llm-wiki/companies/company_APG.md": 1,
      "docs/llm-wiki/companies/company_APH.md": 1,
      "docs/llm-wiki/companies/company_API.md": 1,
      "docs/llm-wiki/companies/company_APLE.md": 1,
      "docs/llm-wiki/companies/company_APM.md": 1,
      "docs/llm-wiki/companies/company_APO.md": 1,
      "docs/llm-wiki/companies/company_APOG.md": 1,
      "docs/llm-wiki/companies/company_APP.md": 1,
      "docs/llm-wiki/companies/company_APPF.md": 1,
      "docs/llm-wiki/companies/company_APPN.md": 1,
      "docs/llm-wiki/companies/company_APPS.md": 1,
      "docs/llm-wiki/companies/company_APRE.md": 1,
      "docs/llm-wiki/companies/company_APTV.md": 1,
      "docs/llm-wiki/companies/company_APVO.md": 1,
      "docs/llm-wiki/companies/company_APWC.md": 1,
      "docs/llm-wiki/companies/company_APXT.md": 1,
      "docs/llm-wiki/companies/company_APYX.md": 1,
      "docs/llm-wiki/companies/company_AQB.md": 1,
      "docs/llm-wiki/companies/company_AQMS.md": 1,
      "docs/llm-wiki/companies/company_AQN.md": 1,
      "docs/llm-wiki/companies/company_AQNB.md": 1,
      "docs/llm-wiki/companies/company_AQST.md": 1,
      "docs/llm-wiki/companies/company_ARAY.md": 1,
      "docs/llm-wiki/companies/company_ARCB.md": 1,
      "docs/llm-wiki/companies/company_ARCC.md": 1,
      "docs/llm-wiki/companies/company_ARCO.md": 1,
      "docs/llm-wiki/companies/company_ARCT.md": 1,
      "docs/llm-wiki/companies/company_ARDC.md": 1,
      "docs/llm-wiki/companies/company_ARDX.md": 1,
      "docs/llm-wiki/companies/company_ARE.md": 1,
      "docs/llm-wiki/companies/company_AREC.md": 1,
      "docs/llm-wiki/companies/company_ARES.md": 1,
      "docs/llm-wiki/companies/company_ARGX.md": 1,
      "docs/llm-wiki/companies/company_ARI.md": 1,
      "docs/llm-wiki/companies/company_ARKO.md": 1,
      "docs/llm-wiki/companies/company_ARL.md": 1,
      "docs/llm-wiki/companies/company_ARLO.md": 1,
      "docs/llm-wiki/companies/company_ARLP.md": 1,
      "docs/llm-wiki/companies/company_ARMK.md": 1,
      "docs/llm-wiki/companies/company_AROC.md": 1,
      "docs/llm-wiki/companies/company_AROW.md": 1,
      "docs/llm-wiki/companies/company_ARQT.md": 1,
      "docs/llm-wiki/companies/company_ARRY.md": 1,
      "docs/llm-wiki/companies/company_ARTL.md": 1,
      "docs/llm-wiki/companies/company_ARTNA.md": 1,
      "docs/llm-wiki/companies/company_ARTW.md": 1,
      "docs/llm-wiki/companies/company_ARVN.md": 1,
      "docs/llm-wiki/companies/company_ARW.md": 1,
      "docs/llm-wiki/companies/company_ASA.md": 1,
      "docs/llm-wiki/companies/company_ASAN.md": 1,
      "docs/llm-wiki/companies/company_ASB.md": 1,
      "docs/llm-wiki/companies/company_ASC.md": 1,
      "docs/llm-wiki/companies/company_ASG.md": 1,
      "docs/llm-wiki/companies/company_ASGI.md": 1,
      "docs/llm-wiki/companies/company_ASH.md": 1,
      "docs/llm-wiki/companies/company_ASIX.md": 1,
      "docs/llm-wiki/companies/company_ASLE.md": 1,
      "docs/llm-wiki/companies/company_ASMB.md": 1,
      "docs/llm-wiki/companies/company_ASML.md": 1,
      "docs/llm-wiki/companies/company_ASND.md": 1,
      "docs/llm-wiki/companies/company_ASO.md": 1,
      "docs/llm-wiki/companies/company_ASPN.md": 1,
      "docs/llm-wiki/companies/company_ASPS.md": 1,
      "docs/llm-wiki/companies/company_ASRV.md": 1,
      "docs/llm-wiki/companies/company_ASTC.md": 1,
      "docs/llm-wiki/companies/company_ASTE.md": 1,
      "docs/llm-wiki/companies/company_ASX.md": 1,
      "docs/llm-wiki/companies/company_ASYS.md": 1,
      "docs/llm-wiki/companies/company_ATAC.md": 1,
      "docs/llm-wiki/companies/company_ATCX.md": 1,
      "docs/llm-wiki/companies/company_ATEC.md": 1,
      "docs/llm-wiki/companies/company_ATEN.md": 1,
      "docs/llm-wiki/companies/company_ATEX.md": 1,
      "docs/llm-wiki/companies/company_ATHE.md": 1,
      "docs/llm-wiki/companies/company_ATHM.md": 1,
      "docs/llm-wiki/companies/company_ATI.md": 1,
      "docs/llm-wiki/companies/company_ATLC.md": 1,
      "docs/llm-wiki/companies/company_ATLO.md": 1,
      "docs/llm-wiki/companies/company_ATNI.md": 1,
      "docs/llm-wiki/companies/company_ATO.md": 1,
      "docs/llm-wiki/companies/company_ATOM.md": 1,
      "docs/llm-wiki/companies/company_ATOS.md": 1,
      "docs/llm-wiki/companies/company_ATRA.md": 1,
      "docs/llm-wiki/companies/company_ATRC.md": 1,
      "docs/llm-wiki/companies/company_ATRO.md": 1,
      "docs/llm-wiki/companies/company_ATXI.md": 1,
      "docs/llm-wiki/companies/company_AUB.md": 1,
      "docs/llm-wiki/companies/company_AUBN.md": 1,
      "docs/llm-wiki/companies/company_AUDC.md": 1,
      "docs/llm-wiki/companies/company_AUPH.md": 1,
      "docs/llm-wiki/companies/company_AUTL.md": 1,
      "docs/llm-wiki/companies/company_AUUD.md": 1,
      "docs/llm-wiki/companies/company_AVA.md": 1,
      "docs/llm-wiki/companies/company_AVAL.md": 1,
      "docs/llm-wiki/companies/company_AVAV.md": 1,
      "docs/llm-wiki/companies/company_AVB.md": 1,
      "docs/llm-wiki/companies/company_AVD.md": 1,
      "docs/llm-wiki/companies/company_AVGO.md": 1,
      "docs/llm-wiki/companies/company_AVK.md": 1,
      "docs/llm-wiki/companies/company_AVNS.md": 1,
      "docs/llm-wiki/companies/company_AVNT.md": 1,
      "docs/llm-wiki/companies/company_AVNW.md": 1,
      "docs/llm-wiki/companies/company_AVO.md": 1,
      "docs/llm-wiki/companies/company_AVT.md": 1,
      "docs/llm-wiki/companies/company_AVXL.md": 1,
      "docs/llm-wiki/companies/company_AVY.md": 1,
      "docs/llm-wiki/companies/company_AWF.md": 1,
      "docs/llm-wiki/companies/company_AWI.md": 1,
      "docs/llm-wiki/companies/company_AWK.md": 1,
      "docs/llm-wiki/companies/company_AWP.md": 1,
      "docs/llm-wiki/companies/company_AWRE.md": 1,
      "docs/llm-wiki/companies/company_AX.md": 1,
      "docs/llm-wiki/companies/company_AXGN.md": 1,
      "docs/llm-wiki/companies/company_AXON.md": 1,
      "docs/llm-wiki/companies/company_AXP.md": 1,
      "docs/llm-wiki/companies/company_AXS.md": 1,
      "docs/llm-wiki/companies/company_AXSM.md": 1,
      "docs/llm-wiki/companies/company_AXTA.md": 1,
      "docs/llm-wiki/companies/company_AXTI.md": 1,
      "docs/llm-wiki/companies/company_AYI.md": 1,
      "docs/llm-wiki/companies/company_AZN.md": 1,
      "docs/llm-wiki/companies/company_AZO.md": 1,
      "docs/llm-wiki/companies/company_AZUL.md": 1,
      "docs/llm-wiki/companies/company_AZZ.md": 1,
      "docs/llm-wiki/companies/company_B.md": 1,
      "docs/llm-wiki/companies/company_BA.md": 1,
      "docs/llm-wiki/companies/company_BABA.md": 1,
      "docs/llm-wiki/companies/company_BAC.md": 1,
      "docs/llm-wiki/companies/company_BAH.md": 1,
      "docs/llm-wiki/companies/company_BAK.md": 1,
      "docs/llm-wiki/companies/company_BALL.md": 1,
      "docs/llm-wiki/companies/company_BALY.md": 1,
      "docs/llm-wiki/companies/company_BAM.md": 1,
      "docs/llm-wiki/companies/company_BANC.md": 1,
      "docs/llm-wiki/companies/company_BAND.md": 1,
      "docs/llm-wiki/companies/company_BANF.md": 1,
      "docs/llm-wiki/companies/company_BANFP.md": 1,
      "docs/llm-wiki/companies/company_BANX.md": 1,
      "docs/llm-wiki/companies/company_BAP.md": 1,
      "docs/llm-wiki/companies/company_BATRA.md": 1,
      "docs/llm-wiki/companies/company_BATRK.md": 1,
      "docs/llm-wiki/companies/company_BAX.md": 1,
      "docs/llm-wiki/companies/company_BB.md": 1,
      "docs/llm-wiki/companies/company_BBBY.md": 1,
      "docs/llm-wiki/companies/company_BBCP.md": 1,
      "docs/llm-wiki/companies/company_BBD.md": 1,
      "docs/llm-wiki/companies/company_BBDC.md": 1,
      "docs/llm-wiki/companies/company_BBDO.md": 1,
      "docs/llm-wiki/companies/company_BBGI.md": 1,
      "docs/llm-wiki/companies/company_BBIO.md": 1,
      "docs/llm-wiki/companies/company_BBN.md": 1,
      "docs/llm-wiki/companies/company_BBSI.md": 1,
      "docs/llm-wiki/companies/company_BBVA.md": 1,
      "docs/llm-wiki/companies/company_BBW.md": 1,
      "docs/llm-wiki/companies/company_BBY.md": 1,
      "docs/llm-wiki/companies/company_BC.md": 1,
      "docs/llm-wiki/companies/company_BCAB.md": 1,
      "docs/llm-wiki/companies/company_BCAT.md": 1,
      "docs/llm-wiki/companies/company_BCBP.md": 1,
      "docs/llm-wiki/companies/company_BCC.md": 1,
      "docs/llm-wiki/companies/company_BCDA.md": 1,
      "docs/llm-wiki/companies/company_BCE.md": 1,
      "docs/llm-wiki/companies/company_BCH.md": 1,
      "docs/llm-wiki/companies/company_BCLI.md": 1,
      "docs/llm-wiki/companies/company_BCML.md": 1,
      "docs/llm-wiki/companies/company_BCO.md": 1,
      "docs/llm-wiki/companies/company_BCPC.md": 1,
      "docs/llm-wiki/companies/company_BCRX.md": 1,
      "docs/llm-wiki/companies/company_BCS.md": 1,
      "docs/llm-wiki/companies/company_BCSF.md": 1,
      "docs/llm-wiki/companies/company_BCX.md": 1,
      "docs/llm-wiki/companies/company_BCYC.md": 1,
      "docs/llm-wiki/companies/company_BDC.md": 1,
      "docs/llm-wiki/companies/company_BDJ.md": 1,
      "docs/llm-wiki/companies/company_BDN.md": 1,
      "docs/llm-wiki/companies/company_BDSX.md": 1,
      "docs/llm-wiki/companies/company_BDTX.md": 1,
      "docs/llm-wiki/companies/company_BDX.md": 1,
      "docs/llm-wiki/companies/company_BE.md": 1,
      "docs/llm-wiki/companies/company_BEAM.md": 1,
      "docs/llm-wiki/companies/company_BEAT.md": 1,
      "docs/llm-wiki/companies/company_BEEM.md": 1,
      "docs/llm-wiki/companies/company_BEKE.md": 1,
      "docs/llm-wiki/companies/company_BELFA.md": 1,
      "docs/llm-wiki/companies/company_BELFB.md": 1,
      "docs/llm-wiki/companies/company_BEN.md": 1,
      "docs/llm-wiki/companies/company_BEP.md": 1,
      "docs/llm-wiki/companies/company_BEPC.md": 1,
      "docs/llm-wiki/companies/company_BF-B.md": 1,
      "docs/llm-wiki/companies/company_BF.A.md": 1,
      "docs/llm-wiki/companies/company_BF.B.md": 1,
      "docs/llm-wiki/companies/company_BFAM.md": 1,
      "docs/llm-wiki/companies/company_BFC.md": 1,
      "docs/llm-wiki/companies/company_BFS.md": 1,
      "docs/llm-wiki/companies/company_BFST.md": 1,
      "docs/llm-wiki/companies/company_BG.md": 1,
      "docs/llm-wiki/companies/company_BGB.md": 1,
      "docs/llm-wiki/companies/company_BGH.md": 1,
      "docs/llm-wiki/companies/company_BGS.md": 1,
      "docs/llm-wiki/companies/company_BGSF.md": 1,
      "docs/llm-wiki/companies/company_BGT.md": 1,
      "docs/llm-wiki/companies/company_BGX.md": 1,
      "docs/llm-wiki/companies/company_BGY.md": 1,
      "docs/llm-wiki/companies/company_BH.A.md": 1,
      "docs/llm-wiki/companies/company_BH.md": 1,
      "docs/llm-wiki/companies/company_BHC.md": 1,
      "docs/llm-wiki/companies/company_BHE.md": 1,
      "docs/llm-wiki/companies/company_BHF.md": 1,
      "docs/llm-wiki/companies/company_BHFAL.md": 1,
      "docs/llm-wiki/companies/company_BHFAN.md": 1,
      "docs/llm-wiki/companies/company_BHFAO.md": 1,
      "docs/llm-wiki/companies/company_BHFAP.md": 1,
      "docs/llm-wiki/companies/company_BHK.md": 1,
      "docs/llm-wiki/companies/company_BHP.md": 1,
      "docs/llm-wiki/companies/company_BHV.md": 1,
      "docs/llm-wiki/companies/company_BHVN.md": 1,
      "docs/llm-wiki/companies/company_BIIB.md": 1,
      "docs/llm-wiki/companies/company_BILI.md": 1,
      "docs/llm-wiki/companies/company_BILL.md": 1,
      "docs/llm-wiki/companies/company_BIO.B.md": 1,
      "docs/llm-wiki/companies/company_BIO.md": 1,
      "docs/llm-wiki/companies/company_BIP.md": 1,
      "docs/llm-wiki/companies/company_BIPC.md": 1,
      "docs/llm-wiki/companies/company_BIT.md": 1,
      "docs/llm-wiki/companies/company_BIVI.md": 1,
      "docs/llm-wiki/companies/company_BJ.md": 1,
      "docs/llm-wiki/companies/company_BJRI.md": 1,
      "docs/llm-wiki/companies/company_BKD.md": 1,
      "docs/llm-wiki/companies/company_BKE.md": 1,
      "docs/llm-wiki/companies/company_BKH.md": 1,
      "docs/llm-wiki/companies/company_BKNG.md": 1,
      "docs/llm-wiki/companies/company_BKR.md": 1,
      "docs/llm-wiki/companies/company_BKSC.md": 1,
      "docs/llm-wiki/companies/company_BKT.md": 1,
      "docs/llm-wiki/companies/company_BKYI.md": 1,
      "docs/llm-wiki/companies/company_BL.md": 1,
      "docs/llm-wiki/companies/company_BLBD.md": 1,
      "docs/llm-wiki/companies/company_BLDP.md": 1,
      "docs/llm-wiki/companies/company_BLDR.md": 1,
      "docs/llm-wiki/companies/company_BLFS.md": 1,
      "docs/llm-wiki/companies/company_BLIN.md": 1,
      "docs/llm-wiki/companies/company_BLK.md": 1,
      "docs/llm-wiki/companies/company_BLKB.md": 1,
      "docs/llm-wiki/companies/company_BLMN.md": 1,
      "docs/llm-wiki/companies/company_BLNK.md": 1,
      "docs/llm-wiki/companies/company_BLRX.md": 1,
      "docs/llm-wiki/companies/company_BLW.md": 1,
      "docs/llm-wiki/companies/company_BLX.md": 1,
      "docs/llm-wiki/companies/company_BMA.md": 1,
      "docs/llm-wiki/companies/company_BME.md": 1,
      "docs/llm-wiki/companies/company_BMEZ.md": 1,
      "docs/llm-wiki/companies/company_BMI.md": 1,
      "docs/llm-wiki/companies/company_BMO.md": 1,
      "docs/llm-wiki/companies/company_BMRA.md": 1,
      "docs/llm-wiki/companies/company_BMRC.md": 1,
      "docs/llm-wiki/companies/company_BMRN.md": 1,
      "docs/llm-wiki/companies/company_BMY.md": 1,
      "docs/llm-wiki/companies/company_BNED.md": 1,
      "docs/llm-wiki/companies/company_BNGO.md": 1,
      "docs/llm-wiki/companies/company_BNL.md": 1,
      "docs/llm-wiki/companies/company_BNS.md": 1,
      "docs/llm-wiki/companies/company_BNTC.md": 1,
      "docs/llm-wiki/companies/company_BNTX.md": 1,
      "docs/llm-wiki/companies/company_BNY.md": 1,
      "docs/llm-wiki/companies/company_BOE.md": 1,
      "docs/llm-wiki/companies/company_BOH.md": 1,
      "docs/llm-wiki/companies/company_BOKF.md": 1,
      "docs/llm-wiki/companies/company_BOOM.md": 1,
      "docs/llm-wiki/companies/company_BOOT.md": 1,
      "docs/llm-wiki/companies/company_BOSC.md": 1,
      "docs/llm-wiki/companies/company_BOTJ.md": 1,
      "docs/llm-wiki/companies/company_BOX.md": 1,
      "docs/llm-wiki/companies/company_BOXL.md": 1,
      "docs/llm-wiki/companies/company_BP.md": 1,
      "docs/llm-wiki/companies/company_BPOP.md": 1,
      "docs/llm-wiki/companies/company_BPOPM.md": 1,
      "docs/llm-wiki/companies/company_BPRN.md": 1,
      "docs/llm-wiki/companies/company_BPTH.md": 1,
      "docs/llm-wiki/companies/company_BPYPN.md": 1,
      "docs/llm-wiki/companies/company_BPYPO.md": 1,
      "docs/llm-wiki/companies/company_BPYPP.md": 1,
      "docs/llm-wiki/companies/company_BQ.md": 1,
      "docs/llm-wiki/companies/company_BR.md": 1,
      "docs/llm-wiki/companies/company_BRC.md": 1,
      "docs/llm-wiki/companies/company_BREZ.md": 1,
      "docs/llm-wiki/companies/company_BRID.md": 1,
      "docs/llm-wiki/companies/company_BRK-B.md": 1,
      "docs/llm-wiki/companies/company_BRK.A.md": 1,
      "docs/llm-wiki/companies/company_BRK.B.md": 1,
      "docs/llm-wiki/companies/company_BRO.md": 1,
      "docs/llm-wiki/companies/company_BRT.md": 1,
      "docs/llm-wiki/companies/company_BRX.md": 1,
      "docs/llm-wiki/companies/company_BSAC.md": 1,
      "docs/llm-wiki/companies/company_BSBK.md": 1,
      "docs/llm-wiki/companies/company_BSCL.md": 1,
      "docs/llm-wiki/companies/company_BSET.md": 1,
      "docs/llm-wiki/companies/company_BSL.md": 1,
      "docs/llm-wiki/companies/company_BSM.md": 1,
      "docs/llm-wiki/companies/company_BST.md": 1,
      "docs/llm-wiki/companies/company_BSTZ.md": 1,
      "docs/llm-wiki/companies/company_BSVN.md": 1,
      "docs/llm-wiki/companies/company_BSX.md": 1,
      "docs/llm-wiki/companies/company_BSY.md": 1,
      "docs/llm-wiki/companies/company_BTAI.md": 1,
      "docs/llm-wiki/companies/company_BTBT.md": 1,
      "docs/llm-wiki/companies/company_BTI.md": 1,
      "docs/llm-wiki/companies/company_BTO.md": 1,
      "docs/llm-wiki/companies/company_BTT.md": 1,
      "docs/llm-wiki/companies/company_BTZ.md": 1,
      "docs/llm-wiki/companies/company_BUD.md": 1,
      "docs/llm-wiki/companies/company_BUI.md": 1,
      "docs/llm-wiki/companies/company_BURL.md": 1,
      "docs/llm-wiki/companies/company_BUSE.md": 1,
      "docs/llm-wiki/companies/company_BV.md": 1,
      "docs/llm-wiki/companies/company_BVN.md": 1,
      "docs/llm-wiki/companies/company_BW.md": 1,
      "docs/llm-wiki/companies/company_BWA.md": 1,
      "docs/llm-wiki/index.md": 1
    },
    "truncated": true,
    "max_items": 500
  },
  "example": "scout --json todos --path bigbang/plugins/write",
  "discover": "scout todos --path bigbang/plugins --type TODO"
} shows the review task next morning.
# To verify: scout --json todos list --path bigbang/plugins/dev_loop
# Expected: marker contains "review toil PR https://github.com/jcdavis131/dottie/pull/6"
# Solo personal project, no connection to employer, built with public/free-tier only
