<div align="center">
  <img src="assets/icon.png" width="132" alt="PalisadeDB icon">
  <h1>PalisadeDB</h1>
  <p><strong>A compact custom local database engine with its own pager, B+ tree, SQL layer, and recovery machinery.</strong></p>
  <p>
    <a href="https://github.com/purysho/PalisadeDB/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/purysho/PalisadeDB/actions/workflows/ci.yml/badge.svg"></a>
    <a href="https://github.com/purysho/PalisadeDB/releases"><img alt="Releases" src="https://img.shields.io/github/v/release/purysho/PalisadeDB?display_name=tag&sort=semver"></a>
    <a href="LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-202832.svg"></a>
    <a href="#download"><img alt="Status: beta" src="https://img.shields.io/badge/status-beta-C9A44C.svg"></a>
  </p>
  <p><strong>Download:</strong> <a href="https://github.com/purysho/PalisadeDB/releases/latest/download/PalisadeDB-Windows-x64.exe">Windows</a> · <a href="https://github.com/purysho/PalisadeDB/releases/latest/download/PalisadeDB-macOS-arm64.zip">macOS</a> · <a href="https://github.com/purysho/PalisadeDB/releases/latest/download/PalisadeDB-Linux-x86_64.tar.gz">Linux</a> · <a href="#run-from-source">Run from source</a> · <a href="https://github.com/purysho/PalisadeDB/issues">Report an issue</a></p>
</div>

![PalisadeDB running a query against a sample library database](docs/screenshot.png)

## What it does

- Custom .pdb database format
- Page-based storage layer
- B+ tree indexes
- SQL parsing and execution
- Transactions and WAL/recovery machinery
- Schema, page, tree, stats, and integrity inspection

## Download

| Platform | File |
|---|---|
| Windows 10/11 (x64) | [PalisadeDB-Windows-x64.exe](https://github.com/purysho/PalisadeDB/releases/latest/download/PalisadeDB-Windows-x64.exe) — portable, no installer |
| macOS (Apple Silicon) | [PalisadeDB-macOS-arm64.zip](https://github.com/purysho/PalisadeDB/releases/latest/download/PalisadeDB-macOS-arm64.zip) — unzip and move to Applications |
| Linux (x86_64) | [PalisadeDB-Linux-x86_64.tar.gz](https://github.com/purysho/PalisadeDB/releases/latest/download/PalisadeDB-Linux-x86_64.tar.gz) — extract and run `./PalisadeDB` |

Each [release](https://github.com/purysho/PalisadeDB/releases) is built from the tagged source by GitHub Actions and carries a `SHA256SUMS.txt`. The builds are not yet code-signed, so on first launch Windows SmartScreen may ask you to confirm ("More info" → "Run anyway"), and macOS may need you to Control-click the app and choose **Open**.

**Status: beta.** PalisadeDB does what this README describes and is covered by CI on Windows, macOS and Linux, but it is young: expect rough edges, and please [report them](https://github.com/purysho/PalisadeDB/issues).

## Run from source

Requirements: Python 3.10+ with Tk support.

```powershell
pyw palisadedb_desktop.pyw
```

The application uses Python's standard library at runtime.

## Build a standalone Windows executable

```powershell
powershell -ExecutionPolicy Bypass -File .\build-windows.ps1
```

Output:

```text
dist\PalisadeDB.exe
```

## Privacy

PalisadeDB stores databases in local files and does not require a server, account, or network service.

## Scope

PalisadeDB is an educational but functional engine, not a production replacement for mature database systems. Its SQL grammar and durability model are intentionally compact and inspectable.

## Release process

- Every push runs tests/compile checks and builds a Windows executable artifact.
- Tags matching `v*` build the executable again, compute SHA256, and publish both files to GitHub Releases.
- See [CHANGELOG.md](CHANGELOG.md) for release history.

## License

MIT
