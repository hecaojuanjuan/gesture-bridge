@echo off
cd /d C:\Users\jiawa\Desktop\gesture-bridge
echo 正在烧录固件...
C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe tools\build.py headvoice flash --port COM3
pause
