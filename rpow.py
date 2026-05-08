#!/usr/bin/env python3
"""
RPOW2 Miner CLI — Python orchestrator + Rust native miner.

Usage:
  python rpow.py login <email>
  python rpow.py mine [--workers N] [--count N]
  python rpow.py status
  python rpow.py activity
  python rpow.py send <email> <amount>
  python rpow.py ledger
"""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("[!] Missing 'requests'. Run: pip install requests")
    sys.exit(1)

# ─── Config ───────────────────────────────────────────────────────────────────
API_BASE = os.environ.get("RPOW_API_BASE", "https://api.rpow2.com")
DIR = Path(__file__).parent
SESSION_FILE = DIR / ".session.json"
UA = "rpow2-miner-cli/1.0"


def _find_native_bin():
    """Find the native Rust miner binary for current platform."""
    if platform.system() == "Windows":
        candidates = [
            DIR / "bin" / "rpow-miner-windows-x64.exe",
            DIR / "rpow-miner.exe",
        ]
    elif platform.system() == "Darwin":
        candidates = [
            DIR / "bin" / "rpow-miner-macos-arm64",
            DIR / "bin" / "rpow-miner-macos-x64",
            DIR / "rpow-miner",
        ]
    else:
        candidates = [
            DIR / "bin" / "rpow-miner-linux-x64",
            DIR / "rpow-miner",
        ]
    for p in candidates:
        if p.exists():
            return p
    return None


NATIVE_BIN = _find_native_bin()


# ─── Session ──────────────────────────────────────────────────────────────────
def load_session() -> dict:
    if SESSION_FILE.exists():
        try:
            return json.loads(SESSION_FILE.read_text())
        except Exception:
            pass
    return {"email": None, "cookies": {}}


def save_session(s: dict):
    SESSION_FILE.write_text(json.dumps(s, indent=2))
    try:
        os.chmod(SESSION_FILE, 0o600)
    except Exception:
        pass


def clear_session():
    SESSION_FILE.unlink(missing_ok=True)


# ─── API ──────────────────────────────────────────────────────────────────────
class ApiError(Exception):
    def __init__(self, code, message, status=0):
        super().__init__(message)
        self.code = code
        self.status = status


def _req(method, path, body=None, state=None):
    url = f"{API_BASE}{path}"
    headers = {"Accept": "application/json", "User-Agent": UA}
    if body is not None:
        headers["Content-Type"] = "application/json"
    cookies = (state or {}).get("cookies", {})
    try:
        r = requests.request(method, url, json=body, headers=headers,
                             cookies=cookies, allow_redirects=True, timeout=20)
    except requests.RequestException as e:
        raise ApiError("NETWORK", str(e))

    if state is not None and r.cookies:
        state.setdefault("cookies", {})
        for k, v in r.cookies.items():
            state["cookies"][k] = v
        save_session(state)

    if not r.ok:
        try:
            payload = r.json()
        except Exception:
            payload = {}
        code = payload.get("error", f"HTTP_{r.status_code}")
        msg = payload.get("message", r.text[:200])
        raise ApiError(code, msg, r.status_code)
    if r.status_code == 204:
        return None
    try:
        return r.json()
    except Exception:
        return r.text


def api_auth_request(email, state):
    return _req("POST", "/auth/request", {"email": email}, state)


def api_follow_magic_link(raw_url, state):
    current = raw_url.strip().strip("\"'<>\s")
    api_host = API_BASE.split("//")[1]
    for _ in range(10):
        if api_host not in current:
            from urllib.parse import urlparse, parse_qs, urljoin
            parsed = urlparse(current)
            params = {}
            params.update(parse_qs(parsed.query))
            if parsed.fragment and "?" in parsed.fragment:
                params.update(parse_qs(parsed.fragment.split("?", 1)[1]))
            token = None
            for k in ("token", "t", "code", "magic", "magic_link"):
                if k in params:
                    token = params[k][0]
                    break
            if not token:
                raise ApiError("BAD_REQUEST", "No token found in magic link")
            current = f"{API_BASE}/auth/verify?token={token}"
            continue

        cookies = state.get("cookies", {})
        r = requests.get(current, cookies=cookies, allow_redirects=False, timeout=15)
        if r.cookies:
            state.setdefault("cookies", {})
            for k, v in r.cookies.items():
                state["cookies"][k] = v
            save_session(state)
        if 300 <= r.status_code < 400:
            loc = r.headers.get("Location")
            if not loc:
                break
            from urllib.parse import urljoin
            current = urljoin(current, loc)
            if api_host not in current:
                break
            continue
        if not r.ok:
            try:
                p = r.json()
            except Exception:
                p = {}
            raise ApiError(p.get("error", f"HTTP_{r.status_code}"), p.get("message", "link rejected"))
        break


def api_me(state):
    return _req("GET", "/me", state=state)


def api_challenge(state):
    return _req("POST", "/challenge", state=state)


def api_mint(payload, state):
    return _req("POST", "/mint", body=payload, state=state)


def api_activity(state):
    return _req("GET", "/activity", state=state)


def api_ledger(state):
    return _req("GET", "/ledger", state=state)


def api_send(payload, state):
    return _req("POST", "/send", body=payload, state=state)


def api_logout(state):
    return _req("POST", "/auth/logout", state=state)


# ─── Mining ───────────────────────────────────────────────────────────────────
def solve_native(challenge, workers=0):
    """Use Rust binary for mining."""
    if not NATIVE_BIN:
        raise RuntimeError(
            f"Native miner not found! Put rpow-miner binary in bin/ folder.\n"
            f"Download from: https://github.com/comlat12/rpow-miner/releases"
        )
    args = [
        str(NATIVE_BIN),
        "--prefix", challenge["nonce_prefix"],
        "--difficulty", str(challenge["difficulty_bits"]),
        "--workers", str(workers),
    ]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "progress":
                sys.stdout.write(f"\r  hashes={msg['hashes']:,} elapsed={msg['elapsed_ms']/1000:.1f}s")
                sys.stdout.flush()
            elif msg.get("type") == "found":
                sys.stdout.write("\n")
                return {
                    "solution_nonce": str(msg["nonce"]),
                    "digest_hex": msg["digest"],
                    "trailing_zero_bits": msg["trailing_zero_bits"],
                    "hashes": msg["hashes"],
                    "elapsed_ms": msg["elapsed_ms"],
                    "backend": "native",
                }
            elif msg.get("type") == "error":
                raise RuntimeError(msg.get("message", "unknown error"))
    finally:
        proc.kill()
    raise RuntimeError("native miner exited without solution")


def _trailing_zero_bits(digest: bytes) -> int:
    count = 0
    for i in range(31, -1, -1):
        b = digest[i]
        if b == 0:
            count += 8
            continue
        return count + (b & -b).bit_length() - 1
    return count


def solve_python(challenge, workers=0):
    """Pure Python fallback (slower)."""
    import multiprocessing
    if workers <= 0:
        workers = max(1, os.cpu_count() or 2)
    prefix_hex = challenge["nonce_prefix"]
    difficulty = challenge["difficulty_bits"]
    prefix = bytes.fromhex(prefix_hex)
    full_zero_bytes = difficulty // 8
    rem_bits = difficulty - full_zero_bytes * 8
    rem_mask = (1 << rem_bits) - 1 if rem_bits else 0

    t0 = time.time()
    found_event = multiprocessing.Event()
    result_val = multiprocessing.Value("Q", 0)
    result_hash = multiprocessing.Array("B", 32)

    def worker_fn(wid):
        nonce = wid
        stride = workers
        while not found_event.is_set():
            buf = prefix + nonce.to_bytes(8, "little")
            digest = hashlib.sha256(buf).digest()
            ok = True
            for i in range(full_zero_bytes):
                if digest[31 - i] != 0:
                    ok = False
                    break
            if ok and rem_bits:
                if digest[31 - full_zero_bytes] & rem_mask:
                    ok = False
            if ok:
                tz = _trailing_zero_bits(digest)
                if tz >= difficulty:
                    if not found_event.is_set():
                        found_event.set()
                        result_val.value = nonce
                        for j in range(32):
                            result_hash[j] = digest[j]
                    return
            nonce += stride

    procs = []
    for w in range(workers):
        p = multiprocessing.Process(target=worker_fn, args=(w,))
        p.start()
        procs.append(p)

    found_event.wait()
    elapsed_ms = int((time.time() - t0) * 1000)
    for p in procs:
        p.terminate()

    digest_hex = "".join(f"{result_hash[j]:02x}" for j in range(32))
    return {
        "solution_nonce": str(result_val.value),
        "digest_hex": digest_hex,
        "trailing_zero_bits": _trailing_zero_bits(bytes(result_hash)),
        "hashes": 0,
        "elapsed_ms": elapsed_ms,
        "backend": "python",
    }


def solve_challenge(challenge, workers=0, backend="auto"):
    if backend == "native" or (backend == "auto" and NATIVE_BIN):
        return solve_native(challenge, workers)
    return solve_python(challenge, workers)


# ─── Commands ─────────────────────────────────────────────────────────────────
def cmd_login(email):
    state = load_session()
    if state.get("cookies"):
        try:
            me = api_me(state)
            if me and me.get("email"):
                print(f"[i] Already logged in as {me['email']}")
                return
        except Exception:
            pass

    print(f"[*] Requesting magic link for {email}...")
    api_auth_request(email, state)
    state["email"] = email
    save_session(state)
    print("[✓] Check inbox — link expires in 15 min.")
    link = input("\nPaste magic link: ").strip()
    if not link:
        print("[!] No link provided.")
        return
    print("[*] Verifying...")
    api_follow_magic_link(link, state)
    me = api_me(state)
    if me and me.get("email"):
        print(f"[✓] Logged in as {me['email']} | balance={me.get('balance', 0)} RPOW")
    else:
        print("[!] Verification failed.")


def cmd_mine(workers=0, count=1, backend="auto"):
    state = load_session()
    if not state.get("cookies"):
        print("[!] Not logged in. Run: python rpow.py login <email>")
        return

    try:
        me = api_me(state)
        print(f"[i] {me['email']} | balance={me['balance']} minted={me['minted']}")
    except ApiError as e:
        if e.status == 401:
            print("[!] Session expired. Re-login required.")
            return
        print(f"[!] api.me() failed: {e} — will retry during mining")

    backend_label = "Rust native" if (backend == "auto" and NATIVE_BIN) or backend == "native" else "Python"
    print(f"[*] Mining {count} token(s) | engine={backend_label} | workers={workers or 'auto'}\n")

    mined = 0
    total_hashes = 0
    session_start = time.time()

    while mined < count:
        try:
            challenge = api_challenge(state)
        except ApiError as e:
            if e.status == 401:
                print("[!] Session expired.")
                break
            print(f"[!] challenge failed: {e}")
            time.sleep(3)
            continue

        diff = challenge["difficulty_bits"]
        cid = challenge.get("challenge_id", "?")[:16]
        print(f"[>] challenge {cid} difficulty={diff} bits")

        try:
            found = solve_challenge(challenge, workers, backend)
        except Exception as e:
            print(f"[!] mining error: {e}")
            time.sleep(2)
            continue

        total_hashes += found.get("hashes", 0)
        rate = found["hashes"] / (found["elapsed_ms"] / 1000) if found["elapsed_ms"] > 0 else 0
        print(f"[✓] solved in {found['elapsed_ms']/1000:.1f}s ({found['hashes']:,} hashes, {rate:,.0f} H/s)")

        # Mint with retries
        minted_ok = False
        for attempt in range(5):
            try:
                res = api_mint({
                    "challenge_id": challenge["challenge_id"],
                    "solution_nonce": found["solution_nonce"],
                }, state)
                minted_ok = True
                break
            except ApiError as e:
                if e.code == "STALE_CHALLENGE":
                    print("[!] Challenge expired, getting new one...")
                    break
                if attempt < 4:
                    print(f"[!] mint attempt {attempt+1}/5: {e}")
                    time.sleep(3)
                    continue
                print(f"[!] mint failed: {e}")

        if not minted_ok:
            continue

        mined += 1
        token_id = res.get("token", {}).get("id", "")[:16] if isinstance(res.get("token"), dict) else ""
        uptime = time.time() - session_start
        print(f"[+] minted {token_id} | run={mined}/{count} uptime={uptime:.0f}s")

        try:
            fresh = api_me(state)
            print(f"    balance={fresh['balance']} minted={fresh['minted']}\n")
        except Exception:
            pass

    elapsed = time.time() - session_start
    print(f"[done] Mined {mined} token(s) in {elapsed:.0f}s")


def cmd_status():
    state = load_session()
    if not state.get("cookies"):
        print("[!] Not logged in.")
        return
    try:
        me = api_me(state)
        print(f"  EMAIL    : {me['email']}")
        print(f"  BALANCE  : {me['balance']} RPOW")
        print(f"  MINTED   : {me['minted']}")
        print(f"  SENT     : {me['sent']}")
        print(f"  RECEIVED : {me['received']}")
    except ApiError as e:
        print(f"[!] {e}")
        return

    try:
        ledger = api_ledger(state)
        print(f"\n  --- Public Ledger ---")
        print(f"  TOTAL MINTED      : {ledger['total_minted']}")
        print(f"  CIRCULATING       : {ledger['circulating_supply']}")
        print(f"  DIFFICULTY        : {ledger['current_difficulty_bits']} bits")
        print(f"  USERS             : {ledger['user_count']}")
    except Exception:
        pass


def cmd_activity():
    state = load_session()
    try:
        items = api_activity(state)
    except ApiError as e:
        print(f"[!] {e}")
        return
    if not items:
        print("  (no activity)")
        return
    for item in items[:20]:
        at = item["at"][:19].replace("T", " ")
        tp = item["type"].upper().ljust(8)
        sign = "-" if item["type"] == "send" else "+"
        cp = item.get("counterparty_email", "")
        print(f"  {at}  {tp}  {sign}{item['amount']}  {cp}")


def cmd_send(to_email, amount):
    state = load_session()
    import uuid
    try:
        res = api_send({
            "recipient_email": to_email,
            "amount": int(amount),
            "idempotency_key": str(uuid.uuid4()),
        }, state)
        print(f"[✓] Sent {amount} RPOW to {to_email}")
    except ApiError as e:
        print(f"[!] Send failed: {e}")


def cmd_ledger():
    try:
        ledger = api_ledger({})
        print(f"  TOTAL MINTED      : {ledger['total_minted']}")
        print(f"  TOTAL TRANSFERRED : {ledger['total_transferred']}")
        print(f"  CIRCULATING       : {ledger['circulating_supply']}")
        print(f"  DIFFICULTY        : {ledger['current_difficulty_bits']} bits")
        print(f"  USERS             : {ledger['user_count']}")
    except ApiError as e:
        print(f"[!] {e}")


def cmd_logout():
    state = load_session()
    try:
        api_logout(state)
    except Exception:
        pass
    clear_session()
    print("[✓] Logged out.")


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    print("+======================================================================+")
    print("|                   RPOW2 Miner — Rust Native CLI                      |")
    print(f"|  native={NATIVE_BIN or 'NOT FOUND'}  |")
    print("+======================================================================+")

    parser = argparse.ArgumentParser(description="RPOW2 Miner CLI")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("run", help="Login if needed, then mine")
    p_login = sub.add_parser("login", help="Login via magic link")
    p_login.add_argument("email", nargs="?")

    p_mine = sub.add_parser("mine", help="Mine tokens")
    p_mine.add_argument("--workers", type=int, default=0)
    p_mine.add_argument("--count", type=int, default=1)
    p_mine.add_argument("--backend", choices=["auto", "native", "python"], default="auto")

    sub.add_parser("status", help="Account info + ledger")
    sub.add_parser("activity", help="Recent activity")
    sub.add_parser("ledger", help="Public ledger")

    p_send = sub.add_parser("send", help="Send RPOW")
    p_send.add_argument("to_email")
    p_send.add_argument("amount", type=int)

    sub.add_parser("logout", help="Clear session")

    args = parser.parse_args()
    cmd = args.cmd or "run"

    try:
        if cmd == "login":
            email = args.email or input("Email: ").strip()
            cmd_login(email)
        elif cmd == "mine":
            cmd_mine(args.workers, args.count, args.backend)
        elif cmd == "status":
            cmd_status()
        elif cmd == "activity":
            cmd_activity()
        elif cmd == "ledger":
            cmd_ledger()
        elif cmd == "send":
            cmd_send(args.to_email, args.amount)
        elif cmd == "logout":
            cmd_logout()
        elif cmd == "run":
            state = load_session()
            if not state.get("cookies"):
                email = input("Email: ").strip()
                cmd_login(email)
            cmd_mine()
    except KeyboardInterrupt:
        print("\n[!] Stopped.")
    except ApiError as e:
        print(f"\n[!] Error [{e.code}]: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
