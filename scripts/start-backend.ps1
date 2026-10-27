# AnyLearn 后端启动脚本
# 用法: powershell -File scripts\start-backend.ps1 [-Port 8000]
param(
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root '.venv'

if (-not (Test-Path $venv)) {
    Write-Host '[1/3] 创建虚拟环境...' -ForegroundColor Cyan
    python -m venv $venv
}
$pip = Join-Path $venv 'Scripts\pip.exe'
& $pip install -q -r (Join-Path $root 'backend\requirements.txt')

Write-Host "[2/3] 启动 FastAPI (http://127.0.0.1:$Port) ..." -ForegroundColor Cyan
$uvicorn = Join-Path $venv 'Scripts\uvicorn.exe'
& $uvicorn app.main:app --app-dir (Join-Path $root 'backend') --host 127.0.0.1 --port $Port
