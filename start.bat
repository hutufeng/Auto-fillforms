@echo off
chcp 65001 >nul
title 身份证智能录入与扫描助手

set PYTHON_CMD=

if exist "C:\Users\hutu_\AppData\Local\Programs\Python\Python310\python.exe" (
    set PYTHON_CMD="C:\Users\hutu_\AppData\Local\Programs\Python\Python310\python.exe"
    goto run
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=py -3
    goto run
)

where python >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=python
    goto run
)

echo [ERROR] Python environment not found! Please ensure Python 3.10+ is installed.
pause
exit /b 1

:run
%PYTHON_CMD% run_desktop.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Application exited with error code %errorlevel%.
    pause
)
