@echo off
setlocal EnableDelayedExpansion
set "LOTTO_AUTO_START=0"
if /I "%~1"=="--auto" set "LOTTO_AUTO_START=1"
cd /d "%~dp0"
set "PROJECT_ROOT=%~dp0.."
for %%I in ("%PROJECT_ROOT%") do set "PROJECT_ROOT=%%~fI"

rem ----- Tim Java va javac -----
rem Uu tien JDK da cau hinh, sau do thu cac duong dan pho bien va PATH.
set "JAVA_EXE="
set "JAVAC_EXE="
set "PWSH_EXE=C:\Program Files\PowerShell\7\pwsh.exe"
if not exist "%PWSH_EXE%" set "PWSH_EXE=C:\Program Files (x86)\PowerShell\7\pwsh.exe"
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
rem Luon dung java va javac cung JDK, tranh JRE JAVA_HOME lech ban bien dich.
if defined JAVAC_EXE (
  for %%D in ("!JAVAC_EXE!") do (
    if exist "%%~dpDjava.exe" set "JAVA_EXE=%%~dpDjava.exe"
  )
)

if not defined JAVA_EXE (
  echo Khong tim thay java.exe cua JDK tren may nay.
  echo Hay cai JDK hoac dat bien JAVA_HOME.
  if "%LOTTO_AUTO_START%"=="0" pause
  exit /b 1
)
if not defined JAVAC_EXE (
  echo Khong tim thay javac.exe cua JDK tren may nay.
  if "%LOTTO_AUTO_START%"=="0" pause
  exit /b 1
)
if not exist "%PWSH_EXE%" set "PWSH_EXE=C:\Program Files (x86)\PowerShell\7\pwsh.exe"
if not exist "%PWSH_EXE%" set "PWSH_EXE=powershell.exe"

rem ----- Launcher PowerShell: compile truoc, kiem tra lai PID/worker roi moi restart -----
set "LOTTO_AUTO_ARG="
if "%LOTTO_AUTO_START%"=="1" set "LOTTO_AUTO_ARG=-Auto"
"%PWSH_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\scripts\start_lotto_web.ps1" -ProjectRoot "%PROJECT_ROOT%" -JavaExe "%JAVA_EXE%" -JavacExe "%JAVAC_EXE%" %LOTTO_AUTO_ARG%
exit /b %ERRORLEVEL%
