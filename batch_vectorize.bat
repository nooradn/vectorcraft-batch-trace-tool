@echo off
setlocal
cd /d "%~dp0"
python "%~dp0batch_vectorize.py" %*
if "%~1"=="" pause
