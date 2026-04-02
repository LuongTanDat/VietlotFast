@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

rem ----- Tim Java va javac -----
rem Kiem tra duong dan Java 17 de dam bao web server co the bien dich va chay duoc.
set "JAVA_EXE="
set "JAVAC_EXE="
set "PWSH_EXE=C:\Program Files (x86)\PowerShell\7\pwsh.exe"
for %%J in (
  "C:\Program Files (x86)\Android\openjdk\jdk-17.0.14\bin\java.exe"
  "C:\Program Files\Eclipse Adoptium\jdk-17.0.18.8-hotspot\bin\java.exe"
) do (
  if not defined JAVA_EXE if exist %%~J set "JAVA_EXE=%%~J"
)
for %%J in (
  "C:\Program Files (x86)\Android\openjdk\jdk-17.0.14\bin\javac.exe"
  "C:\Program Files\Eclipse Adoptium\jdk-17.0.18.8-hotspot\bin\javac.exe"
) do (
  if not defined JAVAC_EXE if exist %%~J set "JAVAC_EXE=%%~J"
)

if not defined JAVA_EXE (
  echo Khong tim thay Java 17 tren may nay.
  echo Hay mo lai cho minh de minh sua duong dan Java.
  pause
  exit /b 1
)
if not defined JAVAC_EXE (
  echo Khong tim thay javac.exe cua Java 17 tren may nay.
  pause
  exit /b 1
)
if not exist "%PWSH_EXE%" set "PWSH_EXE=powershell.exe"

rem ----- Kiem tra cong 8080 va khoi dong lai an toan -----
rem Neu dung server Lotto cu thi tu dong dung de thay bang ban moi, con tien trinh la se khong bi kill.
set "PORT_ACTION="
for /f "usebackq delims=" %%R in (`powershell -NoProfile -Command ^
  "$conn = Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' } | Select-Object -First 1; " ^
  "if (-not $conn) { 'FREE'; exit 0 }; " ^
  "$pid = [int]$conn.OwningProcess; " ^
  "$proc = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $pid) -ErrorAction SilentlyContinue; " ^
  "$name = [string]($proc.Name); " ^
  "$cmd = [string]($proc.CommandLine); " ^
  "if (($name -match '^java(w)?\.exe$') -and ($cmd -match 'LottoWebServer')) { Stop-Process -Id $pid -Force -ErrorAction Stop; Start-Sleep -Seconds 2; 'RESTART'; exit 0 }; " ^
  "'BLOCKED|' + $pid + '|' + $name"`) do set "PORT_ACTION=%%R"

if not defined PORT_ACTION set "PORT_ACTION=FREE"

if /I "%PORT_ACTION%"=="RESTART" (
  echo Da dung server cu cua Lotto tren cong 8080. Dang khoi dong lai ban moi...
)

if /I not "%PORT_ACTION%"=="FREE" if /I not "%PORT_ACTION%"=="RESTART" (
  for /f "tokens=1,2,3 delims=|" %%A in ("%PORT_ACTION%") do (
    set "BLOCK_PID=%%B"
    set "BLOCK_NAME=%%C"
  )
  echo Cong 8080 dang duoc tien trinh khac su dung.
  echo PID: !BLOCK_PID!  Process: !BLOCK_NAME!
  echo Batch se khong tu dong dung tien trinh la.
  echo Hay giai phong cong 8080 roi chay lai.
  pause
  exit /b 1
)

rem ----- Bien dich server Java -----
rem Bien dich lai LottoWebServer.java moi lan chay de tranh lech phien ban giao dien va backend.
echo Dang bien dich LottoWebServer.java...
"%JAVAC_EXE%" -encoding UTF-8 LottoWebServer.java
if errorlevel 1 (
  echo Bien dich that bai.
  pause
  exit /b 1
)

rem ----- Khoi dong server -----
rem Mo mot cua so rieng de chay LottoWebServer voi classpath SQLite hien tai.
echo Dang khoi dong Lotto Web Server...
start "Lotto Web Server" /D "%~dp0" "%PWSH_EXE%" -NoExit -Command "Set-Location -LiteralPath '%~dp0'; & '%JAVA_EXE%' -cp '.;lib\sqlite-jdbc-3.51.2.0.jar' LottoWebServer"

rem ----- Kiem tra server da san sang hay chua -----
rem Thu ping localhost:8080 trong vai giay truoc khi mo trinh duyet.
set "READY=0"
for /l %%I in (1,1,15) do (
  powershell -NoProfile -Command "try { $r = Invoke-WebRequest 'http://localhost:8080/' -UseBasicParsing -TimeoutSec 3; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>nul
  if not errorlevel 1 (
    set "READY=1"
    goto :open_browser
  )
  timeout /t 1 /nobreak >nul
)

:open_browser
rem ----- Mo trinh duyet -----
rem Khi server da len hoac da cho du lau, van mo trinh duyet de nguoi dung kiem tra nhanh.
if "%READY%"=="1" (
  echo Server da san sang tai http://localhost:8080/
) else (
  echo Chua xac nhan duoc server, nhung van mo trinh duyet de ban kiem tra.
)
start "" "http://localhost:8080/"
exit /b 0
