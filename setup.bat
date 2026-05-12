@echo off
echo Neuro D^&D setup version: google-genai
echo Creating virtual environment...
python -m venv .venv
echo Activating virtual environment...
call .venv\Scripts\activate
echo Upgrading pip...
python -m pip install --upgrade pip
echo Installing dependencies from requirements.txt...
pip install -r requirements.txt
echo Removing deprecated Gemini SDK if it exists...
pip uninstall -y google-generativeai google-ai-generativelanguage
echo Ensuring Google Gen AI SDK is installed...
pip install google-genai
echo Creating .env file...
echo GEMINI_API_KEY=__PUT_YOUR_KEY_HERE__> .env
echo GEMINI_MODEL=gemini-2.0-flash>> .env
echo GEMINI_FALLBACK_MODELS=gemini-2.0-flash,gemini-2.0-flash-exp,gemini-1.5-flash-latest>> .env
echo CLOUDFLARE_ACCOUNT_ID=__PUT_YOUR_ACCOUNT_ID_HERE__>> .env
echo CLOUDFLARE_API_TOKEN=__PUT_YOUR_TOKEN_HERE__>> .env
echo CLOUDFLARE_IMAGE_MODEL=@cf/black-forest-labs/flux-1-schnell>> .env
echo CLOUDFLARE_IMAGE_STEPS=4>> .env
echo.
echo Setup complete. Please edit the .env file and add your GEMINI_API_KEY and Cloudflare Workers AI credentials.
pause
