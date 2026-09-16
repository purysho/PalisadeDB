from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from typing import Callable, Iterable

from .pager import PAGE_SIZE, Transaction

LEAF = 0x21
INTERNAL = 0x22
LEAF_HEADER = struct.Struct("<BHI9x")       # type, count, next_leaf
INTERNAL_HEADER = struct.Struct("<BHI9x")   # type, key_count, first_child
LEAF_ENTRY_HEAD = struct.Struct("<qH")      # key, payload_len
INTERNAL_ENTRY = struct.Struct("<qI")       # separator key, right child


class BTreeError(Exception):
    pass


@dataclass
class Leaf:
    entries: list[tuple[int, dict]]
    next_leaf: int = 0


@dataclass
class Internal:
    keys: list[int]
    children: list[int]


def page_type(data: bytes) -> int:
    return data[0] if data else 0


def encode_leaf(leaf: Leaf) -> bytes:
    out = bytearray(LEAF_HEADER.pack(LEAF, len(leaf.entries), leaf.next_leaf))
    last = None
    for key, row in leaf.entries:
        if last is not None and key <= last:
            raise BTreeError("leaf keys must be strictly increasing")
        last = key
        payload = json.dumps(row, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(payload) > 65535:
            raise BTreeError("row too large")
        out += LEAF_ENTRY_HEAD.pack(key, len(payload))
        out += payload
    if len(out) > PAGE_SIZE:
        raise BTreeError("leaf page overflow")
    out += bytes(PAGE_SIZE - len(out))
    return bytes(out)


def decode_leaf(data: bytes) -> Leaf:
    if len(data) != PAGE_SIZE or page_type(data) != LEAF:
        raise BTreeError("not a leaf page")
    _, count, next_leaf = LEAF_HEADER.unpack_from(data, 0)
    off = LEAF_HEADER.size
    entries: list[tuple[int, dict]] = []
    for _ in range(count):
        if off + LEAF_ENTRY_HEAD.size > PAGE_SIZE:
            raise BTreeError("corrupt leaf entry header")
        key, length = LEAF_ENTRY_HEAD.unpack_from(data, off)
        off += LEAF_ENTRY_HEAD.size
        payload = data[off: off + length]
        if len(payload) != length:
            raise BTreeError("corrupt leaf payload")
        off += length
        try:
            row = json.loads(payload.decode("utf-8"))
        except Exception as exc:
            raise BTreeError("invalid row payload") from exc
        entries.append((key, row))
    return Leaf(entries, next_leaf)


def encode_internal(node: Internal) -> bytes:
    if len(node.children) != len(node.keys) + 1:
        raise BTreeError("internal node child/key count mismatch")
    out = bytearray(INTERNAL_HEADER.pack(INTERNAL, len(node.keys), node.children[0]))
    for key, child in zip(node.keys, node.children[1:]):
        out += INTERNAL_ENTRY.pack(key, child)
    if len(out) > PAGE_SIZE:
        raise BTreeError("internal page overflow")
    out += bytes(PAGE_SIZE - len(out))
    return bytes(out)


def decode_internal(data: bytes) -> Internal:
    if len(data) != PAGE_SIZE or page_type(data) != INTERNAL:
        raise BTreeError("not an internal page")
    _, count, first_child = INTERNAL_HEADER.unpack_from(data, 0)
    keys: list[int] = []
    children = [first_child]
    off = INTERNAL_HEADER.size
    for _ in range(count):
        key, child = INTERNAL_ENTRY.unpack_from(data, off)
        off += INTERNAL_ENTRY.size
        keys.append(key)
        children.append(child)
    return Internal(keys, children)


class BPlusTree:
    def __init__(self, tx: Transaction, allocate_page: Callable[[], int]):
        self.tx = tx
        self.allocate_page = allocate_page

    def make_empty(self) -> int:
        page = self.allocate_page()
        self.tx.write_page(page, encode_leaf(Leaf([])))
        return page

    def _find_leaf(self, root: int, key: int) -> tuple[int, list[int]]:
        page = root
        path: list[int] = []
        while True:
            data = self.tx.read_page(page)
            typ = page_type(data)
            if typ == LEAF:
                return page, path
            if typ != INTERNAL:
                raise BTreeError(f"unexpected page type {typ:#x} at page {page}")
            node = decode_internal(data)
            path.append(page)
            child = node.children[0]
            for sep, right in zip(node.keys, node.children[1:]):
                if key < sep:
                    break
                child = right
            page = child

    def get(self, root: int, key: int) -> dict | None:
        leaf_page, _ = self._find_leaf(root, key)
        leaf = decode_leaf(self.tx.read_page(leaf_page))
        lo, hi = 0, len(leaf.entries)
        while lo < hi:
            mid = (lo + hi) // 2
            if leaf.entries[mid][0] < key:
                lo = mid + 1
            else:
                hi = mid
        if lo < len(leaf.entries) and leaf.entries[lo][0] == key:
            return leaf.entries[lo][1]
        return None

    def _leaf_encoded_len(self, entries: list[tuple[int, dict]]) -> int:
        total = LEAF_HEADER.size
        for _, row in entries:
            payload = json.dumps(row, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            total += LEAF_ENTRY_HEAD.size + len(payload)
        return total

    def _split_leaf_entries(self, entries: list[tuple[int, dict]]) -> int:
        total = self._leaf_encoded_len(entries) - LEAF_HEADER.size
        target = total / 2
        used = 0
        for i, (_, row) in enumerate(entries[:-1], start=1):
            payload = json.dumps(row, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            used += LEAF_ENTRY_HEAD.size + len(payload)
            if used >= target:
                return i
        return max(1, len(entries) // 2)

    def insert(self, root: int, key: int, row: dict) -> int:
        leaf_page, path = self._find_leaf(root, key)
        leaf = decode_leaf(self.tx.read_page(leaf_page))
        if any(k == key for k, _ in leaf.entries):
            raise BTreeError(f"duplicate primary key {key}")
        leaf.entries.append((key, row))
        leaf.entries.sort(key=lambda kv: kv[0])

        try:
            self.tx.write_page(leaf_page, encode_leaf(leaf))
            return root
        except BTreeError as exc:
            if "overflow" not in str(exc):
                raise

        split_at = self._split_leaf_entries(leaf.entries)
        left_entries = leaf.entries[:split_at]
        right_entries = leaf.entries[split_at:]
        if not left_entries or not right_entries:
            raise BTreeError("row is too large to split into B+ tree leaves")
        right_page = self.allocate_page()
        right = Leaf(right_entries, leaf.next_leaf)
        left = Leaf(left_entries, right_page)
        self.tx.write_page(leaf_page, encode_leaf(left))
        self.tx.write_page(right_page, encode_leaf(right))
        separator = right_entries[0][0]
        return self._insert_parent(root, path, leaf_page, separator, right_page)

    def _insert_parent(self, root: int, path: list[int], left_page: int, sep: int, right_page: int) -> int:
        if not path:
            new_root = self.allocate_page()
            self.tx.write_page(new_root, encode_internal(Internal([sep], [left_page, right_page])))
            return new_root

        parent_page = path.pop()
        parent = decode_internal(self.tx.read_page(parent_page))
        try:
            child_index = parent.children.index(left_page)
        except ValueError as exc:
            raise BTreeError("parent does not reference split child") from exc
        parent.keys.insert(child_index, sep)
        parent.children.insert(child_index + 1, right_page)

        try:
            self.tx.write_page(parent_page, encode_internal(parent))
            return root
        except BTreeError as exc:
            if "overflow" not in str(exc):
                raise

        mid = len(parent.keys) // 2
        promote = parent.keys[mid]
        left_node = Internal(parent.keys[:mid], parent.children[:mid + 1])
        right_node = Internal(parent.keys[mid + 1:], parent.children[mid + 1:])
        new_right = self.allocate_page()
        self.tx.write_page(parent_page, encode_internal(left_node))
        self.tx.write_page(new_right, encode_internal(right_node))
        return self._insert_parent(root, path, parent_page, promote, new_right)

    def delete(self, root: int, key: int) -> bool:
        leaf_page, _ = self._find_leaf(root, key)
        leaf = decode_leaf(self.tx.read_page(leaf_page))
        before = len(leaf.entries)
        leaf.entries = [(k, row) for k, row in leaf.entries if k != key]
        if len(leaf.entries) == before:
            return False
        self.tx.write_page(leaf_page, encode_leaf(leaf))
        return True

    def iter_rows(self, root: int) -> Iterable[tuple[int, dict]]:
        page = root
        while page_type(self.tx.read_page(page)) == INTERNAL:
            page = decode_internal(self.tx.read_page(page)).children[0]
        seen: set[int] = set()
        while page:
            if page in seen:
                raise BTreeError("cycle detected in leaf chain")
            seen.add(page)
            leaf = decode_leaf(self.tx.read_page(page))
            yield from leaf.entries
            page = leaf.next_leaf

    def describe(self, root: int) -> dict:
        levels: list[list[dict]] = []
        frontier = [root]
        seen: set[int] = set()
        while frontier:
            level: list[dict] = []
            nxt: list[int] = []
            for page in frontier:
                if page in seen:
                    raise BTreeError("cycle detected in tree")
                seen.add(page)
                data = self.tx.read_page(page)
                if page_type(data) == LEAF:
                    leaf = decode_leaf(data)
                    level.append({"page": page, "type": "leaf", "keys": [k for k, _ in leaf.entries], "next": leaf.next_leaf})
                elif page_type(data) == INTERNAL:
                    node = decode_internal(data)
                    level.append({"page": page, "type": "internal", "keys": node.keys, "children": node.children})
                    nxt.extend(node.children)
                else:
                    raise BTreeError(f"invalid tree page {page}")
            levels.append(level)
            frontier = nxt
        return {"root": root, "height": len(levels), "levels": levels, "pages": len(seen)}
