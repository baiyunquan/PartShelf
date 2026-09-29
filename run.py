"""
Startup launcher for PartShelf.
Usage:
    python run.py
"""
import sys
import socket
from pathlib import Path
import uvicorn

PARTSHELF_DIR = Path(__file__).resolve().parent

if str(PARTSHELF_DIR) not in sys.path:
    sys.path.insert(0, str(PARTSHELF_DIR))

def check_port_in_use(port: int = 8000) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0

if __name__ == "__main__":
    port = 8000
    if check_port_in_use(port):
        print(f"[Warning] Port {port} is already in use by another process.")
        print(f"To terminate the process holding port {port}, run in PowerShell:")
        print(f"    Stop-Process -Id (Get-NetTCPConnection -LocalPort {port} -State Listen).OwningProcess -Force")
        print("Or check running Python processes with: Get-Process python*")
        sys.exit(1)

    print(f"Starting PartShelf server from: {PARTSHELF_DIR}")
    print(f"Open your browser at: http://127.0.0.1:{port}")
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, reload=True, app_dir=str(PARTSHELF_DIR))
