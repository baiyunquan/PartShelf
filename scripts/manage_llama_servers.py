"""Management script for local llama.cpp servers (Extractor and Reranker).

Supports:
  python scripts/manage_llama_servers.py start
  python scripts/manage_llama_servers.py stop
  python scripts/manage_llama_servers.py status
  python scripts/manage_llama_servers.py healthcheck
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.core.config import settings

STATE_FILE = BASE_DIR / "data" / "llama_servers_state.json"
LOG_DIR = BASE_DIR / "data" / "logs"


def is_service_ready(url: str, timeout: float = 1.0) -> bool:
    """Check if server endpoint responds with 200 OK."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PartShelf-HealthCheck"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def get_models_info(base_url: str) -> list:
    """Retrieve models list from OpenAI-compatible endpoint."""
    url = f"{base_url.rstrip('/')}/models"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PartShelf-HealthCheck"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("data", [])
    except Exception:
        pass
    return []


def start_server(bin_path: str, model_path: str, port: int, alias: str, log_file: Path) -> int:
    """Spawn a llama-server background process."""
    if not os.path.exists(bin_path):
        raise FileNotFoundError(f"llama-server binary not found at: {bin_path}")
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model GGUF file not found at: {model_path}")

    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_fp = open(log_file, "a", encoding="utf-8")

    cmd = [
        bin_path,
        "-m", model_path,
        "-ngl", "99",
        "--port", str(port),
        "--host", "127.0.0.1",
        "-c", "2048",
        "--alias", alias,
    ]

    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

    proc = subprocess.Popen(
        cmd,
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        creationflags=flags,
        close_fds=True,
    )
    return proc.pid


def cmd_start(args):
    """Start Extractor and Reranker servers."""
    print("Starting llama.cpp server instances...")

    servers = [
        {
            "name": "Extractor",
            "port": settings.LLAMA_EXTRACTOR_PORT,
            "base_url": settings.LLAMA_EXTRACTOR_BASE_URL,
            "model": settings.LLAMA_EXTRACTOR_MODEL,
            "alias": "electronic-qwen-extractor",
            "log": LOG_DIR / "llama_extractor.log",
        },
        {
            "name": "Reranker",
            "port": settings.LLAMA_RERANKER_PORT,
            "base_url": settings.LLAMA_RERANKER_BASE_URL,
            "model": settings.LLAMA_RERANKER_MODEL,
            "alias": "electronic-qwen-reranker",
            "log": LOG_DIR / "llama_reranker.log",
        },
    ]

    state = {}
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {}

    for s in servers:
        health_url = f"http://127.0.0.1:{s['port']}/health"
        if is_service_ready(health_url):
            print(f"[{s['name']}] Already running and healthy on port {s['port']}.")
            continue

        print(f"[{s['name']}] Launching on port {s['port']} with model {os.path.basename(s['model'])}...")
        pid = start_server(
            bin_path=settings.LLAMA_SERVER_BIN,
            model_path=s['model'],
            port=s['port'],
            alias=s['alias'],
            log_file=s['log'],
        )
        state[s['name']] = {"pid": pid, "port": s['port'], "alias": s['alias']}

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    # Wait for both servers to become ready
    print("Waiting for servers to initialize (up to 30s)...")
    start_time = time.time()
    all_ready = False

    while time.time() - start_time < 30.0:
        ready_count = 0
        for s in servers:
            health_url = f"http://127.0.0.1:{s['port']}/health"
            if is_service_ready(health_url):
                ready_count += 1
        if ready_count == len(servers):
            all_ready = True
            break
        time.sleep(1.0)

    if all_ready:
        print("All llama.cpp servers successfully started and healthy.")
        cmd_status(args)
    else:
        print("Warning: One or more servers failed to respond within 30 seconds.")
        cmd_status(args)
        sys.exit(1)


def cmd_stop(args):
    """Stop running llama.cpp servers."""
    print("Stopping llama.cpp servers...")
    pids_to_kill = set()

    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
                for entry in state.values():
                    if "pid" in entry:
                        pids_to_kill.add(entry["pid"])
        except Exception:
            pass

    for pid in pids_to_kill:
        print(f"Terminating PID {pid}...")
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
            else:
                os.kill(pid, 9)
        except Exception as e:
            print(f"Failed to kill PID {pid}: {e}")

    # Fallback cleanup for ports 8081 and 8082 if any orphan process remains
    if sys.platform == "win32":
        for port in [settings.LLAMA_EXTRACTOR_PORT, settings.LLAMA_RERANKER_PORT]:
            try:
                cmd = f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess"
                res = subprocess.run(["powershell", "-Command", cmd], capture_output=True, text=True)
                for line in res.stdout.strip().splitlines():
                    p = line.strip()
                    if p and p.isdigit() and int(p) > 0:
                        print(f"Killing process on port {port} (PID {p})...")
                        subprocess.run(["taskkill", "/F", "/PID", p], capture_output=True)
            except Exception:
                pass

    if STATE_FILE.exists():
        try:
            STATE_FILE.unlink()
        except Exception:
            pass

    print("Servers stopped.")


def cmd_status(args):
    """Display current status of servers."""
    servers = [
        {
            "name": "Extractor",
            "port": settings.LLAMA_EXTRACTOR_PORT,
            "base_url": settings.LLAMA_EXTRACTOR_BASE_URL,
            "alias": "electronic-qwen-extractor",
        },
        {
            "name": "Reranker",
            "port": settings.LLAMA_RERANKER_PORT,
            "base_url": settings.LLAMA_RERANKER_BASE_URL,
            "alias": "electronic-qwen-reranker",
        },
    ]

    all_healthy = True
    print("\n--- llama.cpp Server Status ---")
    for s in servers:
        health_url = f"http://127.0.0.1:{s['port']}/health"
        is_ok = is_service_ready(health_url)
        models = get_models_info(s["base_url"]) if is_ok else []
        model_names = [m.get("id") for m in models]

        status_str = "RUNNING (Healthy)" if is_ok else "OFFLINE"
        if not is_ok:
            all_healthy = False

        print(f"[{s['name']}] Port: {s['port']} | Status: {status_str}")
        if is_ok:
            print(f"   Base URL: {s['base_url']}")
            print(f"   Models Loaded: {model_names if model_names else s['alias']}")
    print("--------------------------------\n")
    return 0 if all_healthy else 1


def cmd_healthcheck(args):
    """Quick exit-code check for script automation."""
    for port in [settings.LLAMA_EXTRACTOR_PORT, settings.LLAMA_RERANKER_PORT]:
        if not is_service_ready(f"http://127.0.0.1:{port}/health"):
            sys.exit(1)
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="PartShelf llama.cpp server management tool.")
    subparsers = parser.add_subparsers(dest="action")

    subparsers.add_parser("start", help="Start Extractor and Reranker llama-server instances.")
    subparsers.add_parser("stop", help="Stop running llama-server instances.")
    subparsers.add_parser("status", help="Show status of llama-server instances.")
    subparsers.add_parser("healthcheck", help="Check if servers are healthy (returns exit code 0 or 1).")

    args = parser.parse_args()
    if args.action == "start":
        cmd_start(args)
    elif args.action == "stop":
        cmd_stop(args)
    elif args.action == "status":
        sys.exit(cmd_status(args))
    elif args.action == "healthcheck":
        cmd_healthcheck(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
