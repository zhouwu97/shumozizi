@echo off
setlocal
if "%~1"=="" exit /b 2
matlab -batch "run('%~1')"
exit /b %ERRORLEVEL%
