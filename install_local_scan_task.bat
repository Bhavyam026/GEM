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
echo This creates GeM scan tasks at 09:00, 11:00, 13:00, 15:00 and 17:00,
echo Monday through Saturday, using this Windows account.
echo First run run_local_scan.bat manually and confirm it pushes successfully.
echo.
choice /C YN /M "Continue and create the scheduled tasks"
if errorlevel 2 exit /b 0

set "SCRIPT=%~dp0run_local_scan.bat"
for %%D in (MON TUE WED THU FRI SAT) do call :make_day %%D
echo.
echo Task creation finished. Open Task Scheduler to verify "GeM Tender Auto Scan" tasks.
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
