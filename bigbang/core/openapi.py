# Solo personal project, no connection to employer, built with public/free-tier only
"""
OpenAPI codegen + real call adapter
Fetch spec, parse operations, generate Typer plugin, and perform real calls with policy enforcement.
"""
from __future__ import annotations

import json
import re
import keyword
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
import yaml

from bigbang.core.http_utils import sanitize_no_proxy_env
sanitize_no_proxy_env()

from bigbang.core.policy import enforce_or_raise
from bigbang.core.security import get_secret


def _sanitize_identifier(name: str) -> str:
    s = re.sub(r'[^0-9a-zA-Z_]+', '_', name)
    s = re.sub(r'_+', '_', s).strip('_')
    if not s:
        s = "op"
    if s[0].isdigit():
        s = "_" + s
    if keyword.iskeyword(s):
        s = s + "_"
    return s

def _sanitize_cmd_name(name: str) -> str:
    s = re.sub(r'[^0-9A-Za-z_-]+', '-', name)
    s = re.sub(r'-+', '-', s).strip('-')
    return s or "op"

def _cmd_to_func_name(cmd: str) -> str:
    s = cmd.replace('-', '_')
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s)
    s = s.lower()
    s = _sanitize_identifier(s)
    return s

def _python_type_from_param(param: Dict[str, Any]) -> str:
    schema = param.get("schema") if isinstance(param.get("schema"), dict) else {}
    t = schema.get("type") if isinstance(schema, dict) else None
    if not t:
        t = param.get("type")
    if t == "integer":
        return "int"
    if t == "number":
        return "float"
    if t == "boolean":
        return "bool"
    return "str"

def _get_domain_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        return parsed.netloc or url
    except Exception:
        return url

def _resolve_base_url(spec: Dict[str, Any], fallback_url: str) -> str:
    servers = spec.get("servers") or []
    if servers and isinstance(servers, list):
        first = servers[0] if isinstance(servers[0], dict) else {}
        base = first.get("url", "")
        if base:
            if base.startswith("/"):
                parsed = urlparse(fallback_url)
                origin = f"{parsed.scheme}://{parsed.netloc}"
                return (origin.rstrip("/") + base).rstrip("/")
            if base.startswith("http"):
                return base.rstrip("/")
            parsed = urlparse(fallback_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            return (origin.rstrip("/") + "/" + base.lstrip("/")).rstrip("/")
    if "basePath" in spec:
        parsed = urlparse(fallback_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        bp = spec.get("basePath", "")
        if bp:
            return (origin.rstrip("/") + "/" + bp.strip("/")).rstrip("/")
        return origin.rstrip("/")
    try:
        parsed = urlparse(fallback_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin and origin != "://":
            return origin.rstrip("/")
    except Exception:
        pass
    try:
        return fallback_url.rsplit("/", 1)[0]
    except Exception:
        return fallback_url

def _op_to_command_name(op: Dict[str, Any]) -> str:
    op_id = op.get("operationId")
    if op_id:
        return _sanitize_cmd_name(str(op_id))
    method = op.get("method", "get")
    path = op.get("path", "/")
    path_clean = path.strip("/")
    path_clean = path_clean.replace("{", "").replace("}", "").replace("/", "-")
    path_clean = re.sub(r'[^0-9A-Za-z_-]+', '-', path_clean)
    path_clean = path_clean.strip("-")
    if not path_clean:
        path_clean = "root"
    cmd = f"{method}-{path_clean}"
    return _sanitize_cmd_name(cmd)

def fetch_spec(url: str) -> dict:
    sanitize_no_proxy_env()
    resp = httpx.get(url, timeout=10.0, follow_redirects=True)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        try:
            return yaml.safe_load(resp.text) or {}
        except Exception:
            raise ValueError(f"Failed to parse spec from {url} as JSON")

def parse_operations(spec: dict) -> List[Dict[str, Any]]:
    ops: List[Dict[str, Any]] = []
    paths = spec.get("paths", {}) or {}
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, details in methods.items():
            ml = method.lower()
            if ml not in {"get", "post", "put", "delete", "patch", "head", "options", "trace"}:
                continue
            if not isinstance(details, dict):
                continue
            ops.append({
                "method": ml,
                "path": path,
                "operationId": details.get("operationId"),
                "summary": details.get("summary") or details.get("description", "")[:200] if details.get("description") else details.get("summary", ""),
                "parameters": details.get("parameters", []) or []
            })
    return ops

def _collect_secret_headers(tool_name: str) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    candidates = [tool_name, f"{tool_name}_api_key", f"{tool_name}_token", f"{tool_name.upper()}_API_KEY", f"{tool_name.upper()}_TOKEN"]
    token = None
    found_key = None
    for k in candidates:
        v = get_secret(k) or get_secret(k.upper()) or get_secret(k.lower())
        if v:
            token = v
            found_key = k
            break
    if token:
        low = (found_key or "").lower()
        if "api_key" in low:
            headers["X-API-Key"] = token
        else:
            headers["Authorization"] = f"Bearer {token}"
    return headers

def call_openapi(tool_manifest: Dict[str, Any], operation: str, args_dict: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(args_dict, dict):
        args_dict = {}
    spec_url = tool_manifest.get("url") or ""
    if not spec_url:
        raise ValueError("tool_manifest missing url")
    spec = fetch_spec(spec_url)
    ops = parse_operations(spec)
    # find operation
    matched = None
    for o in ops:
        if o.get("operationId") == operation or _op_to_command_name(o) == operation or _cmd_to_func_name(_op_to_command_name(o)) == operation:
            matched = o
            break
    if not matched:
        avail = [_op_to_command_name(o) for o in ops[:10]]
        raise ValueError(f"operation '{operation}' not found. Available: {avail}")
    method = matched.get("method", "get")
    path_template = matched.get("path", "/")
    parameters = matched.get("parameters", []) or []
    base_url = _resolve_base_url(spec, spec_url)
    path = path_template
    query_params: Dict[str, Any] = {}
    headers: Dict[str, str] = {}
    for param in parameters:
        if not isinstance(param, dict):
            continue
        pname = param.get("name")
        if not pname:
            continue
        pin = param.get("in")
        val = args_dict.get(pname)
        if val is None:
            for k, v in args_dict.items():
                if k.lower() == pname.lower():
                    val = v
                    break
        if val is None:
            continue
        if pin == "path":
            path = path.replace(f"{{{pname}}}", str(val))
        elif pin == "query":
            query_params[pname] = val
        elif pin == "header":
            headers[pname] = str(val)
    # remaining args as query for GET
    remaining = {k: v for k, v in args_dict.items() if k not in query_params and f"{{{k}}}" not in path_template}
    # if method GET, put remaining in query
    if method in {"get", "delete"}:
        query_params.update({k: v for k, v in remaining.items() if k not in ["body", "json"]})
        json_body = None
    else:
        json_body = remaining.get("body") or remaining.get("json") or (remaining if remaining else None)
    full_url = base_url.rstrip("/") + "/" + path.lstrip("/")
    auth_headers = _collect_secret_headers(tool_manifest.get("name") or "tool")
    final_headers = {**auth_headers, **headers}
    caps = tool_manifest.get("capabilities", {})
    policy_manifest = {"name": tool_manifest.get("name") or "openapi-tool", "capabilities": caps or {"network": {"enabled": True, "domains": [_get_domain_from_url(spec_url)]}}}
    enforce_or_raise(policy_manifest, "network", full_url)
    sanitize_no_proxy_env()
    resp = httpx.request(method.upper(), full_url, params=query_params or None, headers=final_headers or None, json=json_body if isinstance(json_body, (dict, list)) else None, timeout=10.0, follow_redirects=True)
    try:
        data = resp.json()
    except Exception:
        data = resp.text[:5000]
    return {"status_code": resp.status_code, "url": full_url, "method": method.upper(), "data": data}

def generate_typer_plugin(tool_name: str, spec: dict, url: str) -> List[str]:
    safe_tool_name = re.sub(r'[^0-9A-Za-z_-]+', '-', tool_name).strip('-') or "tool"
    tool_identifier = _sanitize_identifier(safe_tool_name)
    this_file = Path(__file__).resolve()
    plugins_base = this_file.parent.parent / "plugins"
    bases_to_try: List[Path] = [plugins_base]
    cwd_plugins = Path.cwd() / "bigbang" / "plugins"
    if cwd_plugins.exists() and cwd_plugins.resolve() != plugins_base.resolve():
        bases_to_try.append(cwd_plugins)
    alt = Path.cwd() / "bigbang-cli" / "bigbang" / "plugins"
    if alt.exists() and alt.resolve() not in [b.resolve() for b in bases_to_try]:
        bases_to_try.append(alt)
    generated_files: List[str] = []
    domain = _get_domain_from_url(url)
    info = spec.get("info", {}) or {}
    description = info.get("description") or info.get("title") or f"{safe_tool_name} API"
    description_short = (description[:200] + "...") if len(description) > 200 else description
    servers = spec.get("servers") or []
    host = spec.get("host") or ""
    basePath = spec.get("basePath") or ""
    ops = parse_operations(spec)
    used_cmd_names = set()
    used_func_names = set()
    ops_with_names: List[Dict[str, Any]] = []
    for op in ops:
        cmd_raw = _op_to_command_name(op)
        cmd = cmd_raw
        suffix = 1
        while cmd.lower() in {c.lower() for c in used_cmd_names}:
            suffix += 1
            cmd = f"{cmd_raw}-{suffix}"
        used_cmd_names.add(cmd)
        func_raw = _cmd_to_func_name(cmd)
        func_name = func_raw
        sfx = 1
        while func_name in used_func_names:
            sfx += 1
            func_name = f"{func_raw}_{sfx}"
        used_func_names.add(func_name)
        ops_with_names.append({**op, "_cmd_name": cmd, "_func_name": func_name})
    for base in bases_to_try:
        tool_dir = base / safe_tool_name
        tool_dir.mkdir(parents=True, exist_ok=True)
        init_path = tool_dir / "__init__.py"
        init_path.write_text("", encoding="utf-8")
        manifest_dict = {"name": safe_tool_name, "version": "0.4.0", "description": description_short, "capabilities": {"network": {"enabled": True, "domains": [domain]}, "filesystem": {"write": False}}}
        manifest_path = tool_dir / "manifest.yaml"
        manifest_path.write_text(yaml.safe_dump(manifest_dict, sort_keys=False), encoding="utf-8")
        cli_path = tool_dir / "cli.py"
        lines: List[str] = []
        lines.append('"""Auto-generated Typer plugin"""')
        lines.append('from __future__ import annotations')
        lines.append('import json, typer, httpx')
        lines.append('from typing import Optional')
        lines.append('from urllib.parse import urlparse')
        lines.append('from bigbang.core.output import emit')
        lines.append('from bigbang.core.policy import enforce_or_raise')
        lines.append('from bigbang.core.security import get_secret')
        lines.append('from bigbang.core.http_utils import sanitize_no_proxy_env')
        lines.append('sanitize_no_proxy_env()')
        lines.append(f'app = typer.Typer(name="{safe_tool_name}", help={repr(description_short)}, no_args_is_help=True)')
        lines.append(f'SPEC_SERVERS = {json.dumps(servers)}')
        lines.append(f'SPEC_HOST = {repr(host)}')
        lines.append(f'SPEC_BASE = {repr(basePath)}')
        lines.append(f'FALLBACK_URL = {repr(url)}')
        lines.append(f'TOOL_MANIFEST = {{"name": {repr(safe_tool_name)}, "capabilities": {{"network": {{"enabled": True, "domains": [{repr(domain)}]}}, "filesystem": {{"write": False}}}}}}')
        lines.append('def _get_base_url():')
        lines.append('    if SPEC_SERVERS and SPEC_SERVERS[0].get("url"):')
        lines.append('        b=SPEC_SERVERS[0].get("url")')
        lines.append('        if b.startswith("/"):')
        lines.append('            from urllib.parse import urlparse as _up; _p=_up(FALLBACK_URL); return f"{_p.scheme}://{_p.netloc}{b}".rstrip("/")')
        lines.append('        return b.rstrip("/")')
        lines.append('    if SPEC_BASE:')
        lines.append('        from urllib.parse import urlparse as _up; _p=_up(FALLBACK_URL)')
        lines.append('        origin = f"{_p.scheme}://{_p.netloc}"')
        lines.append('        if SPEC_HOST:')
        lines.append('            # prefer spec host if present')
        lines.append('            scheme = _p.scheme or "https"')
        lines.append('            origin = f"{scheme}://{SPEC_HOST}"')
        lines.append('        return (origin.rstrip("/") + "/" + SPEC_BASE.strip("/")).rstrip("/")')
        lines.append('    if SPEC_HOST:')
        lines.append('        from urllib.parse import urlparse as _up; _p=_up(FALLBACK_URL); scheme=_p.scheme or "https"; return f"{scheme}://{SPEC_HOST}".rstrip("/")')
        lines.append('    from urllib.parse import urlparse as _up; _p=_up(FALLBACK_URL); return f"{_p.scheme}://{_p.netloc}".rstrip("/")')
        lines.append('def _auth_headers():')
        lines.append('    return {}')
        for op in ops_with_names[:25]:  # limit to 25 ops for v0.4
            method = op["method"]
            path = op["path"]
            cmd_name = op["_cmd_name"]
            func_name = op["_func_name"]
            summary = (op.get("summary") or "")[:80].replace('"', "'")
            params = op.get("parameters") or []
            # simple signature: all query/path as optional
            sig_parts = []
            for p in params:
                if not isinstance(p, dict):
                    continue
                orig = p.get("name")
                if not orig:
                    continue
                var = _sanitize_identifier(orig)
                sig_parts.append(f'    {var}: Optional[str] = typer.Option(None, help="{p.get("in")} {orig}")')
            lines.append(f'@app.command("{cmd_name}")')
            if sig_parts:
                lines.append(f'def {func_name}(')
                for sp in sig_parts:
                    lines.append(f'{sp},')
                lines.append('):')
            else:
                lines.append(f'def {func_name}():')
            lines.append(f'    """{summary}"""')
            lines.append(f'    base=_get_base_url(); path={repr(path)}')
            # path replace
            for p in params:
                if p.get("in")=="path":
                    var = _sanitize_identifier(p.get("name"))
                    lines.append(f'    if {var}: path=path.replace("{{{p.get("name")}}}", str({var}))')
            lines.append('    params={}')
            for p in params:
                if p.get("in")=="query":
                    var = _sanitize_identifier(p.get("name"))
                    lines.append(f'    if {var} is not None: params["{p.get("name")}"]= {var}')
            lines.append(f'    url=base.rstrip("/") + "/" + path.lstrip("/")')
            lines.append('    enforce_or_raise(TOOL_MANIFEST, "network", url)')
            lines.append('    sanitize_no_proxy_env()')
            lines.append(f'    resp=httpx.request("{method.upper()}", url, params=params or None, timeout=10, follow_redirects=True)')
            lines.append('    try: data=resp.json()')
            lines.append('    except: data=resp.text[:4000]')
            lines.append(f'    emit({{"url": url, "data": data, "status": resp.status_code}}, command="{safe_tool_name} {cmd_name}")')
            lines.append('')
        lines.append('def register(root): root.add_typer(app, name=TOOL_MANIFEST["name"])')
        lines.append('# Solo personal project, no connection to employer, built with public/free-tier only')
        cli_path.write_text("\n".join(lines), encoding="utf-8")
        generated_files.extend([str(tool_dir / "manifest.yaml"), str(tool_dir / "cli.py"), str(tool_dir / "__init__.py")])
    seen=set()
    deduped=[]
    for f in generated_files:
        if f not in seen:
            deduped.append(f); seen.add(f)
    return deduped

# Solo personal project, no connection to employer, built with public/free-tier only
