@echo off
title PetHospital MCP Server (8090)
cd /d "%~dp0PetHospitalMCP"

set MCP_PORT=8090
set PET_HOSPITAL_BASE_URL=http://127.0.0.1:8080
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo ============================================
echo   PetHospital MCP Server
echo   Port   : 8090
echo   MCP    : http://127.0.0.1:8090/mcp
echo   Health : http://127.0.0.1:8090/health
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found in PetHospitalMCP
    pause
    exit /b 1
)

echo NOTE: this depends on the REST backend on 8080.
echo       Run start-rest.bat first.
echo.

.venv\Scripts\python.exe server.py
