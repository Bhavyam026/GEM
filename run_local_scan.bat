@echo off
setlocal EnableExtensions
set "PYTHONDONTWRITEBYTECODE=1"
cd /d "%~dp0"
if not exist ".git" (
  echo ERROR: Run this file from the root of the Bhavyam026/GEM repository.
  exit /b 10
)
if not exist "%USERPROFILE%\GeM-Logs" mkdir "%USERPROFILE%\GeM-Logs"
set "LOG_FILE=%USERPROFILE%\GeM-Logs\local-scan.log"
call :main >> "%LOG_FILE%" 2>&1
set "RESULT=%ERRORLEVEL%"
echo.
echo GeM scan runner finished with exit code %RESULT%.
echo Log: "%LOG_FILE%"
exit /b %RESULT%

:main
echo ============================================================
echo [%DATE% %TIME%] Starting local GeM scan
echo ============================================================

where py >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python Launcher (py.exe) was not found in PATH.
  exit /b 11
)
py -3.8 -c "import sys; print(sys.version); sys.exit(0 if sys.version_info[0]==3 and sys.version_info[1]==8 else 1)"
if errorlevel 1 (
  echo ERROR: Python 3.8.x was not found through "py -3.8".
  exit /b 12
)

where git >nul 2>&1
if errorlevel 1 (
  echo ERROR: Git was not found in PATH.
  exit /b 13
)

git diff --quiet
if errorlevel 1 (
  echo ERROR: Tracked repository files have local changes. Commit or stash them before scanning.
  exit /b 14
)
git diff --cached --quiet
if errorlevel 1 (
  echo ERROR: Tracked repository files are staged locally. Commit or unstage them before scanning.
  exit /b 14
)

echo Updating repository from GitHub...
git pull --rebase origin main
if errorlevel 1 (
  echo ERROR: git pull failed. Check internet and saved GitHub authentication.
  exit /b 15
)

py -3.8 -c "import pypdf" >nul 2>&1
if errorlevel 1 (
  echo Installing scanner dependency...
  py -3.8 -m pip install -r requirements.txt
  if errorlevel 1 (
    echo ERROR: Could not install requirements.
    exit /b 16
  )
)

echo Running official GeM Advance Search collector...
py -3.8 scripts\scan_gem.py
set "SCAN_RESULT=%ERRORLEVEL%"

echo Staging tender data and scan status...
git add -A data
git diff --cached --quiet
if not errorlevel 1 (
  echo No tender/status changes to publish.
  exit /b %SCAN_RESULT%
)

git config user.name >nul 2>&1
if errorlevel 1 git config user.name "GeM Local Auto Scanner"
git config user.email >nul 2>&1
if errorlevel 1 git config user.email "gem-local-scanner@users.noreply.github.com"

git commit -m "Update GeM tender scan data (local PC)"
if errorlevel 1 (
  echo ERROR: Could not create data commit.
  exit /b 17
)

echo Publishing verified data/status to GitHub...
git push origin main
if errorlevel 1 (
  echo ERROR: Push failed. The local commit is retained; next run can retry after authentication/network is fixed.
  exit /b 18
)

echo GitHub updated. Configured dashboard deployments should now pick up the new data.
if not "%SCAN_RESULT%"=="0" (
  echo WARNING: Scan was incomplete. Previous tender data was preserved; failure status was published.
)
exit /b %SCAN_RESULT%
