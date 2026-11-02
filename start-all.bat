@echo off
title Start All MCP Services
cd /d "%~dp0"

echo ============================================
echo   Starting all services required by wAgent
echo ============================================
echo.
echo   [1] PetHospital REST backend  -> 8080  (web + data source)
echo   [2] PetHospital MCP Server    -> 8090  (tool: list_pets)
echo   [3] Bazi MCP Server           -> 8095  (3 bazi tools)
echo.
echo   Order matters: REST must be ready before MCP.
echo ============================================
echo.

echo [1/3] Starting PetHospital REST backend...
start "PetHospital REST" cmd /c "%~dp0start-rest.bat"
timeout /t 4 /nobreak >nul

echo [2/3] Starting PetHospital MCP Server...
start "PetHospital MCP" cmd /c "%~dp0start-mcp-pet.bat"
timeout /t 6 /nobreak >nul

echo [3/3] Starting Bazi MCP Server...
start "Bazi MCP" cmd /c "%~dp0start-mcp-bazi.bat"
timeout /t 6 /nobreak >nul

echo.
echo ============================================
echo   Port check
echo ============================================
for %%P in (8080 8090 8095) do (
    netstat -ano | findstr /R /C:":%%P .*LISTENING" >nul
    if errorlevel 1 (
        echo   %%P : NOT listening  ^<-- check its window for errors
    ) else (
        echo   %%P : listening OK
    )
)

echo.
echo ============================================
echo   Next: start wAgent
echo     cd D:\office
echo     python D:\LLM-Course\Agent\wAgent\main.py
echo ============================================
echo.
pause
