# Changelog

All notable changes to PalisadeDB are documented here.

## [1.1.1] - 2026-09-26

### Added
- Release builds for macOS (Apple Silicon) and Linux (x86_64) alongside Windows, with one `SHA256SUMS.txt` per release.
- The application icon, which the Windows executable was missing.
- A screenshot of the running app in the README.

### Changed
- CI builds the macOS and Linux packages on every push.

## [1.1.0] - 2026-09-16

### Added
- Polished public release documentation and screenshot.
- Cross-platform CI checks plus Windows executable build artifact.
- Automated tagged GitHub Release workflow with SHA256 checksum.
- Issue templates and security/reporting guidance.

### Current product
- Custom .pdb database format
- Page-based storage layer
- B+ tree indexes
- SQL parsing and execution
- Transactions and WAL/recovery machinery
- Schema, page, tree, stats, and integrity inspection
