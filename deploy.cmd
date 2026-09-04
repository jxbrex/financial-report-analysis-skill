@echo off
rem Deploy: mirror the skill source to the user-level skills directory.
rem Usage: run from repo root, or double-click. Chinese docs live in AGENTS.md;
rem keep this file ASCII-only (cmd.exe chokes on UTF-8 Chinese comments).
setlocal
set SRC=%~dp0financial-report-analysis
set DST=%USERPROFILE%\.agents\skills\financial-report-analysis
robocopy "%SRC%" "%DST%" /MIR /NFL /NDL /NJH
rem robocopy exit codes 0-7 mean success
if %ERRORLEVEL% LEQ 7 (echo Deployed to %DST%) else (echo Deploy failed & exit /b 1)
