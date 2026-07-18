"""HTTP utils with NO_PROXY sanitization for Hatch egress proxy compatibility"""
import os

def _clean_no_proxy_value(s: str) -> str:
    parts = s.split(",")
    clean=[]
    for p in parts:
        p=p.strip()
        if not p:
            continue
        if "[" in p or "]" in p:
            continue
        if "::" in p:
            continue
        # skip any entry with multiple colons (IPv6 leftover)
        # keep simple: if contains ':' and not a single port like host:port but IPv6 has >1 colon
        # but we already skipped ::, so check if fd** or contains ':'
        # For safety, allow host:port single colon? We'll keep only if IPv4 or hostname without ':'
        # Actually no_proxy entries usually don't include :port, except maybe host:port - but not needed
        # We'll keep entries that have at most one ':' and that ':' is not part of IPv6 (we already filtered ::)
        # Simplify: if ':' in p and p.count(':')>1: skip
        if p.count(":")>1:
            continue
        # also skip fd8b etc which now have no :: after cleaning? but they contain : so skip if contains : and not IPv4?
        # Keep IPv4 and hostnames and CIDR with / but no ':'
        if ":" in p:
            # allow IPv4:port like 127.0.0.1:8080 (single colon, dots present)
            if "." not in p:
                continue
        clean.append(p)
    return ",".join(clean)

def sanitize_no_proxy_env():
    """Fix broken NO_PROXY env that contains IPv6 bracket notation breaking httpx URLPattern"""
    for key in ("NO_PROXY", "no_proxy"):
        val = os.environ.get(key)
        if not val:
            continue
        cleaned = _clean_no_proxy_value(val)
        # only update if different
        if cleaned != val:
            os.environ[key] = cleaned

# Auto-sanitize on import
sanitize_no_proxy_env()

# Solo personal project, no connection to employer, built with public/free-tier only
