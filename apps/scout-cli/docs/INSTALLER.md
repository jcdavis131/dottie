# Installing scout

scout is Dottie's CLI (`apps/scout-cli`, Python package `bigbang`, command
`scout`). Install it with [`uv`](https://docs.astral.sh/uv/).

## From a Dottie checkout (recommended)

```sh
git clone https://github.com/jcdavis131/dottie
cd dottie
uv sync --all-groups            # scout + its workspace deps (dottie-loop = the router)
uv run scout --help
uv run scout system doctor
uv run scout --json route "compare Stripe vs Lemon Squeezy"
```

`uv sync` installs the workspace members that `pyproject.toml` lists. scout
depends on `packages/dottie-loop` through a workspace source, so plain
`pip install -e apps/scout-cli` cannot resolve it. Use uv.

## As a tool on your PATH

```sh
uv tool install "git+https://github.com/jcdavis131/dottie#subdirectory=apps/scout-cli"
scout --help
```

## The curl one-liner (what it actually does)

```sh
curl -fsSL https://raw.githubusercontent.com/jcdavis131/dottie/main/apps/scout-cli/install.sh | sh
```

`install.sh` is a bash-only scaffold. It installs **no** Python package and
makes no network calls of its own. In the target directory (default `.`) it
writes:

- `bundles/zero_deps.json`: `{"zero_deps":true,"allow":"acne:./src"}`
- `bundles/manifest.json`: a static description of the bundle layout
- `bundles/.installed`: a marker line with the installer version
- `bundles/cli.sh` (mode 770), only if one is not already there. It copies
  `~/workspace/bundles/cli.sh` when that file exists. Otherwise it writes a
  wrapper that execs `bundles/dev-api/scout_cli_shim_v3.py`, which the
  installer does not create.

The latency and performance figures the script prints are hardcoded strings,
not measurements. To get a working `scout`, use one of the uv paths above.
The repo-root `install.sh` calls this script and then runs
`uv sync --all-groups --frozen` if `uv` is on your PATH.

## Verify

```sh
uv run scout --json system doctor
uv run scout --json harness run "heartbeat monitor tick"   # routes, plans, executes locally
uv run scout --json router status                          # traces, stamps, current authority
```
