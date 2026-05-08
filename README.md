# RPOW2 Miner — Rust Native CLI

Fast RPOW2 miner with **Rust native SHA-256** engine + **Python CLI** orchestrator.

## ⚡ Quick Start (Windows)

```cmd
git clone https://github.com/comlat12/rpow-miner.git
cd rpow-miner
pip install requests
python rpow.py login your@email.com
python rpow.py mine --count 10
```

## ⚡ Quick Start (Linux/macOS)

```bash
git clone https://github.com/comlat12/rpow-miner.git
cd rpow-miner
pip3 install requests
python3 rpow.py login your@email.com
python3 rpow.py mine --count 10
```

## Requirements

- **Python 3.8+**
- **No Rust/C compiler needed** — pre-built binaries included in `bin/`

## Download Pre-built Binaries

```cmd
git clone https://github.com/comlat12/rpow-miner.git
cd rpow-miner
pip install requests
```

That's it! Binary for your platform is auto-detected from `bin/`.

## Commands

```bash
python rpow.py login <email>          # Login via magic link
python rpow.py mine                   # Mine 1 token
python rpow.py mine --count 10        # Mine 10 tokens
python rpow.py mine --workers 8       # Use 8 CPU threads
python rpow.py mine --backend python  # Use Python fallback (slower)
python rpow.py status                 # Account + ledger
python rpow.py activity               # Recent activity
python rpow.py send <email> <amount>  # Send RPOW
python rpow.py ledger                 # Public ledger
python rpow.py logout                 # Clear session
```

## Build from Source

If you want to compile the Rust miner yourself:

```bash
# Install Rust: https://rustup.rs
cd rpow-miner
cargo build --release
cp target/release/rpow-miner bin/rpow-miner
```

Cross-compile for Windows from Linux:

```bash
rustup target add x86_64-pc-windows-gnu
sudo apt install mingw-w64
cargo build --release --target x86_64-pc-windows-gnu
cp target/x86_64-pc-windows-gnu/release/rpow-miner.exe bin/rpow-miner-windows-x64.exe
```

## Architecture

```
rpow.py                     ← Python CLI (API + orchestration)
Cargo.toml + src/main.rs    ← Rust native SHA-256 miner
bin/
  rpow-miner-linux-x64      ← Pre-built Linux binary
  rpow-miner-windows-x64.exe ← Pre-built Windows binary
  rpow-miner-macos-arm64    ← Pre-built macOS ARM binary
.session.json               ← Login session (auto-created, gitignored)
```

## Mining Performance

| Engine | Speed | Notes |
|--------|-------|-------|
| Rust native | ⚡ ~20-50 MH/s | Pre-built binary, recommended |
| Python fallback | 🐌 ~0.5-2 MH/s | Pure Python, no binary needed |

## Auto-Build via GitHub Actions

Push a tag to trigger automatic build + release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

This builds native binaries for Linux, Windows, macOS and creates a GitHub Release.

## License

MIT
