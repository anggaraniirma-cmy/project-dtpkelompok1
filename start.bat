@echo off
REM ===========================================================================
REM  SKOMDA Gesture Quiz - jalankan semua service
REM  Klik dua kali file ini. Jendela ini harus tetap terbuka selama pameran.
REM
REM  Admin   : http://localhost:3000   (admin / skomda2026)
REM  Visitor : http://localhost:8080
REM  API     : http://localhost:8000/docs
REM ===========================================================================
setlocal
cd /d "%~dp0"

echo.
echo   SKOMDA GESTURE QUIZ - SMK Telkom Sidoarjo
echo   ========================================
echo.

REM --- 1. cek Python venv ---------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo   [X] Folder .venv tidak ditemukan.
  echo.
  echo   Jalankan sekali di terminal:
  echo       python -m venv .venv
  echo       .venv\Scripts\python.exe -m pip install -r requirements.txt
  echo.
  pause
  exit /b 1
)

REM --- 2. cek model MediaPipe ----------------------------------------------
if not exist "backend\models\hand_landmarker.task" (
  echo   [!] Model MediaPipe belum ada, mengunduh...
  ".venv\Scripts\python.exe" scripts\download_model.py
  if errorlevel 1 (
    echo   [X] Gagal mengunduh model. Unduh manual lalu simpan di
    echo       backend\models\hand_landmarker.task
    pause
    exit /b 1
  )
)

REM --- 3. cek kamera dipakai aplikasi lain? --------------------------------
echo   Memeriksa kamera...
".venv\Scripts\python.exe" -c "import cv2,sys; c=cv2.VideoCapture(0,cv2.CAP_DSHOW); ok=c.isOpened() and c.read()[0]; c.release(); print('   [OK] Kamera siap' if ok else '   [!] Kamera tidak terdeteksi - permainan tetap jalan, jawab manual bisa dipakai'); sys.exit(0)"

echo.
echo   Menjalankan backend, admin, dan panel pengunjung...
echo.

REM --- 4. jalankan ketiga service ------------------------------------------
".venv\Scripts\python.exe" scripts\run_all.py

REM run_all.py keluar (Ctrl+C atau error): beri kesempatan membaca pesan
echo.
echo   Semua service berhenti.
pause
endlocal
