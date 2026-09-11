# Local Dottie image verification

Build from the monorepo root:

```sh
docker build -f Dockerfile.jarvisd -t dottie/jarvisd:fleet-local .
uv run --frozen python deploy/smoke_image.py
```

The smoke test creates a disposable container with a random test bearer, a
loopback-only ephemeral port, a read-only root filesystem, dropped capabilities,
and private temporary state. It checks health, rejection without authentication,
pairing, replay rejection, durable goals after restart, and dottie-loop imports.
It stops the container on completion; Docker removes its anonymous test volume.
No production state or credentials are used. Set `DOTTIE_TEST_IMAGE` to test a
different image tag.

The canonical image includes Scout, jarvisd, dottie-loop, and Git. The workspace
member manifests must all be copied before the first frozen dependency sync;
the Docker context allowlist must include their sources as well.

Local inference is selected through the existing `JARVIS_BRAIN=ollama`,
`OLLAMA_HOST`, and `OLLAMA_MODEL` configuration. This image check intentionally
sets the brain off: success proves deployment plumbing, not model quality or
autonomous coding performance. A model-backed workflow benchmark remains a
separate acceptance gate.

Windows can run the daemon tests directly. The loop security suite creates
symbolic links; run it in Linux when the Windows account lacks that privilege.
Do not weaken the symlink escape test to accommodate the host.
