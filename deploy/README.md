# Hosting jarvisd

How to run the Jarvis daemon (`docs/JARVISD_SPEC.md`) somewhere other agents can reach it.
Plan reference: `docs/JARVIS_HARNESS_PLAN.md` §5 Phase 2. Three paths, in order of
preference:

| Path | Cost | Always on? | GPU / Ollama | State |
|---|---|---|---|---|
| **A. Home box + Cloudflare Tunnel** | free | while the box is on | yes (host Ollama) | SQLite in a docker volume, nightly backup |
| **B. Hugging Face Space (Docker)** | free (CPU basic) | sleeps after ~48 h idle, wakes on request | no | **ephemeral** unless paid persistent storage |
| **C. Any VM with docker compose** | whatever the VM costs | yes | usually no | SQLite in a docker volume |

Files involved (all at the repo root unless noted):

- `Dockerfile.jarvisd` -- image; `Dockerfile.jarvisd.dockerignore` -- its context filter
- `docker-compose.jarvisd.yml` -- `jarvisd` service on `127.0.0.1:8790`, optional `cloudflared` behind `--profile tunnel`
- `deploy/.env.example` -- every env var, copy to `deploy/.env`
- `deploy/backup.sh` -- nightly SQLite backup (+ optional rclone to R2)
- `deploy/hf_space_export.sh` -- assembles the minimal tree to push to a Space
- `scripts/jarvisd_start.ps1` / `scripts/jarvisd_start.sh` -- start + register at logon

## 0. Common setup (all paths)

```sh
cp deploy/.env.example deploy/.env
chmod 600 deploy/.env                                        # Windows: it's in your profile, fine
python -c "import secrets; print('jv_' + secrets.token_urlsafe(32))"   # -> JARVIS_BEARER
```

Edit `deploy/.env`: set `JARVIS_BEARER`, set `JARVIS_PUBLIC_HOST` to the hostname you will
use, optionally `ANTHROPIC_API_KEY` for the `jarvis.ask` brain. Leave everything else.

Every compose command below carries `--env-file deploy/.env`. That flag feeds the `${VAR}`
substitutions in the compose file; the service-level `env_file:` only feeds the container.
Without it you get: `set JARVIS_BEARER in deploy/.env and run compose with --env-file deploy/.env`.

## A. Home box + Cloudflare Tunnel (recommended)

The daemon binds only `127.0.0.1:8790` on the box. `cloudflared` runs as a sidecar in the
same compose network and forwards `https://jarvis.<zone>` to `http://jarvisd:8790`.
No inbound port is opened on the router. Ollama on the box is visible to the container
as `http://host.docker.internal:11434`.

1. **Create the tunnel** (one time, in the browser): Cloudflare dashboard -> Zero Trust ->
   Networks -> Tunnels -> *Create a tunnel* -> Cloudflared -> name it `jarvis`.
   On the *Install connector* step copy the token from the `cloudflared ... --token <TOKEN>`
   line (do not install anything on the host; compose runs it). Next step, *Public
   Hostname*: subdomain `jarvis`, domain `<zone>`, type `HTTP`, URL `jarvisd:8790`.
   Save. Cloudflare creates the DNS record for you.
2. Put the token in `deploy/.env`: `CLOUDFLARE_TUNNEL_TOKEN=eyJ...` and set
   `JARVIS_PUBLIC_HOST=jarvis.<zone>`.
3. Bring it up:

   ```sh
   docker compose --env-file deploy/.env -f docker-compose.jarvisd.yml --profile tunnel up -d --build
   docker compose --env-file deploy/.env -f docker-compose.jarvisd.yml ps       # jarvisd healthy, cloudflared running
   docker compose --env-file deploy/.env -f docker-compose.jarvisd.yml logs -f cloudflared   # "Registered tunnel connection"
   ```

   Or use the wrappers, which also wait for Docker Desktop and poll `/api/health`:

   ```powershell
   .\scripts\jarvisd_start.ps1            # Windows: up -d with the tunnel profile
   .\scripts\jarvisd_start.ps1 -Install   # + Task Scheduler task "Jarvisd daemon" at logon
   ```
   ```sh
   ./scripts/jarvisd_start.sh             # Linux/macOS
   ./scripts/jarvisd_start.sh --install   # + systemd --user unit (Linux) / LaunchAgent (macOS)
   ```

4. **Verify** (from any machine, a phone is the honest test):

   ```sh
   curl -s https://jarvis.<zone>/api/health
   # {"ok": true, "version": "...", "uptime_s": ..., "db": "/data/jarvis.db", "brain": ...}

   curl -s -o /dev/null -w '%{http_code}\n' https://jarvis.<zone>/api/claims      # 401: auth is on
   curl -s -H "Authorization: Bearer $JARVIS_BEARER" https://jarvis.<zone>/api/claims   # 200
   ```

   Ephemeral single-use token (spec §2) minted by the daemon itself:

   ```sh
   TOKEN=$(docker compose --env-file deploy/.env -f docker-compose.jarvisd.yml exec -T jarvisd python -m jarvisd token)
   curl -s -H "Authorization: Bearer $TOKEN" https://jarvis.<zone>/api/claims   # 200 once
   curl -s -H "Authorization: Bearer $TOKEN" https://jarvis.<zone>/api/claims   # 401: reused
   ```

5. **Connect Claude Code** (acceptance §8.1):

   ```sh
   claude mcp add --transport http jarvis https://jarvis.<zone>/mcp --header "Authorization: Bearer $JARVIS_BEARER"
   claude mcp list          # jarvis: connected, tools jarvis.context / jarvis.remember / ...
   ```

   Cursor / OpenCode: same URL + header in their MCP config (the other workers own those
   client configs).

Free-tier caveats, stated plainly: the tunnel itself is free with no bandwidth cap that
matters here, but the daemon is only up while the box is on and awake -- a closed laptop
lid is an outage. Windows sleep/hibernate stops Docker Desktop; disable sleep on the
box or accept the gaps. Path B is the "lid closed" fallback, not a replacement.

## B. Hugging Face Space (Docker SDK) -- fallback

Free CPU-basic Spaces run a Dockerfile, expose one port over HTTPS, and **sleep after
about 48 hours without requests**; the first request after that waits for a cold start
(tens of seconds). The MCP mount is stateless (spec §1), so a client that hits a sleeping
Space just retries -- no session to strand. What you do NOT get for free: persistent disk.
`/data/jarvis.db` lives in the container filesystem and is reset on every restart,
rebuild, or wake. For real state either buy the Space *persistent storage* add-on (it is
mounted at `/data`, exactly where the daemon writes) or treat the Space as a scratch
daemon and keep the home box as the source of truth.

1. Create the Space: huggingface.co -> New Space -> SDK **Docker** -> blank template,
   visibility private if you like (MCP clients still reach it with the bearer).
2. Build the push tree. A Space wants `Dockerfile` at its root, so the export script
   copies the workspace and renames `Dockerfile.jarvisd` -> `Dockerfile` and
   `Dockerfile.jarvisd.dockerignore` -> `.dockerignore`:

   ```sh
   ./deploy/hf_space_export.sh /tmp/jarvisd-space
   cd /tmp/jarvisd-space
   git init && git remote add origin https://huggingface.co/spaces/<owner>/jarvisd
   git add -A && git commit -m "jarvisd" && git push -u origin main
   ```

   The export writes a `README.md` with the required front matter:

   ```yaml
   ---
   title: jarvisd
   sdk: docker
   app_port: 8790
   ---
   ```

   `app_port: 8790` means the plain image (default target, port 8790) is enough. If you
   prefer the conventional 7860, drop `app_port` and add a Space **Variable** `PORT=7860`
   instead -- the image reads `$PORT` at start (that is what the `spaces` build target sets).
3. Space -> Settings -> *Variables and secrets*: secrets `JARVIS_BEARER` and (optional)
   `ANTHROPIC_API_KEY`; variable `JARVIS_PUBLIC_HOST=<owner>-jarvisd.hf.space`.
   Without `JARVIS_BEARER` the daemon refuses to start (non-loopback bind, spec §2) -- the
   Space logs will say so.
4. Verify, same as path A with the Space URL:

   ```sh
   curl -s https://<owner>-jarvisd.hf.space/api/health
   claude mcp add --transport http jarvis https://<owner>-jarvisd.hf.space/mcp --header "Authorization: Bearer $JARVIS_BEARER"
   ```

Ollama and the RTX trainer are not reachable from a Space; `harness.run` falls back to
whatever scout does without them.

## C. Any VM with docker compose

Same compose file. The daemon still binds `127.0.0.1:8790` on the VM; put a TLS
terminator in front of it (Caddy is two lines) or just run the tunnel profile there too --
the token is not tied to the home box.

```sh
git clone <this repo> && cd dottie
cp deploy/.env.example deploy/.env && $EDITOR deploy/.env
docker compose --env-file deploy/.env -f docker-compose.jarvisd.yml up -d --build
curl -s http://127.0.0.1:8790/api/health
./scripts/jarvisd_start.sh --install --no-tunnel     # systemd --user unit, survives reboots with linger
```

Caddyfile alternative to the tunnel (`jarvis.<zone>` must resolve to the VM):

```
jarvis.<zone> {
    reverse_proxy 127.0.0.1:8790
}
```

## Backups

The DB is one SQLite file in the `jarvisd-data` volume, WAL mode. Copy it with the
online backup API, never with `cp` while the daemon is running. The image ships the
`sqlite3` CLI, so this works verbatim:

```sh
docker compose --env-file deploy/.env -f docker-compose.jarvisd.yml exec -T jarvisd \
  sqlite3 /data/jarvis.db ".backup /data/backup/jarvis-$(date +%F).db"
```

`deploy/backup.sh` does that, prunes backups older than 14 days, and optionally pushes
the file to Cloudflare R2 with rclone (you already use R2; free tier is 10 GB):

```sh
rclone config create r2 s3 provider=Cloudflare access_key_id=... secret_access_key=... endpoint=https://<account>.r2.cloudflarestorage.com
RCLONE_REMOTE=r2:jarvis-backups ./deploy/backup.sh
```

Nightly at 03:15:

```sh
# Linux/macOS
( crontab -l 2>/dev/null; echo "15 3 * * * cd $PWD && RCLONE_REMOTE=r2:jarvis-backups ./deploy/backup.sh >> deploy/backup.log 2>&1" ) | crontab -
```
```powershell
# Windows (Task Scheduler, runs the same compose exec line)
$act = New-ScheduledTaskAction -Execute "docker" -Argument "compose --env-file deploy/.env -f docker-compose.jarvisd.yml exec -T jarvisd sh -c `"sqlite3 /data/jarvis.db '.backup /data/backup/jarvis-`$(date +%F).db'`"" -WorkingDirectory (Get-Location)
Register-ScheduledTask -TaskName "Jarvisd backup" -Action $act -Trigger (New-ScheduledTaskTrigger -Daily -At 03:15)
```

Restore: stop the daemon, copy a backup over `/data/jarvis.db` inside the volume, start:

```sh
docker compose --env-file deploy/.env -f docker-compose.jarvisd.yml stop jarvisd
docker compose --env-file deploy/.env -f docker-compose.jarvisd.yml run --rm --no-deps jarvisd \
  sh -c 'cp /data/backup/jarvis-2026-09-05.db /data/jarvis.db && rm -f /data/jarvis.db-wal /data/jarvis.db-shm'
docker compose --env-file deploy/.env -f docker-compose.jarvisd.yml start jarvisd
```

## Operations cheat sheet

```sh
C="docker compose --env-file deploy/.env -f docker-compose.jarvisd.yml"
$C ps                                   # health column
$C logs -f jarvisd                      # uvicorn + audit lines
$C exec -T jarvisd python -m jarvisd token          # mint an ephemeral token
$C exec -T jarvisd tail -n 20 /data/audit.jsonl    # who called what (key last4 only)
$C up -d --build                        # after pulling new code
$C --profile tunnel down                # stop everything, keep the volume
docker volume rm jarvisd_jarvisd-data   # ...and throw the state away (after a backup)
```

Rotating the bearer: change `JARVIS_BEARER` in `deploy/.env`, `$C up -d` (recreates the
container), re-run `claude mcp add` with the new header. Old ephemeral tokens die with
the old key.
