@echo off
chcp 65001 > nul
echo ========================================
echo  🚀 AI-Wealth 智能财务管家
echo ========================================

:: 获取当前脚本所在目录（即后端根目录）
set "BACKEND_DIR=%~dp0"
:: 假设前端目录和后端目录平级，且名字叫 ai-wealth-frontend
set "FRONTEND_DIR=%BACKEND_DIR%..\ai-wealth-frontend"

echo [1/3] 启动后端...
cd /d "%BACKEND_DIR%"
docker-compose down
docker-compose up -d

echo [2/3] 启动前端...
cd /d "%FRONTEND_DIR%"
if not exist "node_modules" (
    echo 安装依赖...
    call npm install
)
start "AI-Wealth-Frontend" npm run dev

echo [3/3] 打开浏览器...
timeout /t 5 /nobreak > nul
start http://localhost:5173
pause