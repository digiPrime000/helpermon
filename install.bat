@echo off
rem ---------------------------------------------------------------------
rem Double-click installer. This is the file a player starts first, and it
rem is meant to be the only time a command window is ever seen.
rem
rem It finds Python (and offers to install it), builds a virtual environment
rem in .venv, installs the packages into it and creates a desktop shortcut.
rem Everything after this is a double-click on that shortcut.
rem
rem Why a virtual environment, when an earlier version deliberately avoided
rem one: a venv never has to be "activated". Activating only edits PATH for
rem a shell, and nothing here uses a shell. The shortcut names
rem .venv\Scripts\pythonw.exe by its full path, exactly the way it already
rem named the system pythonw.exe, so the double-click is unchanged. What is
rem won is that installing cannot damage another Python project on this
rem machine, and that uninstalling is deleting the folder.
rem ---------------------------------------------------------------------
setlocal
cd /d "%~dp0"
title Helpermon, installation

rem The version fetched only when the machine has no Python at all. Kept a
rem little behind the newest release on purpose, because every package here
rem has to have a ready-built wheel for it; a brand new Python means pip
rem tries to compile numpy and opencv, which needs a C compiler nobody has.
set "WINGET_PY=Python.Python.3.12"

set "VENVPY=%~dp0.venv\Scripts\python.exe"

echo ==============================================
echo   Helpermon - installation
echo ==============================================
echo.

rem --- 1. Is Python there at all? --------------------------------------
call :find_python
if defined PYEXE goto have_python

echo Python was not found. Helpermon is written in Python, so it is needed.
echo.

where winget >nul 2>&1
if errorlevel 1 goto manual_python

echo I can install it for you now. It goes into your own user folder, so
echo Windows will not ask for an administrator password, and it changes
echo nothing else on this machine.
echo.
set "ANSWER="
set /p ANSWER=Install Python now? [Y/n] 
if /i "%ANSWER%"=="n" goto manual_python

echo.
echo Installing Python, this takes a minute.
rem --source winget, so the Store source is never consulted. Asked about
rem a package id it does not know, it wants consent to send the region
rem to Microsoft, and that question is asked in a way our --accept flags
rem do not answer.
winget install -e --id %WINGET_PY% --source winget --scope user --accept-package-agreements --accept-source-agreements
echo.

rem PATH in this window is the one from before winget ran, so a fresh
rem "py" is not found by name yet. Look where the per-user install puts it.
call :find_python
if not defined PYEXE call :find_python_installed
if defined PYEXE goto have_python

echo Python still cannot be found after the installation.
echo Close this window, open the folder again and start install.bat once
echo more - a new window picks up the changed PATH.
echo.
pause
exit /b 1

:manual_python
echo.
echo Install Python 3.10 or newer from
echo     https://www.python.org/downloads/
echo During installation tick "Add python.exe to PATH", otherwise this
echo installer cannot find it afterwards. Then start install.bat again.
echo.
echo The download page is opening now.
start "" https://www.python.org/downloads/
pause
exit /b 1

:have_python
rem Printed directly rather than captured into a variable: a for /f
rem around a quoted full path is one of the places cmd mangles quotes.
"%PYEXE%" %PYARGS% --version
echo.

rem --- 2. The virtual environment --------------------------------------
rem A venv records the absolute path it was built at. Moving the folder
rem leaves one that cannot start, which looks exactly like a broken
rem installation, so test it rather than trust that it exists.
if not exist "%VENVPY%" goto make_venv
"%VENVPY%" -c "pass" >nul 2>&1
if not errorlevel 1 goto have_venv
echo The existing .venv folder does not work, most likely because this
echo folder was moved or renamed. Building it again.
rmdir /s /q "%~dp0.venv"

:make_venv
echo Preparing the environment in .venv
"%PYEXE%" %PYARGS% -m venv "%~dp0.venv"
if errorlevel 1 (
    echo.
    echo The environment could not be created. On some systems the Python
    echo installation is missing the venv part; installing Python from
    echo python.org rather than from the Microsoft Store fixes that.
    echo.
    pause
    exit /b 1
)

:have_venv
rem Not fatal. An old pip only means older packages, a missing internet
rem connection is reported by the real install below with a better message.
"%VENVPY%" -m pip install --upgrade pip --quiet --disable-pip-version-check

rem --- 3. Packages -----------------------------------------------------
echo.
echo Installing the required packages. The first time this takes a few
echo minutes and downloads about 150 MB. Windows Defender scans each one
echo as it arrives, which is why it is slower than the download itself.
echo.
"%VENVPY%" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo Installing the packages failed. The lines above say why. Common
    echo causes are no internet connection, a company network blocking pip,
    echo or a very new Python with no ready-built packages yet.
    echo.
    pause
    exit /b 1
)

echo.
echo Packages installed.
echo.

rem --- 4. Desktop shortcut ---------------------------------------------
rem Run through the venv interpreter, because make_shortcut.py points the
rem shortcut at the pythonw.exe beside whichever Python is running it.
echo Creating the desktop shortcut.
"%VENVPY%" make_shortcut.py
if errorlevel 1 (
    echo.
    echo The shortcut could not be created. That is not fatal, start the
    echo program with "Start Helpermon.bat" in this folder instead.
)

echo.
echo ==============================================
echo   Done.
echo ==============================================
echo.
echo Start the program from the desktop shortcut, or from
echo "Start Helpermon.bat" in this folder.
echo.
echo What to do next is in QUICKSTART.md. In short: start LDPlayer, open
echo the game, then run the setup once from the Introduction tab.
echo.
pause
exit /b 0


rem ---------------------------------------------------------------------
rem Finding Python. The result is two variables rather than one, because
rem the launcher needs an argument: "py -3" cannot be quoted as a whole,
rem and a path with a space in it has to be. So callers write
rem     "%PYEXE%" %PYARGS% -m venv ...
rem ---------------------------------------------------------------------
:find_python
set "PYEXE="
set "PYARGS="
py -3 --version >nul 2>&1
if not errorlevel 1 (
    set "PYEXE=py"
    set "PYARGS=-3"
    goto :eof
)
rem Not "python --version": on a machine without Python that name resolves
rem to the Microsoft Store stub, and running it opens the Store. Ask where
rem it lives first and skip that one.
for /f "delims=" %%p in ('where python 2^>nul') do call :try_python "%%p"
goto :eof

:try_python
if defined PYEXE goto :eof
echo %~1 | find /i "\WindowsApps\" >nul
if not errorlevel 1 goto :eof
"%~1" --version >nul 2>&1
if errorlevel 1 goto :eof
set "PYEXE=%~1"
goto :eof

rem Where a per-user install from winget or python.org ends up. Only used
rem right after installing, when PATH in this window is still the old one.
:find_python_installed
if exist "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" (
    set "PYEXE=%LOCALAPPDATA%\Programs\Python\Launcher\py.exe"
    set "PYARGS=-3"
    goto :eof
)
for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*") do call :try_python "%%d\python.exe"
goto :eof
