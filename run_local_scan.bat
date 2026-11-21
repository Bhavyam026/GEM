@echo off
setlocal EnableExtensions
set "PYTHONDONTWRITEBYTECODE=1"
set "REPO_DIR=%~dp0"
cd /d "%REPO_DIR%"
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
echo Repository: "%REPO_DIR%"

where py >nul 2>&1
if errorlevel 1 goto no_python
py -3.8 -c "import sys; print(sys.version); sys.exit(0 if sys.version_info[0]==3 and sys.version_info[1]==8 else 1)"
if errorlevel 1 goto wrong_python

where git >nul 2>&1
if errorlevel 1 goto no_git

git -C "%REPO_DIR%" rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 goto no_git_repo

git -C "%REPO_DIR%" diff --quiet HEAD --
if errorlevel 2 goto git_check_failed
if errorlevel 1 goto dirty_worktree
git -C "%REPO_DIR%" diff --cached --quiet
if errorlevel 2 goto git_check_failed
if errorlevel 1 goto staged_worktree

echo Updating repository from GitHub...
git -C "%REPO_DIR%" pull --rebase origin main
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

:no_git_repo
echo ERROR: Git could not identify the repository at "%REPO_DIR%".
exit /b 19

:git_check_failed
echo ERROR: Git could not check the repository state. No scan was started.
exit /b 20

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
py -3.8 -m pip install -r "%REPO_DIR%requirements.txt"
if errorlevel 1 goto install_failed

:run_scan
echo Running official GeM Advance Search collector...
py -3.8 "%REPO_DIR%scripts\scan_gem.py"
set "SCAN_RESULT=%ERRORLEVEL%"

echo Staging tender data and scan status...
git -C "%REPO_DIR%" add -A data
if errorlevel 1 goto add_failed
git -C "%REPO_DIR%" diff --cached --quiet
if not errorlevel 1 goto no_changes

git -C "%REPO_DIR%" config user.name >nul 2>&1
if errorlevel 1 git -C "%REPO_DIR%" config user.name "GeM Local Auto Scanner"
git -C "%REPO_DIR%" config user.email >nul 2>&1
if errorlevel 1 git -C "%REPO_DIR%" config user.email "gem-local-scanner@users.noreply.github.com"

git -C "%REPO_DIR%" commit -m "Update GeM tender scan data (local PC)"
if errorlevel 1 goto commit_failed

echo Publishing scan data and status to GitHub...
git -C "%REPO_DIR%" push origin main
if errorlevel 1 goto push_failed

echo GitHub updated. The dashboard can now receive the published scan status and data.
if "%SCAN_RESULT%"=="0" goto scan_done
echo WARNING: Scan was incomplete. Previous tender data should remain preserved.
:scan_done
exit /b %SCAN_RESULT%

:no_changes
echo No tender/status changes to publish.
exit /b %SCAN_RESULT%

:add_failed
echo ERROR: Could not stage tender data.
exit /b 21

:install_failed
echo ERROR: Could not install requirements.
exit /b 16

:commit_failed
echo ERROR: Could not create data commit.
exit /b 17

:push_failed
echo ERROR: Push failed. Local commit is retained for a later retry.
exit /b 18
