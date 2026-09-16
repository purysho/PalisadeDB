<div align="center">
  <img src="assets/icon.svg" width="140" alt="PalisadeDB icon">
  <h1>PalisadeDB</h1>
  <p><strong>A small custom local database engine with its own pager, B+ tree, SQL layer, and recovery machinery.</strong></p>
</div>

PalisadeDB is an educational but functional local database engine implemented in Python without SQLite or another database engine underneath. The desktop interface can create and open `.pdb` databases, execute supported SQL, and inspect internal storage structures.

## Features

- Custom `.pdb` database format
- Page-based storage layer
- B+ tree implementation
- SQL parsing and execution for the supported subset
- Transaction and write-ahead-log/recovery machinery
- Schema inspection
- Page and tree inspection
- Database statistics and integrity information
- Windows desktop interface

## Run from source

Requirements: Windows and Python 3.10+.

```powershell
pyw palisadedb_desktop.pyw
```

PalisadeDB uses Python's standard library and Tkinter; there are no third-party runtime dependencies.

## Build a standalone Windows executable

```powershell
powershell -ExecutionPolicy Bypass -File .\build-windows.ps1
```

Output:

```text
dist\PalisadeDB.exe
```

## Project structure

```text
PalisadeDB/
├── palisade/
│   ├── btree.py         # B+ tree implementation
│   ├── engine.py        # database engine
│   ├── pager.py         # page storage / transaction primitives
│   └── sql.py           # SQL parser
├── palisadedb_desktop.pyw
├── build-windows.ps1
├── assets/
└── .github/workflows/
```

## Why build a database engine?

PalisadeDB is meant to expose the mechanics usually hidden behind a database API: pages, indexes, transactions, parsing, persistence, and recovery. It is useful as a compact systems-programming project and as a sandbox for learning database internals.

## Current scope

PalisadeDB is not intended as a production replacement for mature database systems. Its SQL grammar and durability model are intentionally smaller and easier to inspect.

## Status

V1.1 — custom pager, B+ tree, SQL layer, database engine, recovery-related machinery, and Windows inspection UI.
