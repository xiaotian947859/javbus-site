@echo off
REM 本地一键：提交代码 + 推送到 GitHub + 远程服务器自动部署

REM ===== 第一次使用请先修改下面这几项配置 =====
set SERVER_USER=root
set SERVER_HOST=你的服务器IP或域名
set SERVER_PORT=22
set SERVER_WEB_ROOT=/www/wwwroot
set SERVER_PROJECT_DIR=javbus-site
set REPO_URL=https://github.com/xiaotian947859/javbus-site.git
REM 进程名称（如果你在服务器上用 supervisor 或 systemd 管理）
set SUPERVISOR_NAME=javbus-site
set SYSTEMD_SERVICE=javbus-site.service
REM ============================================

cd /d %~dp0

REM 提交说明，可通过第一个参数传入，否则用默认内容
set COMMIT_MSG=%1
if "%COMMIT_MSG%"=="" set COMMIT_MSG=update from deploy_server.bat

echo [1/3] 提交并推送代码到 GitHub...
git add .
git commit -m "%COMMIT_MSG%"
git push origin main
if errorlevel 1 (
    echo git push 失败，请检查错误信息。
    pause
    exit /b 1
)

echo [2/3] 通过 SSH 登录服务器，自动部署代码...
echo 如果提示 ssh 不是内部或外部命令，请先在 Windows 打开 OpenSSH 客户端功能。

ssh -p %SERVER_PORT% %SERVER_USER%@%SERVER_HOST% ^
 "cd %SERVER_WEB_ROOT% && \
 if [ ! -d %SERVER_PROJECT_DIR% ]; then \
   git clone %REPO_URL% %SERVER_PROJECT_DIR%; \
 fi && \
 cd %SERVER_PROJECT_DIR% && \
 python3 -m venv venv || true && \
 source venv/bin/activate && \
 pip install --upgrade pip && \
 pip install -r requirements.txt && \
 (supervisorctl restart %SUPERVISOR_NAME% || systemctl restart %SYSTEMD_SERVICE% || true)"

if errorlevel 1 (
    echo 远程部署命令执行可能失败，请检查服务器上的日志。
) else (
    echo [3/3] 部署完成，请在浏览器访问你的服务。
)

echo.
echo 完成，如需修改服务器信息，请编辑 deploy_server.bat 顶部的配置。
pause

