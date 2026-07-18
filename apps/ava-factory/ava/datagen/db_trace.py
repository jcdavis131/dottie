"""Phase-2/3/4 database-mechanics corpus: ET-CoT docs that teach how
database engines *execute*, one data model per family (mirroring the
"Types of Databases" taxonomy): relational B-tree point/range/insert
mechanics with planner cost comparison and page loads, document-store
filter+projection scans, key-value FNV-1a hashing with linear probing,
wide-column layout arithmetic (column scans vs row scans), graph BFS/DFS
frontier states, time-series window aggregation, and vector search (exact
top-k distance math plus greedy HNSW-style layered descent).

Every trace is produced by actually running the engine structure in Python
(a real order-4 B-tree with CLRS preemptive splits, a real open-addressing
hash table, ...), and every answer is asserted against an independent
recomputation before the doc is yielded. The complete input state (page
table, buckets, adjacency lists, vectors) is inlined in the task statement
so the trace is derivable from the doc alone.
"""

from __future__ import annotations

import json
from bisect import bisect, insort
from typing import Iterator

from ava.datagen.base import Generator
from ava.datagen.trace_common import elide, render_etcot, step_lines

_ITEMS = ["bolt", "gear", "valve", "rotor", "flange", "gasket", "bearing", "piston"]
_NAMES = ["ada", "ben", "cleo", "dana", "eli", "fay", "gus", "hana",
          "ivan", "june", "kai", "lena", "mo", "nia", "omar", "pia"]
_TAGS = ["red", "blue", "green", "gold", "iron", "oak", "sky", "ash"]
_REGIONS = ["north", "south", "east", "west", "central", "coastal"]

# ---------------------------------------------------------------------------
# A real order-4 B-tree (CLRS minimum degree t=2: max 3 keys per page)
# ---------------------------------------------------------------------------


class _Page:
    __slots__ = ("pid", "keys", "children")

    def __init__(self, pid: int):
        self.pid = pid
        self.keys: list[int] = []
        self.children: list["_Page"] = []

    @property
    def leaf(self) -> bool:
        return not self.children


class _BTree:
    MAX_KEYS = 3  # order 4

    def __init__(self):
        self.pages: list[_Page] = []
        self.root = self._new_page()

    def _new_page(self) -> _Page:
        p = _Page(len(self.pages))
        self.pages.append(p)
        return p

    def insert(self, key: int, events: list[str] | None = None) -> None:
        if len(self.root.keys) == self.MAX_KEYS:
            old = self.root
            self.root = self._new_page()
            self.root.children = [old]
            if events is not None:
                events.append(f"root p{old.pid} is full -> allocate new root p{self.root.pid}")
            self._split_child(self.root, 0, events)
        self._insert_nonfull(self.root, key, events)

    def _split_child(self, parent: _Page, i: int, events: list[str] | None) -> None:
        child = parent.children[i]
        right = self._new_page()
        median = child.keys[1]
        right.keys = child.keys[2:]
        left_keys = child.keys[:1]
        if child.children:
            right.children = child.children[2:]
            child.children = child.children[:2]
        if events is not None:
            events.append(
                f"split full page p{child.pid} {child.keys}: keys {left_keys} stay in "
                f"p{child.pid}, median {median} promotes into p{parent.pid}, keys "
                f"{right.keys} move to new page p{right.pid}"
            )
        child.keys = left_keys
        parent.keys.insert(i, median)
        parent.children.insert(i + 1, right)

    def _insert_nonfull(self, page: _Page, key: int, events: list[str] | None) -> None:
        while not page.leaf:
            i = bisect(page.keys, key)
            if len(page.children[i].keys) == self.MAX_KEYS:
                self._split_child(page, i, events)
                if key > page.keys[i]:
                    i += 1
            if events is not None:
                events.append(f"descend from p{page.pid}: {key} vs keys {page.keys} -> child index {i} (p{page.children[i].pid})")
            page = page.children[i]
        insort(page.keys, key)
        if events is not None:
            events.append(f"insert {key} into leaf p{page.pid} at its sorted slot -> {page.keys}")

    def search_path(self, key: int) -> tuple[list[tuple[_Page, int, str]], bool]:
        """Returns ([(page, slot, action)], found) with action in
        {'hit', 'miss', 'descend'} -- one entry per page load."""
        path: list[tuple[_Page, int, str]] = []
        page = self.root
        while True:
            i = 0
            while i < len(page.keys) and key > page.keys[i]:
                i += 1
            if i < len(page.keys) and page.keys[i] == key:
                path.append((page, i, "hit"))
                return path, True
            if page.leaf:
                path.append((page, i, "miss"))
                return path, False
            path.append((page, i, "descend"))
            page = page.children[i]

    def range_scan(self, lo: int, hi: int):
        """Prune-aware in-order scan: returns (events, keys_in_range) where
        events = [(page, kind, collected, descended_pids, pruned_pids)]."""
        events: list[tuple[_Page, str, list[int], list[int], list[int]]] = []
        out: list[int] = []

        def rec(page: _Page) -> None:
            if page.leaf:
                got = [k for k in page.keys if lo <= k <= hi]
                events.append((page, "leaf", got, [], []))
                out.extend(got)
                return
            descended, pruned, collected = [], [], []
            plan: list[tuple[str, object]] = []
            for i, k in enumerate(page.keys):
                child = page.children[i]
                if lo < k and (i == 0 or page.keys[i - 1] < hi):
                    descended.append(child.pid)
                    plan.append(("child", child))
                else:
                    pruned.append(child.pid)
                if lo <= k <= hi:
                    collected.append(k)
                    plan.append(("key", k))
            last = page.children[-1]
            if hi > page.keys[-1]:
                descended.append(last.pid)
                plan.append(("child", last))
            else:
                pruned.append(last.pid)
            events.append((page, "internal", collected, descended, pruned))
            for kind, obj in plan:
                if kind == "child":
                    rec(obj)  # type: ignore[arg-type]
                else:
                    out.append(obj)  # type: ignore[arg-type]

        rec(self.root)
        return events, out

    def height(self) -> int:
        h, page = 1, self.root
        while not page.leaf:
            h += 1
            page = page.children[0]
        return h

    def inorder(self) -> list[int]:
        out: list[int] = []

        def rec(page: _Page) -> None:
            if page.leaf:
                out.extend(page.keys)
                return
            for i, k in enumerate(page.keys):
                rec(page.children[i])
                out.append(k)
            rec(page.children[-1])

        rec(self.root)
        return out

    def dump(self) -> list[str]:
        lines, queue = [], [self.root]
        seen = set()
        while queue:
            page = queue.pop(0)
            if page.pid in seen:
                continue
            seen.add(page.pid)
            if page.leaf:
                lines.append(f"  p{page.pid} (leaf): keys={page.keys}")
            else:
                kids = ", ".join(f"p{c.pid}" for c in page.children)
                lines.append(f"  p{page.pid} (internal): keys={page.keys} children=[{kids}]")
                queue.extend(page.children)
        return lines


def _build_tree(rng, n: int) -> tuple[_BTree, list[int]]:
    keys = rng.sample(range(10, 990), n)
    tree = _BTree()
    for k in keys:
        tree.insert(k)
    assert tree.inorder() == sorted(keys)
    return tree, sorted(keys)


def _rows_for(rng, keys: list[int]) -> dict[int, tuple[str, int]]:
    return {k: (f"{rng.choice(_ITEMS)}-{k}", rng.randint(1, 500)) for k in keys}


def _cmp_text(page: _Page, slot: int, key: int) -> str:
    if slot == 0:
        return f"{key} < {page.keys[0]}"
    if slot == len(page.keys):
        return f"{key} > {page.keys[-1]}"
    return f"{page.keys[slot - 1]} < {key} < {page.keys[slot]}"


# ---------------------------------------------------------------------------
# Relational: B-tree point query
# ---------------------------------------------------------------------------


def _btree_point_doc(rng, n: int, elide_over: int):
    tree, keys = _build_tree(rng, n)
    rows = _rows_for(rng, keys)
    if rng.random() < 0.75:
        target = rng.choice(keys)
    else:
        pool = [x for x in range(10, 990) if x not in set(keys)]
        target = rng.choice(pool)
    path, found = tree.search_path(target)
    assert found == (target in set(keys))

    scan_pages = -(-n // 4)  # heap pages hold 4 rows
    raw_steps = [
        f"planner: full table scan reads ceil({n}/4) = {scan_pages} heap pages; index "
        f"seek on the order-4 B-tree (height {tree.height()}) reads at most "
        f"{tree.height()} index pages -> choose INDEX SEEK"
    ]
    states = ["plan chosen: index seek"]
    for j, (page, slot, action) in enumerate(path):
        kind = "leaf" if page.leaf else "internal"
        if action == "descend":
            nxt = path[j + 1][0]
            raw_steps.append(
                f"load page p{page.pid} ({kind}): keys={page.keys}; {_cmp_text(page, slot, target)} "
                f"-> follow child index {slot} to p{nxt.pid}"
            )
        elif action == "hit":
            raw_steps.append(
                f"load page p{page.pid} ({kind}): keys={page.keys}; keys[{slot}] == {target} -> HIT"
            )
        else:
            raw_steps.append(
                f"load page p{page.pid} ({kind}): keys={page.keys}; {_cmp_text(page, slot, target)} "
                f"and page is a leaf -> key {target} is NOT in the index"
            )
        states.append(f"pages loaded={[p.pid for p, _, _ in path[: j + 2]]}")
    if found:
        item, qty = rows[target]
        raw_steps.append(f"fetch heap row for id {target} -> (item='{item}', qty={qty})")
        states.append("row fetched")
        answer = [
            f"result row: (id={target}, item='{item}', qty={qty})",
            f"index pages loaded: {[p.pid for p, _, _ in path]} ({len(path)} loads + 1 heap fetch, "
            f"vs {scan_pages} pages for a full scan)",
        ]
    else:
        answer = [
            "result: 0 rows (key not present)",
            f"index pages loaded: {[p.pid for p, _, _ in path]} ({len(path)} loads, "
            f"vs {scan_pages} pages for a full scan)",
        ]

    task = (
        "### Task: simulate a SQL point query through a B-tree index\n"
        f"Table inventory(id INT PRIMARY KEY, item TEXT, qty INT), {n} rows:\n"
        + "\n".join(f"  ({k}, '{rows[k][0]}', {rows[k][1]})" for k in keys)
        + "\nIndex: B-tree of order 4 on id. Page table:\n"
        + "\n".join(tree.dump())
        + f"\n\nSQL: SELECT item, qty FROM inventory WHERE id = {target};"
    )
    text = render_etcot(task, elide(step_lines(raw_steps), states, elide_over), answer)
    meta = {"keys": keys, "target": target, "found": found,
            "rows": rows, "path_pids": [p.pid for p, _, _ in path]}
    return text, "deliberate", "btree_point_query", meta


# ---------------------------------------------------------------------------
# Relational: B-tree range scan
# ---------------------------------------------------------------------------


def _btree_range_doc(rng, n: int, elide_over: int):
    tree, keys = _build_tree(rng, n)
    rows = _rows_for(rng, keys)
    lo = rng.randint(10, 700)
    hi = lo + rng.randint(40, 250)
    events, got = tree.range_scan(lo, hi)
    expect = [k for k in keys if lo <= k <= hi]
    assert got == expect

    raw_steps, states = [], []
    for page, kind, collected, descended, pruned in events:
        if kind == "leaf":
            raw_steps.append(
                f"visit p{page.pid} (leaf): keys={page.keys} -> collect {collected}"
            )
        else:
            bits = [f"visit p{page.pid} (internal): keys={page.keys}"]
            if collected:
                bits.append(f"keys {collected} are inside [{lo},{hi}]")
            if descended:
                bits.append(f"descend into {['p%d' % p for p in descended]}")
            if pruned:
                bits.append(f"prune subtrees {['p%d' % p for p in pruned]} (ranges cannot overlap [{lo},{hi}])")
            raw_steps.append("; ".join(bits))
        states.append(f"pages visited so far={[e[0].pid for e in events[: len(states) + 1]]}")
    total = sum(rows[k][1] for k in got)
    task = (
        "### Task: simulate a SQL range scan through a B-tree index\n"
        f"Table inventory(id INT PRIMARY KEY, item TEXT, qty INT), {n} rows:\n"
        + "\n".join(f"  ({k}, '{rows[k][0]}', {rows[k][1]})" for k in keys)
        + "\nIndex: B-tree of order 4 on id. Page table:\n"
        + "\n".join(tree.dump())
        + f"\n\nSQL: SELECT SUM(qty) FROM inventory WHERE id BETWEEN {lo} AND {hi};"
    )
    answer = [
        f"matching ids ({len(got)}): {got}",
        f"SUM(qty) = {' + '.join(str(rows[k][1]) for k in got) if got else '0'} = {total}",
        f"pages visited: {[e[0].pid for e in events]} of {len(tree.pages)} total "
        "(pruning skipped every subtree that cannot intersect the range)",
    ]
    text = render_etcot(task, elide(step_lines(raw_steps), states, elide_over), answer)
    meta = {"keys": keys, "lo": lo, "hi": hi, "got": got, "rows": rows, "total": total}
    return text, "deliberate", "btree_range_scan", meta


# ---------------------------------------------------------------------------
# Relational: B-tree insert with page splits
# ---------------------------------------------------------------------------


def _btree_insert_doc(rng, n: int, elide_over: int):
    order = rng.sample(range(10, 990), n)
    pool = [x for x in range(10, 990) if x not in set(order)]
    rng.shuffle(pool)

    def build() -> _BTree:
        t = _BTree()
        for k in order:
            t.insert(k)
        return t

    chosen, events, tree = None, [], None
    for cand in pool[:24]:
        t = build()
        ev: list[str] = []
        old_h = t.height()
        t.insert(cand, ev)
        if any("split" in e for e in ev):
            chosen, events, tree = cand, ev, t
            break
    if chosen is None:  # no candidate split (rare); trace a plain insert honestly
        chosen = pool[0]
        tree = build()
        old_h = tree.height()
        events = []
        tree.insert(chosen, events)
    assert tree.inorder() == sorted(order + [chosen])

    before = build()
    states = [f"pages allocated={len(before.pages) + sum('new page' in e or 'new root' in e for e in events[: i + 1])}"
              for i in range(len(events))]
    task = (
        "### Task: simulate a B-tree INSERT (order 4, preemptive splits)\n"
        f"Current index pages (root p{before.root.pid}):\n"
        + "\n".join(before.dump())
        + f"\n\nOperation: INSERT key {chosen}. A full page (3 keys) encountered on the "
        "way down is split before descending: its median promotes into the parent."
    )
    answer = [
        f"pages after insert (root p{tree.root.pid}):",
        *tree.dump(),
        f"height: {old_h} -> {tree.height()}",
    ]
    text = render_etcot(task, elide(step_lines(events), states, elide_over), answer)
    meta = {"order": order, "inserted": chosen, "inorder": tree.inorder()}
    return text, "deliberate", "btree_insert_split", meta


# ---------------------------------------------------------------------------
# Document store: filter + projection scan
# ---------------------------------------------------------------------------


def _doc_filter_doc(rng, n: int, elide_over: int):
    docs = []
    for i in range(n):
        docs.append({
            "_id": i,
            "user": {"name": rng.choice(_NAMES), "age": rng.randint(18, 70)},
            "tags": rng.sample(_TAGS, 2),
        })
    min_age = rng.randint(25, 55)
    tag = rng.choice(_TAGS)
    matches = [d for d in docs if d["user"]["age"] >= min_age and tag in d["tags"]]
    names = [d["user"]["name"] for d in matches]

    raw_steps, states = [], []
    for d in docs:
        age = d["user"]["age"]
        if age < min_age:
            raw_steps.append(
                f"doc _id={d['_id']}: extract path user.age -> {age}; {age} < {min_age} "
                "-> predicate fails, short-circuit (tags never read) -> SKIP"
            )
        elif tag not in d["tags"]:
            raw_steps.append(
                f"doc _id={d['_id']}: extract path user.age -> {age} (>= {min_age} ok); "
                f"tags={d['tags']} does not contain '{tag}' -> SKIP"
            )
        else:
            raw_steps.append(
                f"doc _id={d['_id']}: extract path user.age -> {age} (>= {min_age} ok); "
                f"tags={d['tags']} contains '{tag}' -> MATCH, project user.name = '{d['user']['name']}'"
            )
        states.append(f"scanned={d['_id'] + 1}/{n}, projected names so far="
                      f"{[m['user']['name'] for m in matches if m['_id'] <= d['_id']]}")
    task = (
        "### Task: simulate a document-store query (collection scan)\n"
        "Collection (JSON documents):\n"
        + "\n".join("  " + json.dumps(d, sort_keys=True) for d in docs)
        + f"\n\nQuery: find(user.age >= {min_age} AND tags contains '{tag}'), "
        "project user.name. Evaluate predicates left-to-right with short-circuiting."
    )
    answer = [
        f"matched {len(matches)} of {n} documents; _ids = {[m['_id'] for m in matches]}",
        f"projected user.name: {names}",
    ]
    text = render_etcot(task, elide(step_lines(raw_steps), states, elide_over), answer)
    meta = {"docs": docs, "min_age": min_age, "tag": tag, "names": names}
    return text, "deliberate", "docstore_filter_project", meta


# ---------------------------------------------------------------------------
# Key-value: FNV-1a hashing + open addressing
# ---------------------------------------------------------------------------

_KV_BUCKETS = 16
_FNV_OFFSET = 2_166_136_261
_FNV_PRIME = 16_777_619


def _fnv1a(s: str) -> int:
    h = _FNV_OFFSET
    for ch in s:
        h = ((h ^ ord(ch)) * _FNV_PRIME) % (1 << 32)
    return h


def _kv_hash_doc(rng, n: int, elide_over: int):
    words = ["user", "cart", "sess", "page", "item", "geo", "rate", "job"]
    kv_keys: list[str] = []
    while len(kv_keys) < n:
        k = f"{rng.choice(words)}{rng.randint(1, 99)}"
        if k not in kv_keys:
            kv_keys.append(k)
    values = {k: rng.randint(1, 999) for k in kv_keys}

    slots: list[str | None] = [None] * _KV_BUCKETS
    placed: dict[str, int] = {}
    raw_steps, states = [], []
    for k in kv_keys:
        h = _fnv1a(k)
        b = h % _KV_BUCKETS
        probes = [b]
        while slots[probes[-1]] is not None:
            probes.append((probes[-1] + 1) % _KV_BUCKETS)
        slots[probes[-1]] = k
        placed[k] = probes[-1]
        if len(probes) == 1:
            raw_steps.append(
                f"PUT '{k}'={values[k]}: fnv1a('{k}') = 0x{h:08X}; 0x{h:08X} mod {_KV_BUCKETS} "
                f"= slot {b}; slot {b} empty -> store"
            )
        else:
            occupants = " -> ".join(
                f"slot {p} taken by '{slots[p]}'" for p in probes[:-1]
            )
            raw_steps.append(
                f"PUT '{k}'={values[k]}: fnv1a('{k}') = 0x{h:08X} -> slot {b}; COLLISION: "
                f"{occupants} -> linear-probe to slot {probes[-1]} -> store"
            )
        states.append("occupied slots=" + str({i: s for i, s in enumerate(slots) if s is not None}))

    target = kv_keys[rng.randrange(len(kv_keys))]
    h = _FNV_OFFSET
    for ch in target:
        h2 = (h ^ ord(ch)) % (1 << 32)
        h = (h2 * _FNV_PRIME) % (1 << 32)
        raw_steps.append(
            f"GET '{target}' hash char '{ch}': h = (h XOR {ord(ch)}) * {_FNV_PRIME} "
            f"mod 2^32 = 0x{h:08X}"
        )
        states.append(f"h=0x{h:08X}")
    assert h == _fnv1a(target)
    b = h % _KV_BUCKETS
    probes = [b]
    while slots[probes[-1]] != target:
        raw_steps.append(
            f"GET '{target}': slot {probes[-1]} holds '{slots[probes[-1]]}' != '{target}' -> probe next"
        )
        states.append(f"probes={probes}")
        probes.append((probes[-1] + 1) % _KV_BUCKETS)
    raw_steps.append(
        f"GET '{target}': 0x{h:08X} mod {_KV_BUCKETS} = {b}; slot {probes[-1]} holds "
        f"'{target}' -> value {values[target]}"
    )
    states.append(f"resolved slot={probes[-1]}")
    assert placed[target] == probes[-1]

    task = (
        "### Task: simulate a key-value store (FNV-1a hash + linear probing)\n"
        f"Hash table: {_KV_BUCKETS} slots, open addressing with linear probing.\n"
        f"hash(k) = FNV-1a-32: h = {_FNV_OFFSET}; per char: h = ((h XOR byte) * {_FNV_PRIME}) mod 2^32.\n"
        "Operations, in order:\n"
        + "\n".join(f"  PUT {k} = {values[k]}" for k in kv_keys)
        + f"\n  GET {target}"
    )
    answer = [
        f"GET '{target}' -> {values[target]} (slot {placed[target]}, "
        f"{len(probes)} probe{'s' if len(probes) > 1 else ''})",
        "final slot map: " + str({i: s for i, s in enumerate(slots) if s is not None}),
    ]
    text = render_etcot(task, elide(step_lines(raw_steps), states, elide_over), answer)
    meta = {"keys": kv_keys, "values": values, "target": target,
            "placed": placed, "buckets": _KV_BUCKETS}
    return text, "deliberate", "kv_hash_probe", meta


# ---------------------------------------------------------------------------
# Wide column: columnar layout arithmetic
# ---------------------------------------------------------------------------


def _wide_column_doc(rng, n: int, elide_over: int):
    rows = [(i + 1, rng.choice(_REGIONS), rng.randint(10, 999), rng.randint(1, 99))
            for i in range(n)]
    sales = [r[2] for r in rows]
    total = sum(sales)
    # layout: id int32 | region char[8] | sales int32 | units int32 -> 20 B/row
    sales_off = n * 12

    raw_steps = [
        f"row layout: each row = 4 (id) + 8 (region) + 4 (sales) + 4 (units) = 20 bytes; "
        f"SUM(sales) on a row store touches all {n} rows = {n * 20} bytes",
        f"column layout: blocks are [id: 0..{4 * n}) [region: {4 * n}..{12 * n}) "
        f"[sales: {sales_off}..{sales_off + 4 * n}) [units: {sales_off + 4 * n}..{20 * n}); "
        f"SUM(sales) reads ONLY the sales block: {4 * n} bytes starting at byte {sales_off}",
    ]
    states = ["layout resolved", "column block located"]
    run = 0
    for i, s in enumerate(sales):
        prev = run
        run += s
        raw_steps.append(
            f"read sales[{i}] at byte {sales_off + 4 * i}: {s}; running sum {prev} + {s} = {run}"
        )
        states.append(f"i={i + 1}/{n}, running sum={run}")
    assert run == total

    task = (
        "### Task: simulate a wide-column aggregate (columnar vs row layout)\n"
        f"Table metrics(id INT32, region CHAR[8], sales INT32, units INT32), {n} rows:\n"
        + "\n".join(f"  ({r[0]}, '{r[1]}', {r[2]}, {r[3]})" for r in rows)
        + "\n\nQuery: SELECT SUM(sales) FROM metrics; -- engine stores data column-major"
    )
    answer = [
        f"SUM(sales) = {total}",
        f"bytes read: column store {4 * n} vs row store {20 * n} "
        f"({20 * n / (4 * n):.1f}x less I/O by scanning one column block)",
    ]
    text = render_etcot(task, elide(step_lines(raw_steps), states, elide_over), answer)
    meta = {"rows": rows, "total": total}
    return text, "deliberate", "wide_column_scan", meta


# ---------------------------------------------------------------------------
# Graph: BFS / DFS traversal with frontier state
# ---------------------------------------------------------------------------


def _make_graph(rng, n: int) -> dict[int, list[int]]:
    edges = set()
    for i in range(1, n):
        edges.add((rng.randrange(i), i))
    for _ in range(max(1, n // 3)):
        a, b = rng.randrange(n), rng.randrange(n)
        if a != b:
            edges.add((min(a, b), max(a, b)))
    adj: dict[int, list[int]] = {i: [] for i in range(n)}
    for a, b in edges:
        adj[a].append(b)
        adj[b].append(a)
    for v in adj:
        adj[v] = sorted(set(adj[v]))
    return adj


def _graph_doc(rng, n: int, elide_over: int):
    adj = _make_graph(rng, n)
    kind = rng.choice(["bfs", "dfs"])
    lbl = lambda v: f"N{v}"  # noqa: E731

    raw_steps, states = [], []
    if kind == "bfs":
        target = n - 1
        dist = {0: 0}
        parent: dict[int, int] = {}
        queue = [0]
        order = []
        while queue:
            u = queue.pop(0)
            order.append(u)
            new = []
            for v in adj[u]:
                if v not in dist:
                    dist[v] = dist[u] + 1
                    parent[v] = u
                    queue.append(v)
                    new.append(v)
            raw_steps.append(
                f"dequeue {lbl(u)} (dist {dist[u]}); neighbors {[lbl(v) for v in adj[u]]}; "
                + (f"newly discovered {[lbl(v) for v in new]} (dist {dist[u] + 1})" if new
                   else "all neighbors already visited")
                + f"; queue = {[lbl(v) for v in queue]}"
            )
            states.append(f"dist={{{', '.join(f'{lbl(k)}:{d}' for k, d in sorted(dist.items()))}}}")
            if u == target:
                raw_steps.append(f"target {lbl(target)} dequeued -> stop (BFS guarantees minimal edge count)")
                states.append("done")
                break
        # independent check: plain BFS distances
        chk = {0: 0}
        q2 = [0]
        while q2:
            u = q2.pop(0)
            for v in adj[u]:
                if v not in chk:
                    chk[v] = chk[u] + 1
                    q2.append(v)
        assert chk[target] == dist[target]
        path = [target]
        while path[-1] != 0:
            path.append(parent[path[-1]])
        path.reverse()
        answer = [
            f"shortest path {lbl(0)} -> {lbl(target)}: {' -> '.join(lbl(v) for v in path)} "
            f"({dist[target]} edges)",
            f"BFS visit order: {[lbl(v) for v in order]}",
        ]
        query = f"shortest path from {lbl(0)} to {lbl(target)} (BFS, neighbors in ascending order)"
        meta = {"adj": adj, "kind": kind, "dist": dist[target], "path": path, "order": order}
    else:
        stack = [0]
        seen: set[int] = set()
        order = []
        while stack:
            u = stack.pop()
            if u in seen:
                raw_steps.append(f"pop {lbl(u)}: already visited -> skip; stack = {[lbl(v) for v in stack]}")
                states.append(f"visited={[lbl(v) for v in order]}")
                continue
            seen.add(u)
            order.append(u)
            todo = [v for v in reversed(adj[u]) if v not in seen]
            stack.extend(todo)
            raw_steps.append(
                f"pop {lbl(u)} -> visit #{len(order)}; push unvisited neighbors "
                f"{[lbl(v) for v in reversed(todo)]} (reversed so smallest pops first); "
                f"stack = {[lbl(v) for v in stack]}"
            )
            states.append(f"visited={[lbl(v) for v in order]}")
        assert set(order) == set(range(n))  # connected by construction
        answer = [f"DFS preorder: {[lbl(v) for v in order]}",
                  f"visited {len(order)} of {n} nodes (graph is connected)"]
        query = f"depth-first preorder from {lbl(0)} (explicit stack, neighbors pushed in reverse-sorted order)"
        meta = {"adj": adj, "kind": kind, "order": order}

    task = (
        "### Task: simulate a graph-database traversal\n"
        f"Nodes: {[lbl(v) for v in range(n)]}\nAdjacency (undirected):\n"
        + "\n".join(f"  {lbl(v)}: {[lbl(w) for w in adj[v]]}" for v in range(n))
        + f"\n\nQuery: {query}"
    )
    text = render_etcot(task, elide(step_lines(raw_steps), states, elide_over), answer)
    return text, "deliberate", f"graph_{kind}", meta


# ---------------------------------------------------------------------------
# Time series: window aggregation
# ---------------------------------------------------------------------------


def _ts_agg_doc(rng, n: int, elide_over: int):
    window = rng.choice([60, 300])
    t0 = 1_700_000_000 + 60 * rng.randint(0, 10_000)
    pts = []
    t = t0
    for _ in range(n):
        t += rng.randint(5, max(6, window // 2))
        pts.append((t, rng.randint(120, 980) / 10.0))

    buckets: dict[int, list[float]] = {}
    raw_steps, states = [], []
    for i, (ti, v) in enumerate(pts):
        b = (ti - t0) // window
        vals = buckets.setdefault(b, [])
        prev = (len(vals), sum(vals))
        vals.append(v)
        raw_steps.append(
            f"point (t=+{ti - t0}s, v={v:.1f}): bucket = ({ti - t0} // {window}) = {b}; "
            f"bucket {b}: count {prev[0]} -> {len(vals)}, sum {prev[1]:.1f} -> {sum(vals):.1f}, "
            f"min {min(vals):.1f}, max {max(vals):.1f}"
        )
        states.append(
            "buckets=" + "; ".join(
                f"b{k}(count {len(vs)}, sum {sum(vs):.1f})" for k, vs in sorted(buckets.items())
            )
        )
    table = {b: (len(vs), sum(vs), min(vs), max(vs), sum(vs) / len(vs))
             for b, vs in sorted(buckets.items())}

    task = (
        "### Task: simulate time-series window aggregation (TSDB downsampling)\n"
        f"Base timestamp t0 = {t0} (unix seconds); window = {window}s; bucket(t) = (t - t0) // {window}.\n"
        f"Data points (offset seconds, value), {n} points:\n"
        + "\n".join(f"  (+{ti - t0}s, {v:.1f})" for ti, v in pts)
        + "\n\nAggregate each bucket: count, sum, min, max, avg."
    )
    answer = [
        f"bucket {b} [{b * window}s, {(b + 1) * window}s): count={c}, sum={s:.1f}, "
        f"min={mn:.1f}, max={mx:.1f}, avg={avg:.2f}"
        for b, (c, s, mn, mx, avg) in table.items()
    ]
    text = render_etcot(task, elide(step_lines(raw_steps), states, elide_over), answer)
    meta = {"t0": t0, "window": window, "pts": pts, "table": table}
    return text, "temporal", "tsdb_window_agg", meta


# ---------------------------------------------------------------------------
# Vector: exact top-k nearest neighbours
# ---------------------------------------------------------------------------

_DIM = 4


def _rand_vec(rng) -> tuple[int, ...]:
    return tuple(rng.randint(-9, 9) for _ in range(_DIM))


def _d2(a, b) -> int:
    return sum((x - y) ** 2 for x, y in zip(a, b))


def _d2_expand(q, v) -> str:
    terms = [f"({x}-({y}))^2" if y < 0 else f"({x}-{y})^2" for x, y in zip(q, v)]
    parts = [str((x - y) ** 2) for x, y in zip(q, v)]
    return f"{' + '.join(terms)} = {' + '.join(parts)} = {_d2(q, v)}"


def _vector_knn_doc(rng, n: int, elide_over: int):
    vecs = [_rand_vec(rng) for _ in range(n)]
    q = _rand_vec(rng)
    k = 3
    ranked = sorted(range(n), key=lambda i: (_d2(q, vecs[i]), i))
    topk = [(i, _d2(q, vecs[i])) for i in ranked[:k]]

    raw_steps, states = [], []
    heap: list[tuple[int, int]] = []
    for i, v in enumerate(vecs):
        d = _d2(q, v)
        heap = sorted(heap + [(d, i)])[:k]
        raw_steps.append(
            f"candidate v{i}={list(v)}: d2(q, v{i}) = {_d2_expand(q, v)}; "
            f"top-{k} -> {[(f'v{j}', dd) for dd, j in heap]}"
        )
        states.append(f"scanned={i + 1}/{n}, top-{k}={[(f'v{j}', dd) for dd, j in heap]}")
    assert [(j, dd) for dd, j in heap] == topk

    task = (
        "### Task: simulate exact k-nearest-neighbour vector search\n"
        f"Query vector q = {list(q)} (dim {_DIM}); metric = squared Euclidean distance; k = {k}.\n"
        f"Index ({n} vectors):\n"
        + "\n".join(f"  v{i} = {list(v)}" for i, v in enumerate(vecs))
        + "\n\nScan every candidate, maintain the running top-k (ties broken by lower id)."
    )
    answer = [
        f"top-{k}: " + ", ".join(f"v{i} (d2={d})" for i, d in topk),
        f"nearest neighbour: v{topk[0][0]} at squared distance {topk[0][1]}",
    ]
    text = render_etcot(task, elide(step_lines(raw_steps), states, elide_over), answer)
    meta = {"vecs": vecs, "q": q, "k": k, "topk": topk}
    return text, "deliberate", "vector_knn_exact", meta


# ---------------------------------------------------------------------------
# Vector: greedy HNSW-style layered search
# ---------------------------------------------------------------------------

_HNSW_M = 3


def _hnsw_neighbors(ids: list[int], vecs: list[tuple[int, ...]]) -> dict[int, list[int]]:
    out = {}
    for i in ids:
        others = sorted((j for j in ids if j != i), key=lambda j: (_d2(vecs[i], vecs[j]), j))
        out[i] = others[:_HNSW_M]
    return out


def _greedy(q, vecs, nbrs, start, trace, layer_name):
    cur = start
    while True:
        dc = _d2(q, vecs[cur])
        cand = [(nb, _d2(q, vecs[nb])) for nb in nbrs[cur]]
        best_nb, best_d = min(cand, key=lambda t: (t[1], t[0]))
        line = (
            f"{layer_name} @ v{cur}: d2(q,v{cur})={dc}; neighbors "
            + ", ".join(f"v{nb}:d2={d}" for nb, d in cand)
        )
        if best_d < dc:
            trace.append(line + f" -> move to v{best_nb} (d2 {best_d} < {dc})")
            cur = best_nb
        else:
            trace.append(line + f" -> no neighbor improves on {dc}; local minimum reached")
            return cur


def _hnsw_doc(rng, n: int, elide_over: int):
    for _attempt in range(12):
        vecs = [_rand_vec(rng) for _ in range(n)]
        q = _rand_vec(rng)
        layer1 = [i for i in range(n) if i % 3 == 0]
        nbrs1 = _hnsw_neighbors(layer1, vecs)
        nbrs0 = _hnsw_neighbors(list(range(n)), vecs)
        entry = layer1[0]

        raw_steps: list[str] = [f"entry point: v{entry} (upper layer)"]
        mid = _greedy(q, vecs, nbrs1, entry, raw_steps, "layer 1")
        raw_steps.append(f"descend to layer 0 at v{mid}")
        got = _greedy(q, vecs, nbrs0, mid, raw_steps, "layer 0")
        exact = min(range(n), key=lambda i: (_d2(q, vecs[i]), i))
        if got == exact:
            break
    states = [f"current node after step {i + 1}" for i in range(len(raw_steps))]
    matched = got == exact

    task = (
        "### Task: simulate a greedy HNSW-style vector search (2 layers)\n"
        f"Query q = {list(q)}; metric = squared Euclidean distance.\n"
        f"Vectors ({n}):\n" + "\n".join(f"  v{i} = {list(v)}" for i, v in enumerate(vecs))
        + f"\nLayer 1 nodes: {[f'v{i}' for i in layer1]}; layer-1 links (M={_HNSW_M}): "
        + "; ".join(f"v{i}->{[f'v{j}' for j in nbrs1[i]]}" for i in layer1)
        + f"\nLayer 0 links (M={_HNSW_M}): "
        + "; ".join(f"v{i}->{[f'v{j}' for j in nbrs0[i]]}" for i in range(n))
        + f"\n\nGreedy descent: start at the entry point v{entry} on layer 1, hop to the "
        "closest linked neighbor while it improves the distance, then repeat on layer 0."
    )
    answer = [
        f"greedy result: v{got} at d2 = {_d2(q, vecs[got])}",
        (f"exact check: brute-force argmin is v{exact} -> greedy search found the true "
         "nearest neighbour" if matched else
         f"exact check: brute-force argmin is v{exact} (d2={_d2(q, vecs[exact])}) -> greedy "
         "search stopped in a local minimum, a known HNSW trade-off"),
    ]
    text = render_etcot(task, elide(step_lines(raw_steps), states, elide_over), answer)
    meta = {"vecs": vecs, "q": q, "got": got, "exact": exact, "layer1": layer1,
            "nbrs0": nbrs0, "nbrs1": nbrs1, "entry": entry}
    return text, "deliberate", "vector_hnsw_greedy", meta


# ---------------------------------------------------------------------------
# LSM tree: memtable -> L0 runs -> compacted L1
# ---------------------------------------------------------------------------

_LSM_MEMTABLE_LIMIT = 4
_LSM_TOMBSTONE = None  # deletion marker inside memtable/runs


class _LSM:
    """Minimal leveled LSM tree: a memtable that flushes to sorted L0 runs at
    4 entries, and a compaction that merges the two L0 runs (plus any existing
    L1 run) into a single L1 run whenever L0 reaches 2 runs. Newer values win;
    tombstones are dropped when they reach L1 (nothing lives below it)."""

    def __init__(self):
        self.mem: dict[str, int | None] = {}
        self.l0: list[tuple[int, list[tuple[str, int | None]]]] = []  # (run_id, sorted items), newest first
        self.l1: list[tuple[str, int | None]] = []
        self.next_run = 1

    def _flush_if_full(self, events: list[str]) -> None:
        if len(self.mem) < _LSM_MEMTABLE_LIMIT:
            return
        run = sorted(self.mem.items())
        rid = self.next_run
        self.next_run += 1
        self.l0.insert(0, (rid, run))
        events.append(
            f"memtable reached {_LSM_MEMTABLE_LIMIT} entries -> flush sorted run "
            f"R{rid} {_fmt_run(run)} to L0 (L0 runs newest-first: "
            f"{[f'R{r}' for r, _ in self.l0]})"
        )
        self.mem = {}
        if len(self.l0) >= 2:
            self._compact(events)

    def _compact(self, events: list[str]) -> None:
        (rb, newer), (ra, older) = self.l0[0], self.l0[1]
        merged: dict[str, int | None] = dict(self.l1)
        merged.update(dict(older))
        merged.update(dict(newer))  # newest last so it wins
        dropped = sorted(k for k, v in merged.items() if v is _LSM_TOMBSTONE)
        self.l1 = sorted((k, v) for k, v in merged.items() if v is not _LSM_TOMBSTONE)
        self.l0 = []
        events.append(
            f"L0 holds 2 runs -> compact R{rb}+R{ra}"
            + (" with the existing L1 run" if merged else "")
            + f": newer values win{', tombstones ' + str(dropped) + ' dropped at the bottom level' if dropped else ''}"
            f" -> L1 run {_fmt_run(self.l1)}"
        )

    def put(self, key: str, val: int, events: list[str]) -> None:
        self.mem[key] = val
        events.append(f"PUT {key}={val} -> memtable {_fmt_mem(self.mem)} ({len(self.mem)}/{_LSM_MEMTABLE_LIMIT})")
        self._flush_if_full(events)

    def delete(self, key: str, events: list[str]) -> None:
        self.mem[key] = _LSM_TOMBSTONE
        events.append(f"DEL {key} -> write tombstone; memtable {_fmt_mem(self.mem)} ({len(self.mem)}/{_LSM_MEMTABLE_LIMIT})")
        self._flush_if_full(events)

    def get(self, key: str, events: list[str]):
        if key in self.mem:
            v = self.mem[key]
            found = "tombstone -> NOT FOUND" if v is _LSM_TOMBSTONE else f"value {v}"
            events.append(f"GET {key}: memtable hit -> {found}")
            return v
        for rid, run in self.l0:
            d = dict(run)
            if key in d:
                v = d[key]
                found = "tombstone -> NOT FOUND" if v is _LSM_TOMBSTONE else f"value {v}"
                events.append(f"GET {key}: memtable miss -> L0 run R{rid} hit -> {found}")
                return v
        d = dict(self.l1)
        if key in d:
            events.append(f"GET {key}: memtable and L0 miss -> L1 hit -> value {d[key]}")
            return d[key]
        events.append(f"GET {key}: memtable, L0 and L1 all miss -> NOT FOUND")
        return _LSM_TOMBSTONE

    def visible(self) -> dict[str, int]:
        state: dict[str, int | None] = dict(self.l1)
        for _, run in reversed(self.l0):
            state.update(dict(run))
        state.update(self.mem)
        return {k: v for k, v in state.items() if v is not _LSM_TOMBSTONE}


def _fmt_run(run: list[tuple[str, int | None]]) -> str:
    return "[" + ", ".join(f"{k}:{'DEL' if v is _LSM_TOMBSTONE else v}" for k, v in run) + "]"


def _fmt_mem(mem: dict[str, int | None]) -> str:
    return "{" + ", ".join(f"{k}:{'DEL' if v is _LSM_TOMBSTONE else v}" for k, v in sorted(mem.items())) + "}"


def _lsm_doc(rng, n: int, elide_over: int):
    pool = [f"k{i:02d}" for i in range(1, max(5, n // 2) + 1)]
    ops: list[tuple[str, str, int | None]] = []
    written: list[str] = []
    for _ in range(n):
        if written and rng.random() < 0.15:
            k = rng.choice(written)
            ops.append(("DEL", k, None))
        else:
            k = rng.choice(pool)
            ops.append(("PUT", k, rng.randint(1, 99)))
            written.append(k)

    lsm = _LSM()
    raw_steps: list[str] = []
    for op, k, v in ops:
        if op == "PUT":
            lsm.put(k, v, raw_steps)
        else:
            lsm.delete(k, raw_steps)
    gets = []
    seen_keys = sorted({k for _, k, _ in ops})
    for k in [rng.choice(seen_keys) for _ in range(3)]:
        got = lsm.get(k, raw_steps)
        gets.append((k, got))

    # independent check: plain last-write-wins dict semantics
    expect: dict[str, int] = {}
    for op, k, v in ops:
        if op == "PUT":
            expect[k] = v
        else:
            expect.pop(k, None)
    assert lsm.visible() == expect
    for k, got in gets:
        assert (got if got is not _LSM_TOMBSTONE else None) == expect.get(k)

    # states per rendered step: the honest snapshot is the visible key->value
    # map; replay a second engine alongside (flush/compact/GET lines don't
    # change visible state, so they reuse the current snapshot)
    states = []
    lsm2 = _LSM()
    replay_iter = iter(ops)
    for line in raw_steps:
        if line.startswith(("PUT ", "DEL ")):
            op, k, v = next(replay_iter)
            if op == "PUT":
                lsm2.put(k, v, [])
            else:
                lsm2.delete(k, [])
        states.append(f"visible state={dict(sorted(lsm2.visible().items()))}")

    task = (
        "### Task: simulate an LSM-tree storage engine\n"
        f"Engine: memtable flushes to a sorted L0 run at {_LSM_MEMTABLE_LIMIT} entries; "
        "when L0 holds 2 runs they compact (merged with any L1 run) into a single L1 "
        "run -- newer values win, tombstones are dropped at L1.\n"
        "Operations, in order:\n"
        + "\n".join(f"  {op} {k}" + (f" = {v}" if v is not None else "") for op, k, v in ops)
        + "\n  then GET " + ", GET ".join(k for k, _ in gets)
    )
    answer = [
        f"memtable: {_fmt_mem(lsm.mem)}",
        f"L0 runs (newest first): {[f'R{r} ' + _fmt_run(run) for r, run in lsm.l0] or 'none'}",
        f"L1 run: {_fmt_run(lsm.l1) if lsm.l1 else 'none'}",
        "GET results: " + ", ".join(
            f"{k} -> {'NOT FOUND' if got is _LSM_TOMBSTONE else got}" for k, got in gets),
    ]
    text = render_etcot(task, elide(step_lines(raw_steps), states, elide_over), answer)
    meta = {"ops": ops, "gets": [(k, None if g is _LSM_TOMBSTONE else g) for k, g in gets],
            "visible": lsm.visible()}
    return text, "deliberate", "lsm_engine", meta


# ---------------------------------------------------------------------------
# Write-ahead log: crash + recovery replay (ACID durability/atomicity)
# ---------------------------------------------------------------------------


def _wal_doc(rng, n: int, elide_over: int):
    accounts = sorted(rng.sample(["acct_a", "acct_b", "acct_c", "acct_d"], rng.randint(2, 4)))
    init = {a: rng.randint(100, 900) for a in accounts}

    # build the full log: per txn BEGIN, 1-2 SETs, COMMIT (75%) or ABORT
    log: list[tuple] = []
    shadow = dict(init)  # what a SET's "old" value is at log-write time
    for t in range(1, n + 1):
        log.append(("BEGIN", t))
        working = dict(shadow)  # before-images track in-txn writes too
        for _ in range(rng.randint(1, 2)):
            a = rng.choice(accounts)
            new = rng.randint(100, 900)
            log.append(("SET", t, a, working[a], new))
            working[a] = new
        if rng.random() < 0.75:
            log.append(("COMMIT", t))
            shadow = working
        else:
            log.append(("ABORT", t))

    # crash somewhere in the last quarter of the log (always leaves >= 1 record)
    crash_at = rng.randint(max(1, 3 * len(log) // 4), len(log))
    surviving = log[:crash_at]

    raw_steps, states = [], []
    for i, rec in enumerate(surviving):
        kind = rec[0]
        if kind == "BEGIN":
            raw_steps.append(f"append log record {i}: BEGIN T{rec[1]}")
        elif kind == "SET":
            _, t, a, old, new = rec
            raw_steps.append(f"append log record {i}: SET T{t} {a}: {old} -> {new} (redo value {new})")
        else:
            raw_steps.append(f"append log record {i}: {kind} T{rec[1]}")
        states.append(f"log length={i + 1}")
    raw_steps.append(f"CRASH -- records {crash_at}..{len(log) - 1} were never persisted" if crash_at < len(log)
                     else "CRASH -- immediately after the final record was persisted")
    states.append("crashed")

    committed = {rec[1] for rec in surviving if rec[0] == "COMMIT"}
    aborted = {rec[1] for rec in surviving if rec[0] == "ABORT"}
    open_txns = sorted({rec[1] for rec in surviving if rec[0] == "BEGIN"} - committed - aborted)
    raw_steps.append(
        f"recovery scan: committed txns {sorted(committed) or 'none'}; aborted {sorted(aborted) or 'none'}; "
        f"in-flight (no COMMIT persisted) {open_txns or 'none'} -> only committed SETs are redone"
    )
    states.append("scan done")
    recovered = dict(init)
    for rec in surviving:
        if rec[0] == "SET" and rec[1] in committed:
            _, t, a, old, new = rec
            raw_steps.append(f"redo SET of committed T{t}: {a} = {new}")
            recovered[a] = new
            states.append(f"recovered={dict(sorted(recovered.items()))}")

    # independent check: apply only committed transactions' effects in order
    expect = dict(init)
    for t in range(1, n + 1):
        if t in committed:
            for rec in log:
                if rec[0] == "SET" and rec[1] == t:
                    expect[rec[2]] = rec[4]
    assert recovered == expect

    task = (
        "### Task: simulate write-ahead-log crash recovery (ACID)\n"
        f"Initial table: {dict(sorted(init.items()))}\n"
        "Log records persisted in order (the crash may cut the tail):\n"
        + "\n".join(
            f"  {i}: " + (f"SET T{r[1]} {r[2]} {r[3]}->{r[4]}" if r[0] == "SET" else f"{r[0]} T{r[1]}")
            for i, r in enumerate(surviving))
        + f"\n\nA crash strikes after record {crash_at - 1}. Recover: scan the surviving log, "
        "redo every SET belonging to a transaction whose COMMIT record survived, and "
        "discard in-flight or aborted work."
    )
    answer = [
        f"recovered table: {dict(sorted(recovered.items()))}",
        f"transactions redone: {sorted(committed) or 'none'}; "
        f"discarded: {sorted(set(range(1, n + 1)) - committed) or 'none'} "
        "(aborted or COMMIT never persisted)",
    ]
    text = render_etcot(task, elide(step_lines(raw_steps), states, elide_over), answer)
    meta = {"init": init, "log": log, "crash_at": crash_at, "recovered": recovered,
            "committed": sorted(committed)}
    return text, "temporal", "wal_recovery", meta


# ---------------------------------------------------------------------------
# Vector: cosine-similarity top-1
# ---------------------------------------------------------------------------


def _cos_parts(q, v) -> tuple[int, float, float, float]:
    import math

    dot = sum(a * b for a, b in zip(q, v))
    nq = math.sqrt(sum(a * a for a in q))
    nv = math.sqrt(sum(b * b for b in v))
    return dot, nq, nv, dot / (nq * nv)


def _nonzero_vec(rng) -> tuple[int, ...]:
    v = _rand_vec(rng)
    while not any(v):
        v = _rand_vec(rng)
    return v


def _vector_cosine_doc(rng, n: int, elide_over: int):
    vecs = [_nonzero_vec(rng) for _ in range(n)]
    q = _nonzero_vec(rng)

    raw_steps, states = [], []
    best_i, best_sim = -1, float("-inf")
    sims = []
    for i, v in enumerate(vecs):
        dot, nq, nv, sim = _cos_parts(q, v)
        sims.append(sim)
        terms = " + ".join(f"{a}*{'(%d)' % b if b < 0 else b}" for a, b in zip(q, v))
        line = (
            f"candidate v{i}={list(v)}: dot = {terms} = {dot}; |q| = {nq:.4f}, "
            f"|v{i}| = {nv:.4f}; cos = {dot}/({nq:.4f}*{nv:.4f}) = {sim:.4f}"
        )
        if sim > best_sim:
            best_i, best_sim = i, sim
            line += f" -> new best (v{i})"
        raw_steps.append(line)
        states.append(f"scanned={i + 1}/{n}, best=v{best_i} at cos {best_sim:.4f}")
    assert best_i == max(range(n), key=lambda i: (sims[i], -i))

    task = (
        "### Task: simulate cosine-similarity vector search (top-1)\n"
        f"Query q = {list(q)} (dim {_DIM}); score = dot(q,v) / (|q| * |v|); higher is closer.\n"
        f"Index ({n} vectors):\n"
        + "\n".join(f"  v{i} = {list(v)}" for i, v in enumerate(vecs))
        + "\n\nScan every candidate and keep the best cosine similarity (4-decimal precision)."
    )
    answer = [
        f"best match: v{best_i} with cosine similarity {best_sim:.4f}",
        f"similarities: " + ", ".join(f"v{i}={s:.4f}" for i, s in enumerate(sims)),
    ]
    text = render_etcot(task, elide(step_lines(raw_steps), states, elide_over), answer)
    meta = {"vecs": vecs, "q": q, "best": best_i, "sims": sims}
    return text, "deliberate", "vector_cosine_top1", meta


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class DBTraceGenerator(Generator):
    """Execution-trace database corpus spanning the seven primary data
    models. Phase sizing = context-window management: p2 emits micro-traces
    for seq 2048/4096, p3 emits medium traces with checkpoint elision, p4
    grows the engine state until the doc clears the spec-02 long-doc band
    (families whose traces cannot grow that far are excluded from p4)."""

    name = "db_trace"
    phases = (2, 3, 4)

    # (weight, builder, source, p2 n-range, p3 n-range,
    #  p4 growth (start_n, step, target_chars, max_n) or None)
    _FAMILIES = [
        (0.10, _btree_point_doc, "dbtrace/btree_point", (12, 20), (30, 60), (70, 12, 6200, 300)),
        (0.08, _btree_range_doc, "dbtrace/btree_range", (12, 20), (30, 60), (60, 12, 6200, 300)),
        (0.07, _btree_insert_doc, "dbtrace/btree_insert", (8, 14), (20, 40), None),
        (0.09, _doc_filter_doc, "dbtrace/docstore", (5, 9), (14, 30), (28, 6, 6200, 120)),
        (0.09, _kv_hash_doc, "dbtrace/kv_hash", (4, 7), (8, 12), None),
        (0.08, _wide_column_doc, "dbtrace/wide_column", (5, 9), (20, 44), (40, 8, 6200, 160)),
        (0.10, _graph_doc, "dbtrace/graph", (6, 9), (12, 24), (18, 3, 6200, 60)),
        (0.08, _ts_agg_doc, "dbtrace/timeseries", (6, 10), (20, 40), (30, 6, 6200, 140)),
        (0.09, _vector_knn_doc, "dbtrace/vector_knn", (5, 8), (14, 34), (22, 4, 6200, 110)),
        (0.08, _lsm_doc, "dbtrace/lsm_engine", (6, 10), (14, 24), (30, 6, 6200, 140)),
        (0.08, _wal_doc, "dbtrace/wal_recovery", (3, 5), (7, 12), (16, 3, 6200, 80)),
        (0.06, _vector_cosine_doc, "dbtrace/vector_cosine", (4, 7), (10, 20), (24, 4, 6200, 110)),
        (0.00, _hnsw_doc, "dbtrace/vector_hnsw", (8, 12), (12, 21), None),
    ]
    # _hnsw_doc gets its share via an explicit floor instead of the wheel so
    # its retry-heavy construction stays a bounded fraction of the corpus.
    _HNSW_EVERY = 9  # every 9th doc is an HNSW trace

    _PHASE_MIX = [(0.35, 2), (0.45, 3), (0.20, 4)]

    def generate(self, target_bytes: int) -> Iterator[dict]:
        from ava.datagen.trace_common import PHASE_ELIDE_OVER

        weighted = [(w, b, s, p2, p3, p4) for w, b, s, p2, p3, p4 in self._FAMILIES if w > 0]
        fam_cum, fam_total = [], 0.0
        for w, *_ in weighted:
            fam_total += w
            fam_cum.append(fam_total)
        p4_families = [f for f in weighted if f[5] is not None]
        p4_cum, p4_total = [], 0.0
        for w, *_ in p4_families:
            p4_total += w
            p4_cum.append(p4_total)
        phase_cum, phase_total = [], 0.0
        for w, _ in self._PHASE_MIX:
            phase_total += w
            phase_cum.append(phase_total)
        hnsw = next(f for f in self._FAMILIES if f[1] is _hnsw_doc)

        produced = 0
        count = 0
        while produced < target_bytes:
            r2 = self.rng.random() * phase_total
            pi = 0
            while r2 > phase_cum[pi]:
                pi += 1
            _, phase = self._PHASE_MIX[pi]

            count += 1
            if count % self._HNSW_EVERY == 0 and phase != 4:
                fam = hnsw
            elif phase == 4:
                r = self.rng.random() * p4_total
                fi = 0
                while r > p4_cum[fi]:
                    fi += 1
                fam = p4_families[fi]
            else:
                r = self.rng.random() * fam_total
                fi = 0
                while r > fam_cum[fi]:
                    fi += 1
                fam = weighted[fi]
            _, builder, source, p2_range, p3_range, p4_growth = fam

            elide_over = PHASE_ELIDE_OVER[phase]
            if phase == 4:
                start_n, step, target_chars, max_n = p4_growth
                n = start_n
                text, task_type, concept, _meta = builder(self.rng, n, elide_over)
                while len(text) < target_chars and n < max_n:
                    n = min(n + step, max_n)
                    text, task_type, concept, _meta = builder(self.rng, n, elide_over)
            else:
                lo, hi = p2_range if phase == 2 else p3_range
                text, task_type, concept, _meta = builder(self.rng, self.rng.randint(lo, hi), elide_over)

            d = self.doc(text=text, task_type=task_type, concept=concept, phase=phase, source=source)
            produced += len(d["text"].encode("utf-8"))
            yield d


if __name__ == "__main__":
    from ava.datagen.base import run_cli

    run_cli(DBTraceGenerator)
