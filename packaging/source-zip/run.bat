@echo off
chcp 65001 >nul
rem MyFinSight 스크립트 버전 (Windows). 파이썬 3.11 이상이 깔려 있어야 한다.
rem 처음 한 번만 이 폴더의 .venv 에 라이브러리를 받고, 그다음부터는 바로 켠다.
setlocal
cd /d "%~dp0"

if exist ".venv\installed.txt" goto run

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" || goto oldpython

echo.
echo [MyFinSight] 처음 실행입니다. 필요한 라이브러리를 받습니다. 몇 분 걸립니다.
echo.
%PY% -m venv .venv || goto failed
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto failed
echo ok> ".venv\installed.txt"

:run
".venv\Scripts\python.exe" packaging\launcher.py %*
goto end

:nopython
echo [MyFinSight] 파이썬을 찾지 못했습니다. https://www.python.org/downloads/ 에서 3.11 이상을 설치해 주세요.
echo              설치 화면에서 "Add python.exe to PATH" 를 체크해야 합니다.
goto wait

:oldpython
echo [MyFinSight] 파이썬 3.11 이상이 필요합니다. 지금 버전:
%PY% --version
goto wait

:failed
echo.
echo [MyFinSight] 설치하지 못했습니다. 위의 오류를 확인해 주세요.

:wait
pause

:end
endlocal
