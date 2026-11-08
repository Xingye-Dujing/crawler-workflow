@echo off
rem Console entry point the Inno installer puts on the user's HKCU PATH.
rem Forward every argument (notably --doctor) and keep the child's exit code;
rem do not use "start": a terminal must wait for the console EXE it launched.
"%~dp0..\CaiXiHui.exe" %*
exit /b %ERRORLEVEL%
