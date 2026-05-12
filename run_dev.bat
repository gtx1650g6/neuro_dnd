@echo off
call .venv\Scripts\activate
echo Starting server on http://0.0.0.0:8000
python -c "import importlib.util; from server.core import config; import server.api.ai as ai; print('AI module:', ai.__file__); print('Gemini model:', config.GEMINI_MODEL); print('Gemini fallbacks:', config.GEMINI_FALLBACK_MODELS); print('google-genai installed:', importlib.util.find_spec('google.genai') is not None)"
uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
