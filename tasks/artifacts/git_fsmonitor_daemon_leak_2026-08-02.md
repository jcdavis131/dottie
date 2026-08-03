# git fsmonitor daemons leaked to 60 processes — disabled, on the memory argument only

Solo personal project, no connection to employer, built with public/free-tier only

Found while freeing memory for a Docker fleet restart that the box's own runbook was
calling NO-GO. Recorded because the leak recurs silently and because the first
measurement I took pointed the wrong way.

## What was there

    git.exe count: 60
    58 of 60 had a dead parent  ->  orphans
    oldest: 6,661 minutes (4.6 days)
    all: git fsmonitor--daemon run --detach --ipc-threads=8
    total working set: ~376 MB

`core.fsmonitor` is `true` in the **system** gitconfig
(`C:/Program Files/Git/etc/gitconfig`) — Git for Windows ships it on. It is meant to be
one long-lived daemon per repo. Sixty of them across three or four repos is not that.

The supported cleanup only reached three of them:

    git -C <repo> fsmonitor--daemon stop     ->  60 down to 57

The other 57 were orphans no repo could still address, so they were killed directly,
filtered on `fsmonitor--daemon` in the command line so no in-flight git operation was
touched. Reclaimed 44 MB of resident memory — far less than the 376 MB their working sets
suggested, because most of it was shared or already paged out.

**Accumulation is per-session, not per-invocation.** A 7-repetition benchmark across two
repos spawned only 2 daemons, so this builds up over days rather than per `git` call.
44 MB reclaimed today is the wrong number to focus on; 60-and-climbing is the problem.

## The measurement that changed my mind, and then changed it back

The reason to keep fsmonitor is `git status` latency. So it was measured rather than
assumed. First pass, best-of-3, one repo:

    fsmonitor=true    59 ms
    fsmonitor=false   33 ms

That reads as "fsmonitor is making things ~2x SLOWER", which would have made this an easy
call. It was wrong. Second pass, 7 reps, median and min, two repos:

    repo           ON median (min)    OFF median (min)
    dottie          38 (37)            57 (38)
    vector-hoops    69 (34)            73 (42)

The direction **reversed** for dottie, and the minimums are within a few ms of each other
everywhere. The honest reading is that **fsmonitor makes no measurable difference to
`git status` on these repos at this size** — both readings were noise, and the first one
was noise that happened to look like a result.

Worth stating plainly: a best-of-3 on a single repo was not enough to support a
config change, and it nearly did.

## Decision

`git config --global core.fsmonitor false`

Set at the **global** (user) level, deliberately not `--system`: the system value stays
`true`, so this is a per-user override that a Git for Windows upgrade will not fight and
that is reverted with one command.

**Justified by the leak, not by speed.** There is no measured latency benefit to give up.
The cost side is real: a daemon-per-repo mechanism that reached 60 processes over 4.6 days
on a box whose binding constraint is documented, in `.wslconfig`, as RAM — and which was
at that moment 796 MB short of its own fleet-restart threshold.

To revert:

    git config --global --unset core.fsmonitor     # falls back to the system's true

## Watch for

If `git status` becomes noticeably slow in a large working tree, this is the first thing
to re-test — with medians over 7+ reps, not a best-of-3, which is what produced the
misleading number above.
