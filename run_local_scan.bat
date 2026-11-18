@echo off
setlocal EnableExtensions
set "PYTHONDONTWRITEBYTECODE=1"
cd /d "%~dp0"
if not exist ".git" goto no_repo
if not exist "%USERPROFILE%\GeM-Logs" mkdir "%USERPROFILE%\GeM-Logs"
set "LOG_FILE=%USERPROFILE%\GeM-Logs\local-scan.log"
call :main >> "%LOG_FILE%" 2>&1
set "RESULT=%ERRORLEVEL%"
echo.
echo GeM scan runner finished with exit code %RESULT%.
echo Log: "%LOG_FILE%"
exit /b %RESULT%

:no_repo
echo ERROR: Run this file from the root of the Bhavyam026/GEM repository.
exit /b 10

:main
echo ============================================================
echo Starting local GeM scan
echo ============================================================

where py >nul 2>&1
if errorlevel 1 goto no_python
py -3.8 -c "import sys; print(sys.version); sys.exit(0 if sys.version_info[0]==3 and sys.version_info[1]==8 else 1)"
if errorlevel 1 goto wrong_python

where git >nul 2>&1
if errorlevel 1 goto no_git

git diff --quiet
if errorlevel 1 goto dirty_worktree
git diff --cached --quiet
if errorlevel 1 goto staged_worktree

echo Updating repository from GitHub...
git pull --rebase origin main
if errorlevel 1 goto pull_failed

py -3.8 -c "import pypdf" >nul 2>&1
if errorlevel 1 goto install_requirements

goto run_scan

:no_python
echo ERROR: Python Launcher py.exe was not found in PATH.
exit /b 11

:wrong_python
echo ERROR: Python 3.8.x was not found through py -3.8.
exit /b 12

:no_git
echo ERROR: Git was not found in PATH.
exit /b 13

:dirty_worktree
echo ERROR: Tracked repository files have local changes. Commit or stash them before scanning.
exit /b 14

:staged_worktree
echo ERROR: Tracked repository files are staged locally. Commit or unstage them before scanning.
exit /b 14

:pull_failed
echo ERROR: git pull failed. Check internet and saved GitHub authentication.
exit /b 15

:install_requirements
echo Installing scanner dependency...
py -3.8 -m pip install -r requirements.txt
if errorlevel 1 goto install_failed

:run_scan
echo Running official GeM Advance Search collector...
py -3.8 scripts\scan_gem.py
set "SCAN_RESULT=%ERRORLEVEL%"

echo Staging tender data and scan status...
git add -A data
git diff --cached --quiet
if not errorlevel 1 goto no_changes

git config user.name >nul 2>&1
if errorlevel 1 git config user.name "GeM Local Auto Scanner"
git config user.email >nul 2>&1
if errorlevel 1 git config user.email "gem-local-scanner@users.noreply.github.com"

git commit -m "Update GeM tender scan data (local PC)"
if errorlevel 1 goto commit_failed

echo Publishing scan data and status to GitHub...
git push origin main
if errorlevel 1 goto push_failed

echo GitHub updated. The dashboard can now receive the published scan status and data.
if "%SCAN_RESULT%"=="0" goto scan_done
echo WARNING: Scan was incomplete. Previous tender data should remain preserved.
:scan_done
exit /b %SCAN_RESULT%

:no_changes
echo No tender/status changes to publish.
exit /b %SCAN_RESULT%

:install_failed
echo ERROR: Could not install requirements.
exit /b 16

:commit_failed
echo ERROR: Could not create data commit.
exit /b 17

:push_failed
echo ERROR: Push failed. Local commit is retained for a later retry.
exit /b 18
