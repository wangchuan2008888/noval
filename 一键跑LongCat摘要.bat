@echo off
chcp 65001 >nul
echo ========================================================
echo   LongCat-2.0 批量摘要加速提交工具 (1905 ~ 2438章)
echo ========================================================
echo.
echo 正在运行 LongCat-2.0 深度摘要（已开启 5 线程并发加速，断点实时保存）...
echo 如需随时中断，可直接按 Ctrl+C，已处理进度会自动实时保存！
echo.
python batch_longcat_summarizer.py --start 1905 --end 2438 --workers 5
echo.
echo ========================================================
echo 正在自动更新合并数据并重建阅读网站...
python .agents/skills/novel-reading-guide/scripts/merge_batches.py --project guide-project.json --replace
python .agents/skills/novel-reading-guide/scripts/build_reading_site.py --project guide-project.json --output site --replace
echo.
echo 全部更新完成！请在浏览器中刷新 http://localhost:8000 查看效果！
pause
