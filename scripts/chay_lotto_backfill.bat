@echo off
setlocal
cd /d "%~dp0"
set "PROJECT_ROOT=%~dp0.."
for %%I in ("%PROJECT_ROOT%") do set "PROJECT_ROOT=%%~fI"

rem ----- Tim PowerShell va Python -----
rem Chon moi truong shell va Python phu hop de chay job backfill o nen.
set "PWSH_EXE=C:\Program Files (x86)\PowerShell\7\pwsh.exe"
if not exist "%PWSH_EXE%" set "PWSH_EXE=powershell.exe"
set "PYTHON_CMD=py -3"
set "POWERSHELL_PYTHON_CMD=py -3"
if exist "C:\Users\Luong Tan Dat\AppData\Local\Programs\Python\Python313\python.exe" (
  set PYTHON_CMD="C:\Users\Luong Tan Dat\AppData\Local\Programs\Python\Python313\python.exe"
  set "POWERSHELL_PYTHON_CMD=& 'C:\Users\Luong Tan Dat\AppData\Local\Programs\Python\Python313\python.exe'"
)

rem ----- Duong dan log va status -----
rem Cac file nay duoc dung de theo doi tien do full-history backfill.
set "LOG_DIR=%PROJECT_ROOT%\runtime\logs"
set "LOG_FILE=%LOG_DIR%\full_history_backfill.log"
set "STATUS_FILE=%LOG_DIR%\full_history_backfill.status.json"

rem ----- Lenh xem nhanh trang thai -----
rem Neu goi kem tham so status thi chi in thong tin hien tai, khong khoi dong job moi.
if /I "%~1"=="status" (
  pushd "%PROJECT_ROOT%"
  %PYTHON_CMD% backend\lotto_backfill.py status
  popd
  exit /b %errorlevel%
)

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

rem ----- Khoi dong runner nen -----
rem Chay lotto_backfill.py trong cua so rieng de job dai khong chan terminal hien tai.
echo Dang khoi dong full-history backfill nen...
start "Lotto Full History Backfill" /MIN "%PWSH_EXE%" -NoExit -Command "Set-Location -LiteralPath '%PROJECT_ROOT%'; %POWERSHELL_PYTHON_CMD% 'backend\lotto_backfill.py'"

rem ----- Tom tat cho nguoi dung -----
rem In ra log/status file va hien trang thai ngay sau khi runner vua duoc bat.
echo.
echo Log file   : %LOG_FILE%
echo Status file: %STATUS_FILE%
echo.
echo Neu muon xem nhanh trang thai, chay:
echo   .\chay_lotto_backfill.bat status
echo.
timeout /t 2 /nobreak >nul
pushd "%PROJECT_ROOT%"
%PYTHON_CMD% backend\lotto_backfill.py status
popd
exit /b 0
