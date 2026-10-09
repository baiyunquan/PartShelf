@echo off
rem Start PartShelf llama.cpp servers for Extractor and Reranker
setlocal
cd /d "%~dp0\.."
python scripts\manage_llama_servers.py start
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to start llama servers.
    pause
    exit /b 1
)
echo [INFO] llama servers are running.
