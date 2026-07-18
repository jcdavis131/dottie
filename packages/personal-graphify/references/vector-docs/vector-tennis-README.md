# Vector Tennis

Strictly noncommercial tennis player-season style modeling and two deterministic
browser games. The complete default build uses an attributed offline CC BY 4.0
fixture. Optional pinned Sackmann/Tennis Abstract acquisition is source-derived,
noncommercial, and CC BY-NC-SA 4.0; ATP/WTA websites are never scraped.

## Local workflow

```powershell
cd C:\Users\jcdav\vector-tennis
python -m unittest discover -s tests -v
python pipeline/verify_release.py --fixture
python -m http.server 4173
```

Python uses only the standard library, NumPy, and CPU-only PyTorch already
installed. Do not install dependencies or select a CUDA device. Tests are
offline. Remote acquisition is an explicit, resumable command only.

See `docs/SPEC.md`, `docs/DATA_SOURCES.md`, `LICENSE-DATA.md`, and the live
execution board at `tasks/todo.md`.
