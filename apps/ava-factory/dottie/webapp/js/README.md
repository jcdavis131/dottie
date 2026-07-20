# webapp contract tests

Run them like this, from `apps/ava-factory`:

```bash
node --test dottie/webapp/js/api.contract.test.mjs dottie/webapp/js/store.contract.test.mjs
```

Or by glob, which survives new test files being added:

```bash
node --test "dottie/webapp/js/*.contract.test.mjs"
```

Expected: **11 passing** (6 in `api.contract.test.mjs`, 5 in `store.contract.test.mjs`).

## Do not pass the directory

`node --test dottie/webapp/js/` looks reasonable and is wrong on Node 24. It tries to
load the directory as a module and dies with:

```
Error: Cannot find module '...\dottie\webapp\js'
✖ failing tests:  test at dottie\webapp\js:1:1
```

That output says `failing tests` and names a test path, so it reads as **the suite failing**
when in fact the suite never ran. Measured 2026-07-20: this was misread as a webapp
regression during a cross-app check, and the tests were green the whole time. Pass files or
a quoted glob, never the bare directory.

There is no `package.json` here on purpose — the webapp ships as plain ES modules with no
build step and no dependencies, so there is nothing for npm to install. These tests import
the modules directly and stub `localStorage`/`fetch` themselves.
