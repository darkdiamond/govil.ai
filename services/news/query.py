"""Read-only SQL over a dataset's tables, for the writer.

The model writes SQL, never Python: an in-memory DuckDB with the recipe's
input tables registered from pandas, then external access (files, network,
extensions) switched off and the configuration locked, so a query can read
those tables and nothing else. One SELECT per call, a wall-clock timeout
(the connection is interrupted), a row cap on what comes back.
"""
from __future__ import annotations

import re
import threading

import pandas as pd

TIMEOUT_S = 20.0
MAX_ROWS = 60
MEMORY_LIMIT = "1GB"
_NUMERIC = re.compile(r"^\s*-?\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*$|^\s*-?\d+(?:\.\d+)?\s*$")


class QueryError(Exception):
    pass


def _typed(df: pd.DataFrame, *, copy: bool = True) -> pd.DataFrame:
    """Recipe inputs arrive as all-text (recipe_exec.load_frames). A column
    whose every non-empty value is a plain number becomes numeric, so SUM /
    AVG / comparisons work without casts; everything else stays text.
    `copy=False` converts the caller's frame in place (it is about to be dropped)."""
    out = df.copy() if copy else df
    for c in out.columns:
        s = out[c].astype(str)
        vals = s[s.str.strip() != ""]
        if len(vals) and vals.str.match(_NUMERIC).all():
            out[c] = pd.to_numeric(s.str.replace(",", "", regex=False).str.strip().replace("", None),
                                   errors="coerce")
    return out


def _duckdb():
    # Imported on first use: only the news job installs it
    # (services/news/requirements.txt); the builder venv need not have it.
    import duckdb

    return duckdb


class TableQuery:
    def __init__(self, tables: dict[str, pd.DataFrame], *, timeout_s: float = TIMEOUT_S,
                 max_rows: int = MAX_ROWS, consume: bool = False):
        """`consume`: the frames are the caller's to give up. Each is typed in
        place and removed from `tables` once its DuckDB table exists, so only
        DuckDB's copy stays in memory."""
        self.timeout_s, self.max_rows = timeout_s, max_rows
        duckdb = self._db = _duckdb()
        self.con = duckdb.connect(":memory:", config={
            "autoinstall_known_extensions": False,
            "autoload_known_extensions": False,
            "memory_limit": MEMORY_LIMIT,
            "threads": 2,
        })
        self.schema: dict[str, list[tuple[str, str]]] = {}
        for name in list(tables):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise QueryError(f"bad table name {name!r}")
            df = _typed(tables.pop(name) if consume else tables[name], copy=not consume)
            self.con.register(f"_df_{name}", df)
            self.con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM "_df_{name}"')
            self.con.unregister(f"_df_{name}")
            del df
            self.schema[name] = [(r[0], r[1]) for r in
                                 self.con.execute(f'DESCRIBE "{name}"').fetchall()]
        self.con.execute("SET enable_external_access = false")
        self.con.execute("SET lock_configuration = true")

    def run(self, sql: str) -> dict:
        duckdb = self._db
        stmts = duckdb.extract_statements(sql)
        if len(stmts) != 1:
            raise QueryError("exactly one statement per query")
        if stmts[0].type != duckdb.StatementType.SELECT:
            raise QueryError("only SELECT queries are allowed")
        timer = threading.Timer(self.timeout_s, self.con.interrupt)
        timer.start()
        try:
            cur = self.con.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchmany(self.max_rows + 1)
        except duckdb.InterruptException as e:
            raise QueryError(f"query took longer than {self.timeout_s:.0f}s") from e
        except duckdb.Error as e:
            raise QueryError(str(e).splitlines()[0][:300]) from e
        finally:
            timer.cancel()
        return {"columns": cols, "rows": [list(r) for r in rows[: self.max_rows]],
                "truncated": len(rows) > self.max_rows}

    def close(self):
        self.con.close()
