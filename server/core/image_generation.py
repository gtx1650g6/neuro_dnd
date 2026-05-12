import base64
import json
import urllib.error
import urllib.request

from server.core import config


class ImageGenerationError(Exception):
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


def ensure_cloudflare_configured() -> None:
    if not config.CLOUDFLARE_ACCOUNT_ID:
        raise ImageGenerationError("Cloudflare account ID is not configured on the server.")
    if not config.CLOUDFLARE_API_TOKEN or config.CLOUDFLARE_API_TOKEN == "__PUT_YOUR_TOKEN_HERE__":
        raise ImageGenerationError("Cloudflare API token is not configured on the server.")


def normalize_steps(steps: int | None) -> int:
    selected_steps = steps or config.CLOUDFLARE_IMAGE_STEPS
    return max(1, min(selected_steps, 8))


def build_scene_prompt(prompt: str) -> str:
    """Adds a consistent fantasy art direction and keeps Cloudflare's prompt limit."""
    style_suffix = (
        "\n\nFantasy tabletop RPG scene, cinematic composition, epic medieval atmosphere, "
        "realistic textures, high detail, dramatic lighting."
    )
    full_prompt = f"{prompt.strip()}{style_suffix}"
    return full_prompt[:2048]


def build_avatar_prompt(prompt: str) -> str:
    """Builds a portrait prompt for player character avatars."""
    style_suffix = (
        "\n\nSingle fantasy RPG character portrait, centered bust, clear face, "
        "neutral dark background, dramatic rim lighting, detailed costume, "
        "high detail, realistic fantasy concept art, no text, no watermark."
    )
    full_prompt = f"{prompt.strip()}{style_suffix}"
    return full_prompt[:2048]


def extract_cloudflare_image(response_body: bytes, content_type: str) -> str:
    """Returns an image data URI from either JSON or raw image responses."""
    if content_type.startswith("image/"):
        image_base64 = base64.b64encode(response_body).decode("utf-8")
        return f"data:{content_type};base64,{image_base64}"

    payload = json.loads(response_body.decode("utf-8"))
    result = payload.get("result", payload)

    image_value = result.get("image") or result.get("dataURI") or result.get("data_uri")
    if not image_value:
        raise ImageGenerationError("Cloudflare response does not contain an image.", status_code=502)

    if image_value.startswith("data:image"):
        return image_value
    return f"data:image/jpeg;charset=utf-8;base64,{image_value}"


def call_cloudflare_image_api(prompt: str, seed: int | None = None, steps: int | None = None) -> str:
    ensure_cloudflare_configured()

    url = (
        f"https://api.cloudflare.com/client/v4/accounts/"
        f"{config.CLOUDFLARE_ACCOUNT_ID}/ai/run/{config.CLOUDFLARE_IMAGE_MODEL}"
    )
    body: dict[str, object] = {"prompt": prompt, "steps": normalize_steps(steps)}
    if seed is not None:
        body["seed"] = seed

    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.CLOUDFLARE_API_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            response_body = response.read()
            content_type = response.headers.get("Content-Type", "application/json").split(";")[0]
            return extract_cloudflare_image(response_body, content_type)
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise ImageGenerationError(f"Cloudflare image API error: {error_body}", status_code=502) from exc
    except urllib.error.URLError as exc:
        raise ImageGenerationError(f"Cloudflare image API is unavailable: {exc.reason}", status_code=503) from exc
    except json.JSONDecodeError as exc:
        raise ImageGenerationError(f"Unexpected Cloudflare image response: {exc}", status_code=502) from exc
