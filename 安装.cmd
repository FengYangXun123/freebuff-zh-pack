@echo off
setlocal EnableExtensions
rem freebuff-zh-pack launcher. ASCII-only content, goto-style, no parentheses
rem anywhere in this file - see devin case lessons: bare parens in echo text
rem corrupt cmd control flow even inside skipped blocks.
rem Path candidates containing spaces are converted to short (8.3) paths so
rem that unquoted %PYEXE% expansion stays safe; "py -3" needs no quoting.
set "PACK=%~dp0"
set "PYEXE="
set "PYOUT=%TEMP%\freebuff_zh_pyver.txt"
set "STEP="

rem candidate 0: explicit override, short-path converted
if defined FREEBUFF_PYTHON for %%I in ("%FREEBUFF_PYTHON%") do set "PYEXE=%%~sI"
if defined PYEXE goto validate
rem candidate 1: pymanager layout, short-path converted
if exist "%LOCALAPPDATA%\Python\bin\python.exe" for %%I in ("%LOCALAPPDATA%\Python\bin\python.exe") do set "PYEXE=%%~sI"
if defined PYEXE goto validate
rem candidate 2: py launcher
set "STEP=py"
where py >nul 2>nul
if errorlevel 1 goto try_python
set "PYEXE=py -3"
goto validate

:try_python
rem candidate 3: python on PATH
if "%STEP%"=="python" goto no_python
set "STEP=python"
where python >nul 2>nul
if errorlevel 1 goto no_python
set "PYEXE=python"
goto validate

:validate
rem content check: interpreter must really answer with "Python 3"; this
rem rejects the Microsoft Store stub that only prints a banner
%PYEXE% -V > "%PYOUT%" 2>&1
findstr /b /c:"Python 3" "%PYOUT%" >nul
if errorlevel 1 goto bad_python
goto run

:bad_python
if "%STEP%"=="py" goto try_python
if "%STEP%"=="python" goto no_python
rem explicit override or pymanager path failed validation
echo Found interpreter did not pass check:
type "%PYOUT%"
echo.
if defined FREEBUFF_PYTHON echo Your FREEBUFF_PYTHON setting failed validation.
goto no_python

:no_python
echo Python 3 was not found on this machine.
echo Please install Python 3 from python.org, then run this file again.
echo Advanced: set FREEBUFF_PYTHON to the full path of python.exe.
echo           Paths with spaces are supported, converted to short paths.
pause
exit /b 1

:run
%PYEXE% "%PACK%install.py" --menu
