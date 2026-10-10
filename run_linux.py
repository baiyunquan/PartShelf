#!/usr/bin/env python3
"""Linux startup launcher and orchestrator for PartShelf.

Orchestrates the complete local hardware-accelerated AI retrieval pipeline on Linux:
1. PaddleOCR-VL Multimodal Vision Backend (port 8083, llama-server with PaddleOCR-VL-1.5.gguf + mmproj)
2. PaddleOCR-VL Adapter Translation Layer (port 8010, paddleocr_vl.server)
3. Stage 1 Extractor (port 8081, llama-server with unquantized BF16 ElectronicQwen model)
4. Stage 2 Reranker (port 8082, llama-server with unquantized BF16 ElectronicQwen model)
5. ADB reverse port forwarding for connected Android mobile devices (port 8000)
6. PartShelf web application (port 8000)

Usage:
    python run_linux.py               # Start all services with default BF16 models
    python run_linux.py --models q8   # Use Q8_0 quantized models
    python run_linux.py --models q4   # Use Q4_K_M quantized models
    python run_linux.py --no-web      # Start only AI/OCR backends in background
    python run_linux.py --status      # Check health of all services
    python run_linux.py --stop        # Stop all running services
    python run_linux.py --restart     # Force restart all services
"""

import argparse
import atexit
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Path configurations
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent if (SCRIPT_DIR.parent / "PartShelf").is_dir() else SCRIPT_DIR
PARTSHELF_DIR = REPO_ROOT / "PartShelf" if (REPO_ROOT / "PartShelf").is_dir() else REPO_ROOT
ELECTRONIC_QWEN_DIR = REPO_ROOT / "ElectronicQwen"
DELIVERABLES_DIR = ELECTRONIC_QWEN_DIR / "deliverables" / "v1"

LOG_DIR = PARTSHELF_DIR / "data" / "logs"
STATE_FILE = PARTSHELF_DIR / "data" / "run_linux_state.json"

DEFAULT_OCR_DIR = PARTSHELF_DIR / "data" / "models" / "paddleocr_vl"
DEFAULT_OCR_MODEL = DEFAULT_OCR_DIR / "PaddleOCR-VL-1.5.gguf"
DEFAULT_OCR_MMPROJ = DEFAULT_OCR_DIR / "PaddleOCR-VL-1.5-mmproj.gguf"

MODEL_PRESETS = {
    "bf16": {
        "extractor": "ElectronicQwen-Extractor-v1-BF16.gguf",
        "reranker": "ElectronicQwen-Reranker-v1-BF16.gguf",
        "label": "Unquantized BF16 (Full Precision, Trained Model)",
    },
    "q8": {
        "extractor": "ElectronicQwen-Extractor-v1-Q8_0.gguf",
        "reranker": "ElectronicQwen-Reranker-v1-Q8_0.gguf",
        "label": "Q8_0 8-bit Quantized",
    },
    "q4": {
        "extractor": "ElectronicQwen-Extractor-v1-Q4_K_M.gguf",
        "reranker": "ElectronicQwen-Reranker-v1-Q4_K_M.gguf",
        "label": "Q4_K_M 4-bit Quantized",
    },
}

SPAWNED_PIDS = []


def find_llama_server_bin() -> str:
    """Find native llama-server binary on Linux (CUDA prioritized, CPU fallback)."""
    env_bin = os.getenv("LLAMA_SERVER_BIN")
    if env_bin and os.path.isfile(env_bin) and os.access(env_bin, os.X_OK):
        return env_bin

    # Search known build locations
    candidates = [
        REPO_ROOT.parent / "llama.cpp" / "build-linux-cuda" / "bin" / "llama-server",
        REPO_ROOT.parent / "llama.cpp" / "build-linux" / "bin" / "llama-server",
        REPO_ROOT.parent / "llama.cpp" / "build" / "bin" / "llama-server",
        Path("/mnt/software/workspace/llama.cpp/build-linux-cuda/bin/llama-server"),
        Path("/mnt/software/workspace/llama.cpp/build-linux/bin/llama-server"),
    ]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return str(c.resolve())

    which_bin = shutil.which("llama-server")
    if which_bin:
        return which_bin

    return str(candidates[0])


def find_python_bin() -> str:
    """Find the best Python virtual environment interpreter for PartShelf."""
    candidates = [
        PARTSHELF_DIR / ".venv" / "bin" / "python",
        ELECTRONIC_QWEN_DIR / ".venv-linux" / "bin" / "python",
    ]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)  # Preserve virtualenv binary path (do not call resolve())
    return sys.executable


def is_port_in_use(port: int) -> bool:
    """Check if TCP port is actively listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def is_service_ready(url: str, timeout: float = 1.0) -> bool:
    """Send HTTP GET to check if endpoint returns HTTP 200."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PartShelf-Linux-Launcher"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def get_json_response(url: str, timeout: float = 1.5) -> dict | None:
    """Send HTTP GET and return parsed JSON."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PartShelf-Linux-Launcher"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        pass
    return None


def kill_process_by_pid(pid: int):
    """Force terminate process and its process group by PID on Linux."""
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass

    time.sleep(0.1)

    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGKILL)
    except Exception:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass


def kill_processes_by_port(port: int):
    """Find and terminate processes listening on a specific TCP port on Linux."""
    # 1. Try fuser
    if shutil.which("fuser"):
        try:
            subprocess.run(["fuser", "-k", "-9", f"{port}/tcp"], capture_output=True)
        except Exception:
            pass

    # 2. Try lsof
    if shutil.which("lsof"):
        try:
            res = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True)
            for line in res.stdout.strip().splitlines():
                pid_str = line.strip()
                if pid_str.isdigit():
                    pid = int(pid_str)
                    print(f"[CLEANUP] Terminating process PID {pid} listening on port {port}...")
                    kill_process_by_pid(pid)
        except Exception as exc:
            print(f"[WARN] Failed to inspect port {port} with lsof: {exc}")


def spawn_process(cmd: list[str], log_path: Path, cwd: Path | None = None, env: dict | None = None) -> subprocess.Popen:
    """Spawn detached Linux background process in new process group with logging."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "a", encoding="utf-8")

    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # setsid to create an isolated process group
        close_fds=True,
    )
    SPAWNED_PIDS.append(proc.pid)
    return proc


def record_state(state: dict):
    """Save runner state to disk."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def load_state() -> dict:
    """Load runner state from disk."""
    if not STATE_FILE.is_file():
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def cleanup_on_exit():
    """Cleanup handler when launcher terminates."""
    if not SPAWNED_PIDS:
        return
    print("\n[SHUTDOWN] Stopping spawned background services...")
    for pid in SPAWNED_PIDS:
        kill_process_by_pid(pid)


def try_configure_adb_reverse(port: int = 8000):
    """Automatically configure ADB reverse port forwarding for attached Android devices."""
    if not shutil.which("adb"):
        return
    try:
        res = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=3.0)
        lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
        devices = []
        for line in lines[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        if devices:
            print(f"[ADB] Found {len(devices)} connected Android device(s): {', '.join(devices)}")
            rev_res = subprocess.run(
                ["adb", "reverse", f"tcp:{port}", f"tcp:{port}"],
                capture_output=True,
                text=True,
                timeout=3.0,
            )
            if rev_res.returncode == 0:
                print(f"[ADB] Configured 'adb reverse tcp:{port} tcp:{port}' successfully.")
                print(f"[ADB] Mobile phones can access camera scan at: http://localhost:{port}/scan-import")
            else:
                print(f"[ADB] Failed to set reverse port: {rev_res.stderr.strip()}")
    except Exception as exc:
        print(f"[ADB] Skipped ADB reverse setup: {exc}")


def cmd_status():
    """Check and display status table for all services."""
    services = [
        ("PartShelf Web App", 8000, "http://127.0.0.1:8000/"),
        ("PaddleOCR-VL Adapter", 8010, "http://127.0.0.1:8010/health"),
        ("PaddleOCR-VL Backend", 8083, "http://127.0.0.1:8083/health"),
        ("llama Extractor", 8081, "http://127.0.0.1:8081/health"),
        ("llama Reranker", 8082, "http://127.0.0.1:8082/health"),
    ]

    print("\n==================================================")
    print("           PartShelf Linux Service Status         ")
    print("==================================================")
    all_ok = True
    for name, port, health_url in services:
        listening = is_port_in_use(port)
        ready = is_service_ready(health_url) if listening else False
        status_text = "READY" if ready else ("PORT OPEN (Unhealthy)" if listening else "OFFLINE")
        if not ready:
            all_ok = False
        print(f"  * {name:<21} [Port {port:>4}]: {status_text}")
        if ready and port in (8081, 8082, 8083):
            models_info = get_json_response(f"http://127.0.0.1:{port}/v1/models")
            if models_info and "data" in models_info:
                loaded = [m.get("id") for m in models_info["data"]]
                print(f"      Loaded: {', '.join(loaded)}")
        elif ready and port == 8010:
            info = get_json_response(health_url)
            if info and "device" in info:
                print(f"      Backend: {info.get('device')}")
    print("==================================================\n")
    return all_ok


def cmd_stop():
    """Stop all running services on ports 8000, 8010, 8081, 8082, 8083."""
    print("[STOP] Stopping all PartShelf background services...")
    state = load_state()
    for name, data in state.items():
        if isinstance(data, dict) and "pid" in data:
            print(f"[STOP] Terminating saved {name} (PID {data['pid']})...")
            kill_process_by_pid(data["pid"])

    for port in [8000, 8010, 8081, 8082, 8083]:
        kill_processes_by_port(port)

    if STATE_FILE.is_file():
        try:
            STATE_FILE.unlink()
        except Exception:
            pass
    print("[STOP] All services stopped.")


def main():
    parser = argparse.ArgumentParser(
        description="Unified Linux launcher for PartShelf, PaddleOCR-VL, and llama.cpp backends.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--models",
        choices=["bf16", "q8", "q4"],
        default="bf16",
        help="Model weight precision to use for Extractor and Reranker (default: unquantized bf16).",
    )
    parser.add_argument(
        "--extractor-model",
        type=str,
        default=None,
        help="Path to custom GGUF model for ElectronicQwen Extractor.",
    )
    parser.add_argument(
        "--reranker-model",
        type=str,
        default=None,
        help="Path to custom GGUF model for ElectronicQwen Reranker.",
    )
    parser.add_argument(
        "--ocr-model",
        type=str,
        default=None,
        help="Path to custom PaddleOCR-VL-1.5 GGUF model.",
    )
    parser.add_argument(
        "--ocr-mmproj",
        type=str,
        default=None,
        help="Path to custom PaddleOCR-VL-1.5 mmproj GGUF model.",
    )
    parser.add_argument(
        "--llama-bin",
        type=str,
        default=None,
        help="Path to llama-server executable (defaults to CUDA/CPU auto-discovery).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="PartShelf web server port.",
    )
    parser.add_argument(
        "--no-web",
        action="store_true",
        help="Start only AI & OCR backends without launching the web server.",
    )
    parser.add_argument(
        "--no-ocr",
        action="store_true",
        help="Skip starting PaddleOCR-VL backend and adapter.",
    )
    parser.add_argument(
        "--no-llama",
        action="store_true",
        help="Skip starting llama.cpp Extractor and Reranker server instances.",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop all running services and exit.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show status of all services and exit.",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Force terminate existing instances before starting.",
    )

    args = parser.parse_args()

    if args.stop:
        cmd_stop()
        return

    if args.status:
        cmd_status()
        return

    if args.restart:
        cmd_stop()
        time.sleep(1.0)

    preset = MODEL_PRESETS[args.models]
    extractor_model = args.extractor_model or str(DELIVERABLES_DIR / preset["extractor"])
    reranker_model = args.reranker_model or str(DELIVERABLES_DIR / preset["reranker"])
    ocr_model = args.ocr_model or str(DEFAULT_OCR_MODEL)
    ocr_mmproj = args.ocr_mmproj or str(DEFAULT_OCR_MMPROJ)

    llama_bin = args.llama_bin or find_llama_server_bin()
    python_bin = find_python_bin()

    print("==================================================")
    print("       PartShelf Linux Integrated Launcher        ")
    print("==================================================")
    print(f"Platform:            Linux ({os.uname().machine})")
    print(f"Model Preset:        {preset['label']}")
    print(f"Extractor Model:     {os.path.basename(extractor_model)}")
    print(f"Reranker Model:      {os.path.basename(reranker_model)}")
    print(f"PaddleOCR-VL Model:  {os.path.basename(ocr_model)}")
    print(f"PaddleOCR-VL mmproj: {os.path.basename(ocr_mmproj)}")
    print(f"llama-server Binary: {llama_bin}")
    print(f"Python Interpreter:  {python_bin}")
    print("==================================================")

    # Validate paths
    if not args.no_llama:
        if not os.path.exists(llama_bin) or not os.access(llama_bin, os.X_OK):
            print(f"[ERROR] Executable llama-server binary not found at: {llama_bin}")
            sys.exit(1)
        if not os.path.exists(extractor_model):
            print(f"[ERROR] Extractor model file not found at: {extractor_model}")
            sys.exit(1)
        if not os.path.exists(reranker_model):
            print(f"[ERROR] Reranker model file not found at: {reranker_model}")
            sys.exit(1)

    if not args.no_ocr:
        if not os.path.exists(llama_bin) or not os.access(llama_bin, os.X_OK):
            print(f"[ERROR] Executable llama-server binary not found at: {llama_bin}")
            sys.exit(1)
        if not os.path.exists(ocr_model):
            print(f"[ERROR] PaddleOCR-VL model file not found at: {ocr_model}")
            sys.exit(1)
        if not os.path.exists(ocr_mmproj):
            print(f"[ERROR] PaddleOCR-VL mmproj file not found at: {ocr_mmproj}")
            sys.exit(1)

    state = {}

    atexit.register(cleanup_on_exit)
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

    # 1. Start PaddleOCR-VL Backend (llama-server on port 8083) and Adapter (port 8010)
    if not args.no_ocr:
        llama_ocr_port = 8083
        llama_ocr_health = f"http://127.0.0.1:{llama_ocr_port}/health"
        adapter_port = 8010
        adapter_health = f"http://127.0.0.1:{adapter_port}/health"

        # 1a. Start llama-server on port 8083
        if is_service_ready(llama_ocr_health):
            print(f"[PaddleOCR-VL Backend] Port {llama_ocr_port} is already running and healthy.")
        else:
            if is_port_in_use(llama_ocr_port):
                print(f"[PaddleOCR-VL Backend] Port {llama_ocr_port} is busy, recycling...")
                kill_processes_by_port(llama_ocr_port)
                time.sleep(0.5)

            llama_ocr_cmd = [
                llama_bin,
                "-m",
                ocr_model,
                "--mmproj",
                ocr_mmproj,
                "-ngl",
                "99",
                "--port",
                str(llama_ocr_port),
                "--host",
                "127.0.0.1",
                "-c",
                "4096",
                "--alias",
                "paddleocr-vl",
                "--temp",
                "0",
            ]
            print(f"[PaddleOCR-VL Backend] Starting llama-server on port {llama_ocr_port} with {os.path.basename(ocr_model)}...")
            proc_llama_ocr = spawn_process(llama_ocr_cmd, LOG_DIR / "paddleocr_vl_backend.log")
            state["PaddleOCR-VL-Backend"] = {"pid": proc_llama_ocr.pid, "port": llama_ocr_port}

        # 1b. Start Translation Layer on port 8010
        if is_service_ready(adapter_health):
            print(f"[PaddleOCR-VL Adapter] Port {adapter_port} is already running and healthy.")
        else:
            if is_port_in_use(adapter_port):
                print(f"[PaddleOCR-VL Adapter] Port {adapter_port} is busy, recycling...")
                kill_processes_by_port(adapter_port)
                time.sleep(0.5)

            adapter_cmd = [
                python_bin,
                "-m",
                "paddleocr_vl.server",
                "--port",
                str(adapter_port),
                "--host",
                "127.0.0.1",
                "--llama-url",
                f"http://127.0.0.1:{llama_ocr_port}/v1",
            ]
            print(f"[PaddleOCR-VL Adapter] Starting Translation Layer on port {adapter_port} pointing to port {llama_ocr_port}...")
            proc_adapter = spawn_process(adapter_cmd, LOG_DIR / "paddleocr_vl_adapter.log", cwd=PARTSHELF_DIR)
            state["PaddleOCR-VL-Adapter"] = {"pid": proc_adapter.pid, "port": adapter_port}

    # 2. Start llama Extractor (port 8081)
    if not args.no_llama:
        ext_port = 8081
        ext_health_url = f"http://127.0.0.1:{ext_port}/health"
        if is_service_ready(ext_health_url):
            print(f"[Extractor] Port {ext_port} is already running and healthy.")
        else:
            if is_port_in_use(ext_port):
                print(f"[Extractor] Port {ext_port} is busy with an unresponsive process, recycling...")
                kill_processes_by_port(ext_port)
                time.sleep(0.5)

            ext_cmd = [
                llama_bin,
                "-m",
                extractor_model,
                "-ngl",
                "99",
                "--port",
                str(ext_port),
                "--host",
                "127.0.0.1",
                "-c",
                "2048",
                "--alias",
                "electronic-qwen-extractor",
            ]
            print(f"[Extractor] Starting llama-server on port {ext_port} with {os.path.basename(extractor_model)}...")
            proc_ext = spawn_process(ext_cmd, LOG_DIR / "llama_extractor.log")
            state["Extractor"] = {"pid": proc_ext.pid, "port": ext_port, "model": extractor_model}

    # 3. Start llama Reranker (port 8082)
    if not args.no_llama:
        rerank_port = 8082
        rerank_health_url = f"http://127.0.0.1:{rerank_port}/health"
        if is_service_ready(rerank_health_url):
            print(f"[Reranker] Port {rerank_port} is already running and healthy.")
        else:
            if is_port_in_use(rerank_port):
                print(f"[Reranker] Port {rerank_port} is busy with an unresponsive process, recycling...")
                kill_processes_by_port(rerank_port)
                time.sleep(0.5)

            rerank_cmd = [
                llama_bin,
                "-m",
                reranker_model,
                "-ngl",
                "99",
                "--port",
                str(rerank_port),
                "--host",
                "127.0.0.1",
                "-c",
                "2048",
                "--alias",
                "electronic-qwen-reranker",
            ]
            print(f"[Reranker] Starting llama-server on port {rerank_port} with {os.path.basename(reranker_model)}...")
            proc_rerank = spawn_process(rerank_cmd, LOG_DIR / "llama_reranker.log")
            state["Reranker"] = {"pid": proc_rerank.pid, "port": rerank_port, "model": reranker_model}

    record_state(state)

    # 4. Wait for all backends to become healthy
    print("\n[INIT] Waiting for backend services to pass health checks (up to 40s)...")
    wait_targets = []
    if not args.no_ocr:
        wait_targets.append(("PaddleOCR-VL Backend", "http://127.0.0.1:8083/health"))
        wait_targets.append(("PaddleOCR-VL Adapter", "http://127.0.0.1:8010/health"))
    if not args.no_llama:
        wait_targets.append(("llama Extractor", "http://127.0.0.1:8081/health"))
        wait_targets.append(("llama Reranker", "http://127.0.0.1:8082/health"))

    start_wait = time.time()
    while time.time() - start_wait < 40.0:
        ready_targets = [name for name, url in wait_targets if is_service_ready(url)]
        if len(ready_targets) == len(wait_targets):
            print(f"[OK] All backends are healthy: {', '.join(ready_targets)}.")
            break
        time.sleep(1.0)
    else:
        print("[WARN] Some backends did not report healthy in time. Continuing anyway...")

    # 5. ADB reverse port forwarding for attached Android device
    try_configure_adb_reverse(port=args.port)

    # If --no-web specified, detach and show status
    if args.no_web:
        print("\n[INFO] Backend services started in background mode (--no-web).")
        cmd_status()
        atexit.unregister(cleanup_on_exit)
        return

    # 6. Start PartShelf web application in foreground
    if is_port_in_use(args.port):
        print(f"[WARN] Port {args.port} is already in use. Terminating existing process...")
        kill_processes_by_port(args.port)
        time.sleep(0.5)

    print(f"\n[PartShelf] Starting Web Application on http://127.0.0.1:{args.port}")
    print("[PartShelf] Press Ctrl+C in this terminal to shut down all services cleanly.\n")

    if str(PARTSHELF_DIR) not in sys.path:
        sys.path.insert(0, str(PARTSHELF_DIR))

    # Configure environment variables for the runtime
    os.environ["LLAMA_EXTRACTOR_MODEL"] = extractor_model
    os.environ["LLAMA_RERANKER_MODEL"] = reranker_model
    os.environ["LLAMA_OCR_MODEL"] = ocr_model
    os.environ["LLAMA_OCR_MMPROJ"] = ocr_mmproj
    os.environ["LLAMA_OCR_BASE_URL"] = "http://127.0.0.1:8083/v1"
    os.environ["PADDLEOCR_API_URL"] = "http://127.0.0.1:8010"

    try:
        import uvicorn
        uvicorn.run("app.main:app", host="0.0.0.0", port=args.port, reload=True, app_dir=str(PARTSHELF_DIR))
    except KeyboardInterrupt:
        print("\n[PartShelf] KeyboardInterrupt received. Shutting down...")
    finally:
        cleanup_on_exit()


if __name__ == "__main__":
    main()
