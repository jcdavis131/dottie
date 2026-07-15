"""
serve.py — MCP server wrapper (uses upstream graphify if available, else local)
Solo personal project, no connection to employer, built with public/free-tier only
"""
import subprocess
import sys
from pathlib import Path

def main():
    # try upstream graphify serve
    try:
        # delegate to graphify if installed
        result = subprocess.run(["graphify", "serve"] + sys.argv[1:], check=False)
        sys.exit(result.returncode)
    except FileNotFoundError:
        print("[personal-graphify] Upstream `graphify` CLI not found. Install with `uv tool install graphifyy` for full MCP server.")
        print("Fallback: local query mode — use `pgraphify query \"...\"`")
        sys.exit(1)

if __name__ == "__main__":
    main()
