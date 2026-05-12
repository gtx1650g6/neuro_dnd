@echo off
setlocal

echo Neuro D^&D Gemini quick fix
echo ==========================

if not exist server\api\ai.py (
  echo ERROR: Run this file from the project root, next to server\api\ai.py.
  pause
  exit /b 1
)

if exist .venv\Scripts\activate (
  call .venv\Scripts\activate
) else (
  echo WARNING: .venv was not found. Using the current Python from PATH.
)

echo Removing deprecated Gemini SDK if it exists...
python -m pip uninstall -y google-generativeai google-ai-generativelanguage
echo Installing Google Gen AI SDK required by this project...
python -m pip install google-genai

if exist .env (
  copy /Y .env .env.bak >nul
  echo Existing .env backed up to .env.bak
) else (
  echo Creating new .env
  type nul > .env
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$path='.env';" ^
  "$lines=@(); if(Test-Path $path){$lines=Get-Content $path};" ^
  "function Set-EnvLine([string]$name,[string]$value){" ^
  "  $pattern='^'+[regex]::Escape($name)+'=';" ^
  "  $filtered=@($script:lines | Where-Object { $_ -notmatch $pattern });" ^
  "  $script:lines=$filtered + ($name+'='+$value);" ^
  "};" ^
  "Set-EnvLine 'GEMINI_MODEL' 'gemini-2.0-flash';" ^
  "Set-EnvLine 'GEMINI_FALLBACK_MODELS' 'gemini-2.0-flash,gemini-2.0-flash-exp,gemini-1.5-flash-latest';" ^
  "Set-Content -Path $path -Value $lines -Encoding UTF8;"

echo.
echo Gemini model settings repaired in .env:
findstr /B "GEMINI_MODEL= GEMINI_FALLBACK_MODELS=" .env

echo.
echo Verifying active AI module...
python -c "import importlib.util; from server.core import config; import server.api.ai as ai; print('AI module:', ai.__file__); print('Gemini model:', config.GEMINI_MODEL); print('Gemini fallbacks:', config.GEMINI_FALLBACK_MODELS); print('google-genai installed:', importlib.util.find_spec('google.genai') is not None)"

echo.
echo Done. Now run: run_dev.bat
pause
