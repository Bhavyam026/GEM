@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist ".git" (
  echo ERROR: Run this installer from the root of the Bhavyam026/GEM repository.
  pause
  exit /b 10
)
if not exist "run_local_scan.bat" (
  echo ERROR: run_local_scan.bat is missing.
  pause
  exit /b 11
)
if not exist "configure_local_scan_tasks.ps1" (
  echo ERROR: configure_local_scan_tasks.ps1 is missing.
  pause
  exit /b 12
)
echo This creates GeM scan tasks at 09:00, 11:00, 13:00, 15:00 and 17:00,
echo Monday through Saturday, using this Windows account.
echo Missed runs will be queued for the next time Windows is available.
echo Sleep/hibernate wake-up will be enabled where supported.
echo A fully shut-down PC cannot run tasks until it is powered on again.
echo.
choice /C YN /M "Continue and create the scheduled tasks"
if errorlevel 2 exit /b 0

set "SCRIPT=%~dp0run_local_scan.bat"
for %%D in (MON TUE WED THU FRI SAT) do call :make_day %%D
echo.
echo Applying missed-run and wake-from-sleep settings...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0configure_local_scan_tasks.ps1"
if errorlevel 1 (
  echo WARNING: Task settings could not all be updated. Check the PowerShell message above.
  pause
  exit /b 13
)
echo.
echo Task creation and settings update finished.
echo Verify "GeM Tender Auto Scan" tasks in Task Scheduler.
pause
exit /b 0

:make_day
for %%T in (09:00 11:00 13:00 15:00 17:00) do call :make_one %1 %%T
exit /b 0

:make_one
set "DAY=%1"
set "CLOCK=%2"
set "SAFE_CLOCK=%2"
set "SAFE_CLOCK=%SAFE_CLOCK::=%"
set "TASK_NAME=GeM Tender Auto Scan %DAY% %SAFE_CLOCK%"
set "TASK_ACTION=cmd.exe /c ""%SCRIPT%"""
schtasks /Create /TN "%TASK_NAME%" /TR "%TASK_ACTION%" /SC WEEKLY /D %DAY% /ST %CLOCK% /IT /F
if errorlevel 1 echo WARNING: Could not create "%TASK_NAME%".
exit /b 0
