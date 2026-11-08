@echo off
rem Console entry point the Inno installer puts on the user's HKCU PATH.
rem The exe is windowed, so `start /wait` is what makes a terminal wait for it and keep its
rem exit code; `--doctor` attaches to this console and answers here.
start "" /wait "%~dp0..\CaiXiHui.exe" %*
exit /b %ERRORLEVEL%
