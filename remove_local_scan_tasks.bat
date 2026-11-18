@echo off
setlocal EnableExtensions
for %%D in (MON TUE WED THU FRI SAT) do call :remove_day %%D
echo GeM scheduled tasks removal finished.
pause
exit /b 0

:remove_day
for %%T in (0900 1100 1300 1500 1700) do schtasks /Delete /TN "GeM Tender Auto Scan %1 %%T" /F >nul 2>&1
exit /b 0
