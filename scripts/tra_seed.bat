@echo off
setlocal
set "seedLookupPython="
for /d %%P in ("%LOCALAPPDATA%\Programs\Python\Python3*") do call :try_python "%%~fP\python.exe"
if not defined seedLookupPython for /f "delims=" %%P in ('where python 2^>nul') do call :try_python "%%P"
if not defined seedLookupPython goto no_python
pushd "%~dp0.."
"%seedLookupPython%" scripts\tra_seed.py %*
set "seedLookupExit=%errorlevel%"
popd
if not "%seedLookupExit%"=="0" if "%~1"=="" pause
exit /b %seedLookupExit%

:try_python
if defined seedLookupPython exit /b 0
set "seedLookupCandidate=%~1"
if not "%seedLookupCandidate:WindowsApps=%"=="%seedLookupCandidate%" exit /b 1
if not exist "%seedLookupCandidate%" exit /b 1
"%seedLookupCandidate%" -c "import sys,sqlite3; sys.exit(0 if sys.version_info[:2] >= (3,10) else 1)" >nul 2>nul
if not errorlevel 1 set "seedLookupPython=%seedLookupCandidate%"
exit /b 0

:no_python
echo Khong tim thay Python 3.10+ hoat dong. Hay cai Python hoac chay scripts\tra_seed.py bang Python cua du an.
pause
exit /b 2
