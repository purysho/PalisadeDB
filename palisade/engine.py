from __future__ import annotations

import json
import os
import struct
from pathlib import Path
from typing import Callable

from .btree import BPlusTree, BTreeError, INTERNAL, LEAF, decode_internal, decode_leaf, page_type
from .pager import PAGE_SIZE, Pager, PagerError, SimulatedCrash
from .sql import CreateTable, Delete, Insert, Select, SQLError, parse

MAGIC = b"PALISADE"
VERSION = 1
SUPER = struct.Struct("<8sIIIIIQ")  # magic, version, page_size, next_page, catalog_page, flags, last_txid
CATALOG_TYPE = 0x10
CATALOG_HEAD = struct.Struct("<BI11x")  # type, payload length


class DatabaseError(Exception):
    pass


def encode_super(state: dict) -> bytes:
    out = bytearray(SUPER.pack(
        MAGIC,
        VERSION,
        PAGE_SIZE,
        state["next_page"],
        state["catalog_page"],
        0,
        state["last_txid"],
    ))
    out += bytes(PAGE_SIZE - len(out))
    return bytes(out)


def decode_super(data: bytes) -> dict:
    if len(data) != PAGE_SIZE:
        raise DatabaseError("invalid superblock length")
    magic, version, page_size, next_page, catalog_page, _flags, last_txid = SUPER.unpack_from(data, 0)
    if magic != MAGIC:
        raise DatabaseError("not a PalisadeDB database")
    if version != VERSION:
        raise DatabaseError(f"unsupported database version {version}")
    if page_size != PAGE_SIZE:
        raise DatabaseError(f"unsupported page size {page_size}")
    return {"next_page": next_page, "catalog_page": catalog_page, "last_txid": last_txid}


def encode_catalog(catalog: dict) -> bytes:
    payload = json.dumps(catalog, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if CATALOG_HEAD.size + len(payload) > PAGE_SIZE:
        raise DatabaseError("catalog page full; V1 supports a single catalog page")
    out = bytearray(CATALOG_HEAD.pack(CATALOG_TYPE, len(payload)))
    out += payload
    out += bytes(PAGE_SIZE - len(out))
    return bytes(out)


def decode_catalog(data: bytes) -> dict:
    if len(data) != PAGE_SIZE or data[0] != CATALOG_TYPE:
        raise DatabaseError("invalid catalog page")
    _, length = CATALOG_HEAD.unpack_from(data, 0)
    payload = data[CATALOG_HEAD.size:CATALOG_HEAD.size + length]
    try:
        return json.loads(payload.decode("utf-8"))
    except Exception as exc:
        raise DatabaseError("corrupt catalog JSON") from exc


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        is_new = not self.path.exists() or self.path.stat().st_size == 0
        self.pager = Pager(self.path)
        if is_new:
            self._initialize()
        self.super = decode_super(self.pager.read_page(0))
        self.catalog = decode_catalog(self.pager.read_page(self.super["catalog_page"]))

    def _initialize(self) -> None:
        state = {"next_page": 2, "catalog_page": 1, "last_txid": 0}
        catalog = {"tables": {}}
        # Initial creation is direct because there is no prior database state to recover.
        with self.path.open("wb") as f:
            f.write(encode_super(state))
            f.write(encode_catalog(catalog))
            f.flush()
            os.fsync(f.fileno())

    def _begin_write(self):
        txid = self.super["last_txid"] + 1
        tx = self.pager.begin(txid)
        state = dict(self.super)
        catalog = json.loads(json.dumps(self.catalog))

        def allocate() -> int:
            page = state["next_page"]
            state["next_page"] += 1
            return page

        return txid, tx, state, catalog, allocate

    def _finish_write(self, txid, tx, state, catalog, *, crash_after_wal=False):
        state["last_txid"] = txid
        tx.write_page(0, encode_super(state))
        tx.write_page(state["catalog_page"], encode_catalog(catalog))
        tx.commit(crash_after_wal=crash_after_wal)
        self.super = state
        self.catalog = catalog

    def _table(self, name: str) -> dict:
        table = self.catalog["tables"].get(name)
        if not table:
            raise DatabaseError(f"no such table: {name}")
        return table

    def create_table(self, name: str, columns: list[dict]) -> None:
        if name in self.catalog["tables"]:
            raise DatabaseError(f"table already exists: {name}")
        if not columns:
            raise DatabaseError("table must have at least one column")
        names = [c["name"] for c in columns]
        if len(set(names)) != len(names):
            raise DatabaseError("duplicate column name")
        pk = [c for c in columns if c["primary_key"]]
        if len(pk) != 1 or pk[0]["type"] != "INTEGER":
            raise DatabaseError("V1 requires exactly one INTEGER PRIMARY KEY")

        txid, tx, state, catalog, allocate = self._begin_write()
        tree = BPlusTree(tx, allocate)
        root = tree.make_empty()
        catalog["tables"][name] = {
            "columns": columns,
            "primary_key": pk[0]["name"],
            "root_page": root,
        }
        self._finish_write(txid, tx, state, catalog)

    def _validate_row(self, table: dict, values: list[object]) -> dict:
        cols = table["columns"]
        if len(values) != len(cols):
            raise DatabaseError(f"expected {len(cols)} values, got {len(values)}")
        row = {}
        for col, value in zip(cols, values):
            typ = col["type"]
            if typ == "INTEGER" and not isinstance(value, int):
                raise DatabaseError(f"column {col['name']} requires INTEGER")
            if typ == "TEXT" and not isinstance(value, str):
                raise DatabaseError(f"column {col['name']} requires TEXT")
            row[col["name"]] = value
        return row

    def insert(self, table_name: str, values: list[object], *, crash_after_wal: bool = False) -> None:
        current = self._table(table_name)
        row = self._validate_row(current, values)
        key = row[current["primary_key"]]
        txid, tx, state, catalog, allocate = self._begin_write()
        table = catalog["tables"][table_name]
        tree = BPlusTree(tx, allocate)
        new_root = tree.insert(table["root_page"], key, row)
        table["root_page"] = new_root
        self._finish_write(txid, tx, state, catalog, crash_after_wal=crash_after_wal)

    def _match(self, left, op: str, right) -> bool:
        ops: dict[str, Callable] = {
            "=": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
            "<": lambda a, b: a < b,
            ">": lambda a, b: a > b,
            "<=": lambda a, b: a <= b,
            ">=": lambda a, b: a >= b,
        }
        try:
            return ops[op](left, right)
        except TypeError:
            return False

    def select(self, table_name: str, where=None) -> list[dict]:
        table = self._table(table_name)
        tx = self.pager.begin(self.super["last_txid"])
        tree = BPlusTree(tx, lambda: (_ for _ in ()).throw(DatabaseError("read-only")))
        if where and where[0] == table["primary_key"] and where[1] == "=" and isinstance(where[2], int):
            row = tree.get(table["root_page"], where[2])
            rows = [row] if row is not None else []
        else:
            rows = [row for _, row in tree.iter_rows(table["root_page"])]
        if where:
            col, op, value = where
            if col not in {c["name"] for c in table["columns"]}:
                raise DatabaseError(f"no such column: {col}")
            rows = [r for r in rows if self._match(r[col], op, value)]
        return rows

    def delete(self, table_name: str, where) -> int:
        table_current = self._table(table_name)
        col, op, value = where
        if col not in {c["name"] for c in table_current["columns"]}:
            raise DatabaseError(f"no such column: {col}")

        if col == table_current["primary_key"] and op == "=" and isinstance(value, int):
            keys = [value]
        else:
            keys = [r[table_current["primary_key"]] for r in self.select(table_name, where)]
        if not keys:
            return 0

        txid, tx, state, catalog, allocate = self._begin_write()
        table = catalog["tables"][table_name]
        tree = BPlusTree(tx, allocate)
        deleted = 0
        for key in keys:
            if tree.delete(table["root_page"], key):
                deleted += 1
        self._finish_write(txid, tx, state, catalog)
        return deleted

    def execute(self, sql: str):
        stmt = parse(sql)
        if isinstance(stmt, CreateTable):
            self.create_table(stmt.table, stmt.columns)
            return {"kind": "status", "message": f"created table {stmt.table}"}
        if isinstance(stmt, Insert):
            self.insert(stmt.table, stmt.values)
            return {"kind": "status", "message": "1 row inserted"}
        if isinstance(stmt, Select):
            return {"kind": "rows", "rows": self.select(stmt.table, stmt.where)}
        if isinstance(stmt, Delete):
            n = self.delete(stmt.table, stmt.where)
            return {"kind": "status", "message": f"{n} row(s) deleted"}
        raise SQLError("unsupported statement")

    def tables(self) -> list[str]:
        return sorted(self.catalog["tables"])

    def schema(self, table_name: str) -> str:
        table = self._table(table_name)
        cols = []
        for c in table["columns"]:
            text = f"{c['name']} {c['type']}"
            if c["primary_key"]:
                text += " PRIMARY KEY"
            cols.append(text)
        return f"CREATE TABLE {table_name} ({', '.join(cols)});"

    def btree(self, table_name: str) -> dict:
        table = self._table(table_name)
        tx = self.pager.begin(self.super["last_txid"])
        return BPlusTree(tx, lambda: 0).describe(table["root_page"])

    def pages(self) -> list[dict]:
        result = []
        for p in range(self.pager.page_count()):
            data = self.pager.read_page(p)
            typ = data[0]
            if p == 0:
                label = "superblock"
            elif typ == CATALOG_TYPE:
                label = "catalog"
            elif typ == LEAF:
                label = "btree-leaf"
            elif typ == INTERNAL:
                label = "btree-internal"
            else:
                label = f"unknown({typ:#x})"
            result.append({"page": p, "type": label})
        return result

    def stats(self) -> dict:
        tables = {}
        for name, table in self.catalog["tables"].items():
            desc = self.btree(name)
            tables[name] = {
                "rows": len(self.select(name)),
                "root_page": table["root_page"],
                "tree_height": desc["height"],
                "tree_pages": desc["pages"],
            }
        return {
            "file": str(self.path),
            "bytes": self.path.stat().st_size,
            "page_size": PAGE_SIZE,
            "pages": self.pager.page_count(),
            "last_txid": self.super["last_txid"],
            "tables": tables,
            "wal": self.pager.wal_status(),
            "recovery": self.pager.recovery.__dict__,
        }

    def integrity_check(self) -> list[str]:
        issues: list[str] = []
        try:
            decode_super(self.pager.read_page(0))
            decode_catalog(self.pager.read_page(self.super["catalog_page"]))
        except Exception as exc:
            issues.append(str(exc))
            return issues

        page_count = self.pager.page_count()
        referenced: set[int] = {0, self.super["catalog_page"]}
        for name, table in self.catalog["tables"].items():
            try:
                desc = self.btree(name)
                for level in desc["levels"]:
                    for node in level:
                        page = node["page"]
                        referenced.add(page)
                        if page >= page_count:
                            issues.append(f"{name}: references out-of-range page {page}")
                        keys = node["keys"]
                        if keys != sorted(keys) or len(keys) != len(set(keys)):
                            issues.append(f"{name}: unsorted/duplicate keys on page {page}")
                rows = self.select(name)
                pk = table["primary_key"]
                keys = [r[pk] for r in rows]
                if keys != sorted(keys):
                    issues.append(f"{name}: leaf chain is not globally sorted")
                if len(keys) != len(set(keys)):
                    issues.append(f"{name}: duplicate primary keys")
            except Exception as exc:
                issues.append(f"{name}: {exc}")
        if self.super["next_page"] > page_count:
            issues.append("superblock next_page exceeds physical page count")
        return issues
