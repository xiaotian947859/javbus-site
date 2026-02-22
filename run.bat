@echo off
cd /d %~dp0

echo [1/3] 检查并创建虚拟环境 venv...
if not exist venv (
    python -m venv venv
)

echo [2/3] 激活虚拟环境并安装依赖...
call venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements.txt

echo [3/3] 启动网站 viewer.py ...
python viewer.py

echo.
echo 已退出 viewer.py，可按任意键关闭窗口。
pause>nul

