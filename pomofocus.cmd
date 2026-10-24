@echo off
setlocal
py -3 "%~dp0focus.py" %*
exit /b %ERRORLEVEL%
