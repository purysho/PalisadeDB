from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

PAGE_SIZE = 4096
WAL_MAGIC = b"PLSWAL1\0"
WAL_COMMIT = b"COMMIT!!"
WAL_HEADER = struct.Struct("<8sQI")  # magic, txid, frame_count
WAL_FRAME = struct.Struct("<I")      # page number
WAL_TRAILER = struct.Struct("<8sI") # marker, crc32


class PagerError(Exception):
    pass


class SimulatedCrash(RuntimeError):
    """Raised after a durable WAL commit but before database pages are applied."""


@dataclass
class RecoveryResult:
    recovered: bool
    txid: int | None = None
    pages_replayed: int = 0
    discarded_wal: bool = False


class Transaction:
    def __init__(self, pager: "Pager", txid: int):
        self.pager = pager
        self.txid = txid
        self.staged: Dict[int, bytes] = {}
        self.closed = False

    def read_page(self, page_no: int) -> bytes:
        if page_no in self.staged:
            return self.staged[page_no]
        return self.pager.read_page(page_no)

    def write_page(self, page_no: int, data: bytes) -> None:
        if self.closed:
            raise PagerError("transaction already closed")
        if len(data) != PAGE_SIZE:
            raise PagerError(f"page must be exactly {PAGE_SIZE} bytes")
        self.staged[page_no] = data

    def commit(self, *, crash_after_wal: bool = False) -> None:
        if self.closed:
            raise PagerError("transaction already closed")
        self.pager.commit_pages(self.txid, self.staged, crash_after_wal=crash_after_wal)
        self.closed = True

    def rollback(self) -> None:
        self.staged.clear()
        self.closed = True


class Pager:
    """Fixed-size page IO plus a redo-only write-ahead log.

    A commit writes complete page images to <db>.wal, fsyncs the WAL, writes a
    checksum-protected COMMIT trailer, fsyncs again, then copies the pages into
    the main database and fsyncs it. Recovery replays only WALs with a valid
    trailer and checksum; incomplete WALs are discarded.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.wal_path = Path(str(self.path) + ".wal")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()
        self.recovery = self.recover()

    def begin(self, txid: int) -> Transaction:
        return Transaction(self, txid)

    def page_count(self) -> int:
        size = self.path.stat().st_size
        if size % PAGE_SIZE:
            raise PagerError("database file length is not page-aligned")
        return size // PAGE_SIZE

    def read_page(self, page_no: int) -> bytes:
        if page_no < 0:
            raise PagerError("negative page number")
        with self.path.open("rb") as f:
            f.seek(page_no * PAGE_SIZE)
            data = f.read(PAGE_SIZE)
        if len(data) != PAGE_SIZE:
            raise PagerError(f"page {page_no} does not exist")
        return data

    def _apply_pages(self, pages: Dict[int, bytes]) -> None:
        mode = "r+b" if self.path.exists() else "w+b"
        with self.path.open(mode) as f:
            for page_no, data in sorted(pages.items()):
                f.seek(page_no * PAGE_SIZE)
                f.write(data)
            f.flush()
            os.fsync(f.fileno())

    def commit_pages(self, txid: int, pages: Dict[int, bytes], *, crash_after_wal: bool = False) -> None:
        if not pages:
            return
        body = bytearray(WAL_HEADER.pack(WAL_MAGIC, txid, len(pages)))
        for page_no, data in sorted(pages.items()):
            if len(data) != PAGE_SIZE:
                raise PagerError("invalid staged page size")
            body += WAL_FRAME.pack(page_no)
            body += data
        crc = zlib.crc32(body) & 0xFFFFFFFF

        with self.wal_path.open("wb") as wf:
            wf.write(body)
            wf.flush()
            os.fsync(wf.fileno())
            wf.write(WAL_TRAILER.pack(WAL_COMMIT, crc))
            wf.flush()
            os.fsync(wf.fileno())

        if crash_after_wal:
            raise SimulatedCrash(
                "simulated crash after durable WAL commit; database pages were not applied"
            )

        self._apply_pages(pages)
        self._clear_wal()

    def _clear_wal(self) -> None:
        if self.wal_path.exists():
            with self.wal_path.open("wb") as wf:
                wf.truncate(0)
                wf.flush()
                os.fsync(wf.fileno())

    def wal_status(self) -> dict:
        if not self.wal_path.exists():
            return {"exists": False, "bytes": 0, "committed": False}
        data = self.wal_path.read_bytes()
        status = {"exists": True, "bytes": len(data), "committed": False}
        try:
            parsed = self._parse_wal(data)
            status.update({"committed": True, "txid": parsed[0], "frames": len(parsed[1])})
        except PagerError:
            pass
        return status

    def _parse_wal(self, data: bytes) -> tuple[int, Dict[int, bytes]]:
        min_len = WAL_HEADER.size + WAL_TRAILER.size
        if len(data) < min_len:
            raise PagerError("incomplete WAL")
        magic, txid, frame_count = WAL_HEADER.unpack_from(data, 0)
        if magic != WAL_MAGIC:
            raise PagerError("invalid WAL magic")
        expected = WAL_HEADER.size + frame_count * (WAL_FRAME.size + PAGE_SIZE) + WAL_TRAILER.size
        if len(data) != expected:
            raise PagerError("incomplete or oversized WAL")

        trailer_off = expected - WAL_TRAILER.size
        marker, expected_crc = WAL_TRAILER.unpack_from(data, trailer_off)
        if marker != WAL_COMMIT:
            raise PagerError("WAL has no commit marker")
        actual_crc = zlib.crc32(data[:trailer_off]) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise PagerError("WAL checksum mismatch")

        pages: Dict[int, bytes] = {}
        off = WAL_HEADER.size
        for _ in range(frame_count):
            (page_no,) = WAL_FRAME.unpack_from(data, off)
            off += WAL_FRAME.size
            pages[page_no] = data[off: off + PAGE_SIZE]
            off += PAGE_SIZE
        return txid, pages

    def recover(self) -> RecoveryResult:
        if not self.wal_path.exists() or self.wal_path.stat().st_size == 0:
            return RecoveryResult(False)
        data = self.wal_path.read_bytes()
        try:
            txid, pages = self._parse_wal(data)
        except PagerError:
            self._clear_wal()
            return RecoveryResult(False, discarded_wal=True)

        self._apply_pages(pages)
        self._clear_wal()
        return RecoveryResult(True, txid=txid, pages_replayed=len(pages))
