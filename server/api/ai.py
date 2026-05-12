import importlib
import importlib.util
import json
import re

from fastapi import APIRouter, Depends, HTTPException

from server.core import config, image_generation
from server.core.models import (
    AICompleteRequest,
    AICompleteResponse,
    ImageGenerationRequest,
    ImageGenerationResponse,
)
from server.api.auth import get_current_user_code

router = APIRouter(prefix="/ai", tags=["AI"])

LEGACY_GEMINI_MODEL_ALIASES = {
    "gemini-pro": "gemini-2.0-flash",
    "models/gemini-pro": "gemini-2.0-flash",
    "gemini-1.5-flash": "gemini-2.0-flash",
    "models/gemini-1.5-flash": "gemini-2.0-flash",
    "gemini-1.5-pro": "gemini-2.0-flash",
    "models/gemini-1.5-pro": "gemini-2.0-flash",
}


class GeminiAPIError(Exception):
    def __init__(self, message: str, status_code: int = 503, retryable_model_error: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable_model_error = retryable_model_error


def normalize_gemini_model(model: str) -> str:
    normalized = LEGACY_GEMINI_MODEL_ALIASES.get(model.strip(), model.strip())
    if normalized.startswith("models/"):
        normalized = normalized.removeprefix("models/")
    return normalized


def get_configured_gemini_model() -> str:
    return normalize_gemini_model(config.GEMINI_MODEL or "gemini-2.0-flash")


def get_gemini_model_candidates() -> list[str]:
    candidates = [get_configured_gemini_model()]
    fallback_models = [m.strip() for m in config.GEMINI_FALLBACK_MODELS.split(",") if m.strip()]
    candidates.extend(normalize_gemini_model(model) for model in fallback_models)
    return list(dict.fromkeys(candidates))


def get_genai_module():
    if importlib.util.find_spec("google.genai") is None:
        raise GeminiAPIError(
            "The google-genai package is not installed. Run setup.bat again or install it with: "
            "python -m pip install google-genai",
            status_code=500,
        )
    return importlib.import_module("google.genai")


def is_retryable_gemini_model_error(error_message: str) -> bool:
    lowered = error_message.lower()
    return "404" in lowered and ("not found" in lowered or "not supported" in lowered)


def call_gemini_generate_content(prompt: str) -> str:
    tried_models: list[str] = []
    last_model_error: GeminiAPIError | None = None

    for model in get_gemini_model_candidates():
        tried_models.append(model)
        try:
            return call_gemini_model_generate_content(prompt, model)
        except GeminiAPIError as exc:
            if exc.retryable_model_error:
                last_model_error = exc
                print(f"Gemini model '{model}' is unavailable, trying next fallback model.")
                continue
            raise

    tried = ", ".join(tried_models)
    details = f" Last error: {last_model_error}" if last_model_error else ""
    raise GeminiAPIError(
        f"No configured Gemini model is available for generateContent. Tried: {tried}.{details}",
        status_code=502,
    )


def call_gemini_model_generate_content(prompt: str, model: str) -> str:
    try:
        genai = get_genai_module()
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        response = client.models.generate_content(model=model, contents=prompt)
    except GeminiAPIError:
        raise
    except Exception as exc:
        api_message = str(exc)
        if is_retryable_gemini_model_error(api_message):
            raise GeminiAPIError(
                f"Gemini model '{model}' is not available for generate_content. "
                "The server will try configured fallback models. "
                f"Original error: {api_message}",
                status_code=502,
                retryable_model_error=True,
            ) from exc
        raise GeminiAPIError(api_message, status_code=503) from exc

    response_text = getattr(response, "text", None)
    if not response_text:
        raise GeminiAPIError("Gemini response did not contain text.", status_code=502)
    return response_text


def parse_ai_response(response_text: str) -> AICompleteResponse:
    """
    Parses the raw text from the AI, separating the narrative
    from the structured JSON metadata block.
    """
    json_block_match = re.search(r"```json\n({.*?})\n```", response_text, re.DOTALL)

    text_content = response_text
    meta_data = None

    if json_block_match:
        json_str = json_block_match.group(1)
        text_content = response_text.replace(json_block_match.group(0), "").strip()
        try:
            meta_data = json.loads(json_str)
        except json.JSONDecodeError:
            print(f"Warning: Failed to parse JSON metadata from AI response: {json_str}")
            meta_data = {"error": "failed_to_parse_json"}

    return AICompleteResponse(text=text_content, meta=meta_data)


@router.post("/complete", response_model=AICompleteResponse)
async def get_ai_completion(
    request: AICompleteRequest,
    user_code: str = Depends(get_current_user_code)
):
    """
    Generates a response from the AI Dungeon Master.
    """
    if not config.GEMINI_API_KEY or config.GEMINI_API_KEY == "__PUT_YOUR_KEY_HERE__":
        raise HTTPException(
            status_code=500,
            detail="Gemini API key is not configured on the server."
        )

    # 1. Gather context
    campaign_details = await get_campaign_details(request.campaign_id, user_code)
    user_settings = await get_user_settings(user_code)

    try:
        with open(config.SYSTEM_PROMPT_FILE, 'r', encoding='utf-8') as f:
            system_prompt = f.read()
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="System prompt file not found.")

    # 2. Construct the prompt
    # The user already sends the message history, we just prepend the system prompt
    # and provide context variables.
    full_prompt_context = f"""
{system_prompt}

---
## Game Context
- Campaign Name: {campaign_details.meta.name}
- Tone: {campaign_details.meta.tone}
- Difficulty: {campaign_details.meta.difficulty}
- Language: {user_settings.language}
---
"""

    # 3. Call Gemini API
    final_prompt_list = [full_prompt_context]
    for msg in request.messages:
        final_prompt_list.append(f"**{msg.role.capitalize()}:** {msg.content}")

    try:
        response_text = call_gemini_generate_content("\n".join(final_prompt_list))
        return parse_ai_response(response_text)
    except GeminiAPIError as e:
        print(f"Error calling Gemini API: {e}")
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e



@router.post("/image", response_model=ImageGenerationResponse)
async def generate_scene_image(
    request: ImageGenerationRequest,
    user_code: str = Depends(get_current_user_code),
):
    """Generates a scene illustration from a text description using Cloudflare Workers AI."""
    if not config.CLOUDFLARE_ACCOUNT_ID:
        raise HTTPException(status_code=500, detail="Cloudflare account ID is not configured on the server.")
    if not config.CLOUDFLARE_API_TOKEN or config.CLOUDFLARE_API_TOKEN == "__PUT_YOUR_TOKEN_HERE__":
        raise HTTPException(status_code=500, detail="Cloudflare API token is not configured on the server.")

    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Image prompt cannot be empty.")

    prompt = image_generation.build_scene_prompt(request.prompt)

    try:
        image = image_generation.call_cloudflare_image_api(prompt=prompt, seed=request.seed, steps=request.steps)
    except image_generation.ImageGenerationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return ImageGenerationResponse(
        image=image,
        model=config.CLOUDFLARE_IMAGE_MODEL,
        prompt=prompt,
        seed=request.seed,
    )


# Need to import these from the other routers to avoid circular dependencies
from server.api.campaigns import get_campaign_details
from server.api.users import get_user_settings
