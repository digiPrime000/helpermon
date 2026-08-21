@echo off
rem ---------------------------------------------------------------------
rem Double-click uninstaller, the counterpart to install.bat.
rem
rem It asks twice, because the two halves are not the same decision. The
rem installation is 400 MB of packages that can be downloaded again in five
rem minutes. What you taught the bots is an evening in front of the wizard
rem and cannot be downloaded at all, so it is never removed by the same yes.
rem
rem It cannot delete the folder it is standing in, and does not try. What is
rem left afterwards is text files.
rem ---------------------------------------------------------------------
setlocal
cd /d "%~dp0"
title Helpermon, remove

echo ==============================================
echo   Helpermon - remove
echo ==============================================
echo.

rem --- What is actually here -------------------------------------------
set "VENVMB=?"
rem Through a file rather than for /f. A for /f wraps its command in
rem another cmd, and the nested quotes of a PowerShell -Command do not
rem survive that: measured 177 MB by hand and reported 0 through the
rem loop. A plain redirect has no second parser in it.
set "SIZEFILE=%TEMP%\helpermon_size.txt"
if exist "%~dp0.venv" powershell -NoProfile -Command "[math]::Round((Get-ChildItem -Recurse -Force -File '%~dp0.venv' | Measure-Object -Sum Length).Sum/1MB)" > "%SIZEFILE%" 2>nul
if exist "%SIZEFILE%" set /p VENVMB=<"%SIZEFILE%"
if exist "%SIZEFILE%" del /q "%SIZEFILE%"

set "UDFILES=0"
set "COUNTFILE=%TEMP%\helpermon_count.txt"
if exist "%~dp0userdata" dir /a-d /s /b "%~dp0userdata" 2>nul | find /c /v "" > "%COUNTFILE%"
if exist "%COUNTFILE%" set /p UDFILES=<"%COUNTFILE%"
if exist "%COUNTFILE%" del /q "%COUNTFILE%"

echo Part 1 of 2 - the installation
echo.
if exist "%~dp0.venv" (
    echo    .venv                    %VENVMB% MB of packages
) else (
    echo    .venv                    not here
)
if exist "%~dp0Start Helpermon.bat" (
    echo    Start Helpermon.bat      the starter
) else (
    echo    Start Helpermon.bat      not here
)
if exist "%~dp0__pycache__" echo    __pycache__              compiled leftovers
echo    Desktop shortcut         only if it points at this folder
echo.
echo All of it can be had back by running install.bat again.
echo.
set "ANSWER="
set /p ANSWER=Remove these? [y/N]
if /i not "%ANSWER%"=="y" goto skip_program

echo.
if exist "%~dp0.venv" (
    echo    removing .venv
    rmdir /s /q "%~dp0.venv"
)
if exist "%~dp0__pycache__" rmdir /s /q "%~dp0__pycache__"
if exist "%~dp0Start Helpermon.bat" del /q "%~dp0Start Helpermon.bat"

rem The shortcut is checked before it is deleted, not deleted because of its
rem name. Somebody can have a second copy of Helpermon installed elsewhere,
rem and its shortcut is called exactly the same thing.
rem
rem Windows is asked where the desktop is rather than guessed at, the same
rem way make_shortcut.py puts it there. The old guesses are still searched
rem behind that answer, because a shortcut written by an earlier version can
rem be sitting in a OneDrive\Desktop that was never the desktop.
powershell -NoProfile -Command "$here = '%~dp0'.TrimEnd('\'); $paths = @(); $known = [Environment]::GetFolderPath('Desktop'); if ($known) { $paths += (Join-Path $known 'Helpermon.lnk') }; foreach ($base in @($env:USERPROFILE, $env:OneDrive)) { if (-not $base) { continue }; foreach ($name in 'Desktop','Schreibtisch') { $paths += (Join-Path $base (Join-Path $name 'Helpermon.lnk')) } }; foreach ($p in ($paths | Select-Object -Unique)) { if (Test-Path $p) { $s = (New-Object -ComObject WScript.Shell).CreateShortcut($p); if ($s.WorkingDirectory -eq $here) { Remove-Item $p -Force; Write-Output ('   removing ' + $p) } else { Write-Output ('   keeping ' + $p + ', it points at another copy') } } }"
echo.
echo Installation removed.
goto data

:skip_program
echo.
echo Left alone.

rem --- The learned data, a separate decision ----------------------------
:data
echo.
echo ==============================================
echo.
echo Part 2 of 2 - what you taught it
echo.
if exist "%~dp0userdata" (
    echo    userdata                 %UDFILES% files cropped from your screen
) else (
    echo    userdata                 not here
)
if exist "%APPDATA%\digibot" echo    %APPDATA%\digibot
if exist "%APPDATA%\helpermon.json" echo    helpermon.json           your settings
if exist "%APPDATA%\digibot_app.json" echo    digibot_app.json         settings, older name
echo.
echo This is the part that cannot be downloaded again. Removing it means
echo going through the setup wizard from the start next time. Say no if you
echo are reinstalling, moving to another folder, or not sure.
echo.
set "ANSWER="
set /p ANSWER=Remove what you taught it as well? [y/N]
if /i not "%ANSWER%"=="y" goto kept_data

echo.
if exist "%~dp0userdata" (
    echo    removing userdata
    rmdir /s /q "%~dp0userdata"
)
if exist "%APPDATA%\digibot" (
    echo    removing %APPDATA%\digibot
    rmdir /s /q "%APPDATA%\digibot"
)
if exist "%APPDATA%\helpermon.json" del /q "%APPDATA%\helpermon.json"
if exist "%APPDATA%\digibot_app.json" del /q "%APPDATA%\digibot_app.json"
echo.
echo Removed.
goto done

:kept_data
echo.
if exist "%~dp0userdata" (
    echo Kept, in the userdata folder beside this file.
) else (
    echo Kept.
)

:done
echo.
echo ==============================================
echo   Done.
echo ==============================================
echo.
echo What is left in this folder is the program itself, text files and no
echo installed parts. Delete the folder to finish - this file cannot delete
echo the folder it is running from.
echo.
echo Python was not touched. Other programs use it, and this installer never
echo assumed it was the only one. If you installed it for Helpermon alone,
echo remove it under Settings, Apps, Installed apps.
echo.
pause
