@echo off
chcp 65001 >nul
echo ========================================================
echo   正在启动《谁说没灵根不能修仙的？》本地静态阅读网站...
echo ========================================================
echo.
echo 正在打开浏览器: http://localhost:8000
start http://localhost:8000
echo.
echo 静态服务器已运行（按 Ctrl+C 可停止服务）：
python -m http.server 8000 --directory site
pause
