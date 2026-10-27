@echo off
chcp 65001 >nul
title AnyLearn 学习系统
cd /d %~dp0
echo ============================================
echo   AnyLearn 注入式学习框架  http://127.0.0.1:8000
echo   注入什么内容包，就变成什么学习系统
echo ============================================
powershell -ExecutionPolicy Bypass -File scripts\start-backend.ps1
pause
