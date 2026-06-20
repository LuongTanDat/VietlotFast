@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
set "PROJECT_ROOT=%~dp0.."
for %%I in ("%PROJECT_ROOT%") do set "PROJECT_ROOT=%%~fI"

rem ----- Tim Java va javac -----
rem Uu tien JDK da cau hinh, sau do thu cac duong dan pho bien va PATH.
set "JAVA_EXE="
set "JAVAC_EXE="
set "PWSH_EXE=C:\Program Files (x86)\PowerShell\7\pwsh.exe"
for %%J in (
  "%JAVA_HOME%\bin\java.exe"
  "C:\Program Files (x86)\Android\openjdk\jdk-17.0.14\bin\java.exe"
  "C:\Program Files\Eclipse Adoptium\jdk-17.0.18.8-hotspot\bin\java.exe"
  "C:\java-1.8.0-openjdk-1.8.0.392-1.b08.redhat.windows.x86_64\bin\java.exe"
) do (
  if not defined JAVA_EXE if exist %%~J set "JAVA_EXE=%%~J"
)
for %%J in (
  "%JAVA_HOME%\bin\javac.exe"
  "C:\Program Files (x86)\Android\openjdk\jdk-17.0.14\bin\javac.exe"
  "C:\Program Files\Eclipse Adoptium\jdk-17.0.18.8-hotspot\bin\javac.exe"
  "C:\java-1.8.0-openjdk-1.8.0.392-1.b08.redhat.windows.x86_64\bin\javac.exe"
) do (
  if not defined JAVAC_EXE if exist %%~J set "JAVAC_EXE=%%~J"
)

if not defined JAVAC_EXE (
  for /f "delims=" %%J in ('where javac.exe 2^>nul') do (
    if not defined JAVAC_EXE set "JAVAC_EXE=%%~fJ"
  )
)
if not defined JAVA_EXE if defined JAVAC_EXE (
  for %%D in ("!JAVAC_EXE!") do (
    if exist "%%~dpDjava.exe" set "JAVA_EXE=%%~dpDjava.exe"
  )
)

if not defined JAVA_EXE (
  echo Khong tim thay java.exe cua JDK tren may nay.
  echo Hay cai JDK hoac dat bien JAVA_HOME.
  pause
  exit /b 1
)
if not defined JAVAC_EXE (
  echo Khong tim thay javac.exe cua JDK tren may nay.
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
  "$owningPid = [int]$conn.OwningProcess; " ^
  "$proc = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $owningPid) -ErrorAction SilentlyContinue; " ^
  "$name = [string]($proc.Name); " ^
  "$cmd = [string]($proc.CommandLine); " ^
  "if (($name -match '^java(w)?\.exe$') -and ($cmd -match 'LottoWebServer')) { Stop-Process -Id $owningPid -Force -ErrorAction Stop; Start-Sleep -Seconds 2; 'RESTART'; exit 0 }; " ^
  "'BLOCKED|' + $owningPid + '|' + $name"`) do set "PORT_ACTION=%%R"

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
if not exist "%PROJECT_ROOT%\backend\bin" mkdir "%PROJECT_ROOT%\backend\bin"
echo Dang bien dich backend\LottoWebServer.java...
pushd "%PROJECT_ROOT%"
"%JAVAC_EXE%" -encoding UTF-8 -d "backend\bin" "backend\LottoWebServer.java"
set "COMPILE_EXIT=!ERRORLEVEL!"
if not "!COMPILE_EXIT!"=="0" (
  popd
  echo Bien dich that bai.
  pause
  exit /b 1
)

rem ----- Khoi dong server -----
rem Mo mot cua so rieng de chay LottoWebServer voi classpath SQLite hien tai.
echo Dang khoi dong Lotto Web Server...
start "Lotto Web Server" "%PWSH_EXE%" -NoExit -Command "& '%JAVA_EXE%' -cp 'backend\bin;backend\lib\sqlite-jdbc-3.51.2.0.jar' LottoWebServer"
popd

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
