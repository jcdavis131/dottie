# Solo personal project, no connection to employer, built with public/free-tier only
"""SQLite property-graph store — stdlib only, provenance-mandatory.

Every node and edge carries ``source`` (which ingester wrote it) and
``source_ref`` (a citation into the real substrate: ``file:Lline``,
``ledger:experiments:<id>``, ``metrics_nano.jsonl:<lineno>``). That is the
graphify idea adopted natively: an answer is a graph path whose every hop can
be traced back to a real file location — never an uncited assertion.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nodes (
  id         TEXT PRIMARY KEY,
  type       TEXT NOT NULL,
  label      TEXT NOT NULL DEFAULT '',
  props      TEXT NOT NULL DEFAULT '{}',
  source     TEXT NOT NULL DEFAULT '',
  source_ref TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE TABLE IF NOT EXISTS edges (
  src        TEXT NOT NULL,
  dst        TEXT NOT NULL,
  type       TEXT NOT NULL,
  props      TEXT NOT NULL DEFAULT '{}',
  source     TEXT NOT NULL DEFAULT '',
  source_ref TEXT NOT NULL DEFAULT '',
  UNIQUE (src, dst, type)
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
"""


def open_source_ro(path: str | Path) -> sqlite3.Connection:
    """Open a SOURCE sqlite database strictly read-only (URI mode=ro)."""
    posix = str(Path(path).resolve()).replace("\\", "/")
    con = sqlite3.connect(f"file:{posix}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


class GraphStore:
    """The graph database. Nodes are ``type:key`` ids; edges are typed triples."""

    def __init__(self, path: str | Path, readonly: bool = False) -> None:
        self.path = Path(path)
        if readonly:
            self.con = open_source_ro(self.path)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.con = sqlite3.connect(str(self.path))
            self.con.row_factory = sqlite3.Row
            self.con.executescript(_SCHEMA)

    # -- write ---------------------------------------------------------------

    def upsert_node(
        self,
        node_id: str,
        ntype: str,
        label: str = "",
        props: dict[str, Any] | None = None,
        source: str = "",
        source_ref: str = "",
    ) -> None:
        """Insert or merge: new props update old, existing props survive."""
        row = self.con.execute(
            "SELECT props, label FROM nodes WHERE id=?", (node_id,)
        ).fetchone()
        if row is None:
            self.con.execute(
                "INSERT INTO nodes (id, type, label, props, source, source_ref) "
                "VALUES (?,?,?,?,?,?)",
                (
                    node_id,
                    ntype,
                    label or node_id,
                    json.dumps(props or {}, default=str),
                    source,
                    source_ref,
                ),
            )
        else:
            merged = json.loads(row["props"])
            merged.update(props or {})
            self.con.execute(
                "UPDATE nodes SET props=?, label=CASE WHEN ?='' THEN label ELSE ? END "
                "WHERE id=?",
                (json.dumps(merged, default=str), label, label, node_id),
            )

    def add_edge(
        self,
        src: str,
        dst: str,
        etype: str,
        props: dict[str, Any] | None = None,
        source: str = "",
        source_ref: str = "",
    ) -> None:
        self.con.execute(
            "INSERT OR IGNORE INTO edges (src, dst, type, props, source, source_ref) "
            "VALUES (?,?,?,?,?,?)",
            (src, dst, etype, json.dumps(props or {}, default=str), source, source_ref),
        )

    def set_meta(self, key: str, value: str) -> None:
        self.con.execute(
            "INSERT INTO meta (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def commit(self) -> None:
        self.con.commit()

    def close(self) -> None:
        self.con.close()

    # -- read ----------------------------------------------------------------

    def counts(self) -> dict[str, Any]:
        nodes = {
            r["type"]: r["c"]
            for r in self.con.execute(
                "SELECT type, COUNT(*) c FROM nodes GROUP BY type ORDER BY c DESC"
            )
        }
        edges = {
            r["type"]: r["c"]
            for r in self.con.execute(
                "SELECT type, COUNT(*) c FROM edges GROUP BY type ORDER BY c DESC"
            )
        }
        return {
            "total_nodes": sum(nodes.values()),
            "total_edges": sum(edges.values()),
            "nodes_by_type": nodes,
            "edges_by_type": edges,
        }

    def node(self, node_id: str) -> dict[str, Any] | None:
        row = self.con.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        return self._node_dict(row) if row else None

    def nodes_by_type(self, ntype: str) -> list[dict[str, Any]]:
        return [
            self._node_dict(r)
            for r in self.con.execute(
                "SELECT * FROM nodes WHERE type=? ORDER BY id", (ntype,)
            )
        ]

    def find_nodes(self, substring: str, limit: int = 50) -> list[dict[str, Any]]:
        pat = f"%{substring}%"
        return [
            self._node_dict(r)
            for r in self.con.execute(
                "SELECT * FROM nodes WHERE id LIKE ? OR label LIKE ? LIMIT ?",
                (pat, pat, limit),
            )
        ]

    def edges_from(self, node_id: str) -> list[dict[str, Any]]:
        return [
            self._edge_dict(r)
            for r in self.con.execute(
                "SELECT * FROM edges WHERE src=? ORDER BY type, dst", (node_id,)
            )
        ]

    def edges_to(self, node_id: str) -> list[dict[str, Any]]:
        return [
            self._edge_dict(r)
            for r in self.con.execute(
                "SELECT * FROM edges WHERE dst=? ORDER BY type, src", (node_id,)
            )
        ]

    def chain_back(
        self, node_id: str, etype: str = "preceded_by", limit: int = 10
    ) -> list[dict[str, Any]]:
        """Walk ``etype`` edges backwards in time: node -> its predecessor -> ...

        Returns the predecessors oldest-last (i.e. nearest predecessor first).
        """
        out: list[dict[str, Any]] = []
        current = node_id
        seen = {current}
        while len(out) < limit:
            row = self.con.execute(
                "SELECT dst FROM edges WHERE src=? AND type=? LIMIT 1", (current, etype)
            ).fetchone()
            if row is None or row["dst"] in seen:
                break
            current = row["dst"]
            seen.add(current)
            node = self.node(current)
            if node is None:
                break
            out.append(node)
        return out

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _node_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "type": row["type"],
            "label": row["label"],
            "props": json.loads(row["props"]),
            "source": row["source"],
            "source_ref": row["source_ref"],
        }

    @staticmethod
    def _edge_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "src": row["src"],
            "dst": row["dst"],
            "type": row["type"],
            "props": json.loads(row["props"]),
            "source": row["source"],
            "source_ref": row["source_ref"],
        }
