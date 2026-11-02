@echo off
title PetHospital REST Backend (8080)
cd /d "%~dp0PetHospitalServer"

echo ============================================
echo   PetHospital REST Backend
echo   Port : 8080
echo   Web  : http://127.0.0.1:8080/
echo   Close this window to stop.
echo ============================================
echo.

if not exist "pethospital.exe" (
    echo [ERROR] pethospital.exe not found.
    pause
    exit /b 1
)

pethospital.exe
