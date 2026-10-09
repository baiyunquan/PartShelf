@echo off
rem Stop PartShelf llama.cpp servers
setlocal
cd /d "%~dp0\.."
python scripts\manage_llama_servers.py stop
echo [INFO] llama servers stopped.
