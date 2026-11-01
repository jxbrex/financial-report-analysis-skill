@echo off
rem Deploy: mirror the skill source to the user-level skills directory.
rem Usage: run from repo root, or double-click. Chinese docs live in AGENTS.md;
rem keep this file ASCII-only (cmd.exe chokes on UTF-8 Chinese comments).
setlocal
set SRC=%~dp0bo-financial-analyzer
set DST=%USERPROFILE%\.agents\skills\bo-financial-analyzer
robocopy "%SRC%" "%DST%" /MIR /NFL /NDL /NJH /XD __pycache__
rem robocopy exit codes 0-7 mean success
if %ERRORLEVEL% LEQ 7 (echo Deployed to %DST%) else (echo Deploy failed & exit /b 1)
rem Purge stale __pycache__ in mirror: /XD blinds /MIR to pre-existing ones (pre-v0.0.17 leak)
for /d /r "%DST%" %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
rem Post-deploy verification: entry files must exist in the mirror
if not exist "%DST%\SKILL.md" (echo Verify failed: SKILL.md missing in mirror & exit /b 1)
if not exist "%DST%\scripts\calc.py" (echo Verify failed: scripts\calc.py missing in mirror & exit /b 1)
if not exist "%DST%\assets\report-template.html" (echo Verify failed: report-template.html missing in mirror & exit /b 1)
if exist "%DST%\scripts\__pycache__" (echo Verify failed: __pycache__ leaked into mirror & exit /b 1)
echo Verified: SKILL.md / calc.py / report-template.html present, no __pycache__
