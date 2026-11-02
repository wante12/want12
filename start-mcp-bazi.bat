@echo off
title Bazi MCP Server (8095)
cd /d "%~dp0BaziMCP"

set PORT=8095

echo ============================================
echo   Bazi MCP Server (bazi-mcp)
echo   Port : 8095
echo   MCP  : http://127.0.0.1:8095/mcp
echo ============================================
echo.

if not exist "node_modules\bazi-mcp\dist\httpServer.js" (
    echo [INFO] dependencies missing, installing...
    call npm install --no-audit --no-fund
    if errorlevel 1 (
        echo [ERROR] npm install failed. Check Node.js and network.
        pause
        exit /b 1
    )
)

node node_modules\bazi-mcp\dist\httpServer.js
