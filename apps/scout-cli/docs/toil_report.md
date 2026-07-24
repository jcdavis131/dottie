# Toil Report — Scout Plugin Automation
Date: 2026-07-24T00:32:04.432700+00:00 UTC
Repo: /home/hatch/workspace/dottie/apps/scout-cli
Mode: Home Scout — Single CLI Doctrine

## History Sources
- ~/.zsh_history — found 45313 bytes
- ~/.bash_history — found 24238 bytes
- Audit log — found

## Stats
- Total commands: 2810
- Unique: 75

## Top Singles
- scout system doctor — 248x
- scout todos list — 204x
- git status — 180x
- pytest -q — 180x
- git add -A — 180x
- git commit -m 'feat(scout): todos plugin' — 180x
- git push — 180x
- scout todos — 138x
- scout secrets get — 132x
- scout tools rm — 110x
- scout secrets rm — 106x
- scout secrets set — 98x
- scout auth set-token — 88x
- scout ava status — 68x
- scout tools get — 46x

## Top N-Grams
- scout todos list -> scout system doctor : 182x
- git status -> pytest -q : 180x
- pytest -q -> git add -A : 180x
- git add -A -> git commit -m 'feat(scout): todos plugin' : 180x
- git commit -m 'feat(scout): todos plugin' -> git push : 180x
- git push -> scout todos list : 180x
- git status -> pytest -q -> git add -A : 180x
- pytest -q -> git add -A -> git commit -m 'feat(scout): todos plugin' : 180x
- git add -A -> git commit -m 'feat(scout): todos plugin' -> git push : 180x
- git commit -m 'feat(scout): todos plugin' -> git push -> scout todos list : 180x

## Selected Toil Candidate
- Sequence: git status -> pytest -q -> git add -A -> git commit -m 'feat(scout): todos plugin' -> git push
- Total: 180
- Per week: 41.9 (threshold >5/week: ✅)
- Steps: 5 (threshold >3: ✅)
- Savings: ~419 min/week (7.0 hrs)
- Proposed plugin: dev_loop (git status -> pytest -q -> git add -A -> git commit -m -> git push)

## Safety
- All commands redacted for secrets (sk-, ghp_, AKIA, Bearer, tokens)
- No PII included
