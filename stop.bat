@echo off
REM ===========================================================================
REM  SKOMDA Gesture Quiz - hentikan semua service (port 8000, 3000, 8080)
REM  Klik dua kali bila ada service yang masih hidup setelah jendela ditutup,
REM  atau bila muncul pesan "port sudah dipakai".
REM ===========================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo   Menghentikan SKOMDA Gesture Quiz...
echo.

set FOUND=0
for %%P in (8000 3000 8080) do (
  for /f "tokens=5" %%A in ('netstat -ano ^| findstr /R /C:":%%P .*LISTENING"') do (
    echo   Port %%P -^> menghentikan PID %%A
    taskkill /PID %%A /F >nul 2>&1
    set FOUND=1
  )
)

if "!FOUND!"=="0" (
  echo   Tidak ada service yang berjalan.
) else (
  echo.
  echo   Selesai. Kamera sudah dilepas.
)

echo.
pause
endlocal
