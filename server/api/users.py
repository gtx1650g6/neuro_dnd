from fastapi import APIRouter, Depends, HTTPException
import base64
import json
import urllib.request
import urllib.error
import uuid
import hashlib
from pydantic import BaseModel
from typing import Optional

from server.core import storage, config
from server.core.models import UserSettings, UserProfile, UserProfileResponse, GenerateAvatarRequest, GenerateAvatarResponse
from server.api.auth import get_current_user_code, get_current_user

router = APIRouter(prefix="/users", tags=["Users"])


def _build_fallback_avatar_svg(seed: str) -> str:
    """Create a deterministic SVG avatar with varied geometry based on prompt seed."""
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()

    def h(offset: int, size: int = 2) -> int:
        return int(digest[offset:offset + size], 16)

    bg = f"#{digest[:6]}"
    skin = f"#{digest[6:12]}"
    hair = f"#{digest[12:18]}"
    accent = f"#{digest[18:24]}"
    clothing = f"#{digest[24:30]}"

    eye_style = h(30) % 3
    mouth_style = h(32) % 3
    accessory = h(34) % 4
    head_shape = h(36) % 3

    head = "<circle cx='128' cy='94' r='46' fill='{skin}' />"
    if head_shape == 1:
        head = "<rect x='84' y='50' width='88' height='88' rx='28' fill='{skin}' />"
    elif head_shape == 2:
        head = "<ellipse cx='128' cy='94' rx='50' ry='42' fill='{skin}' />"

    if eye_style == 0:
        eyes = "<circle cx='110' cy='92' r='5' fill='#111'/><circle cx='146' cy='92' r='5' fill='#111'/>"
    elif eye_style == 1:
        eyes = "<rect x='104' y='89' width='12' height='6' rx='3' fill='#111'/><rect x='140' y='89' width='12' height='6' rx='3' fill='#111'/>"
    else:
        eyes = "<path d='M102 93 Q110 86 118 93' stroke='#111' stroke-width='3' fill='none'/><path d='M138 93 Q146 86 154 93' stroke='#111' stroke-width='3' fill='none'/>"

    if mouth_style == 0:
        mouth = "<path d='M108 116 Q128 130 148 116' stroke='#111' stroke-width='4' fill='none' stroke-linecap='round'/>"
    elif mouth_style == 1:
        mouth = "<line x1='112' y1='118' x2='144' y2='118' stroke='#111' stroke-width='4' stroke-linecap='round'/>"
    else:
        mouth = "<path d='M108 124 Q128 108 148 124' stroke='#111' stroke-width='4' fill='none' stroke-linecap='round'/>"

    accessory_svg = ""
    if accessory == 0:
        accessory_svg = "<rect x='88' y='84' width='80' height='20' rx='10' fill='none' stroke='{accent}' stroke-width='6'/>"
    elif accessory == 1:
        accessory_svg = "<path d='M86 78 Q128 52 170 78' stroke='{accent}' stroke-width='10' fill='none' stroke-linecap='round'/>"
    elif accessory == 2:
        accessory_svg = "<circle cx='96' cy='92' r='8' fill='{accent}'/><circle cx='160' cy='92' r='8' fill='{accent}'/>"

    shoulder_width = 132 + (h(38) % 36)
    shoulder_x = (256 - shoulder_width) // 2
    shoulder_rx = 24 + (h(40) % 16)

    svg = f"""<svg xmlns='http://www.w3.org/2000/svg' width='256' height='256' viewBox='0 0 256 256'>
  <rect width='256' height='256' fill='{bg}' />
  <path d='M64 60 Q128 {30 + (h(42) % 26)} 192 60 L192 86 Q128 {50 + (h(44) % 22)} 64 86 Z' fill='{hair}' opacity='0.95'/>
  {head.format(skin=skin)}
  {eyes}
  {mouth}
  {accessory_svg.format(accent=accent) if accessory_svg else ''}
  <rect x='{shoulder_x}' y='154' width='{shoulder_width}' height='74' rx='{shoulder_rx}' fill='{clothing}' opacity='0.95' />
  <path d='M84 200 Q128 {150 + (h(46) % 40)} 172 200' stroke='{accent}' stroke-width='8' fill='none' stroke-linecap='round' opacity='0.8'/>
</svg>"""
    return svg

class UpdateProfileRequest(BaseModel):
    username: Optional[str] = None
    avatar_url: Optional[str] = None

@router.put("/profile", response_model=UserProfileResponse)
async def update_user_profile(
    request: UpdateProfileRequest,
    current_user: UserProfile = Depends(get_current_user)
):
    """Updates the current user's profile (e.g., username)."""
    updated_user = current_user.copy(update=request.dict(exclude_unset=True))

    storage.save_user_profile(updated_user.dict())

    # FastAPI will correctly serialize this to UserProfileResponse
    return updated_user


@router.get("/settings", response_model=UserSettings)
async def get_user_settings(user_code: str = Depends(get_current_user_code)):
    """
    Retrieves the current user's settings.
    If no settings file exists, returns default settings.
    """
    if not storage.user_exists(user_code):
        raise HTTPException(status_code=400, detail="Invalid user code format.")

    return storage.get_user_settings(user_code)


@router.put("/settings", response_model=UserSettings)
async def update_user_settings(
    settings: UserSettings,
    user_code: str = Depends(get_current_user_code)
):
    """
    Updates the current user's settings.
    """
    if not storage.user_exists(user_code):
        raise HTTPException(status_code=400, detail="Invalid user code format.")

    storage.save_user_settings(user_code, settings)
    return settings


@router.post("/avatar/generate", response_model=GenerateAvatarResponse)
async def generate_avatar(
    request: GenerateAvatarRequest,
    current_user: UserProfile = Depends(get_current_user)
):
    """Generate an avatar image from prompt, save it on disk, and update user profile."""
    if not config.CLOUDFLARE_API_TOKEN or not config.CLOUDFLARE_ACCOUNT_ID:
        avatar_name = f"{current_user.user_code}-{uuid.uuid4().hex[:10]}.svg"
        avatar_path = config.AVATARS_DIR / avatar_name
        svg_content = _build_fallback_avatar_svg(f"{current_user.user_code}:{request.prompt}")
        avatar_path.write_text(svg_content, encoding="utf-8")

        avatar_url = f"/assets/avatars/{avatar_name}"
        updated_user = current_user.copy(update={"avatar_url": avatar_url})
        storage.save_user_profile(updated_user.dict())

        return GenerateAvatarResponse(avatar_url=avatar_url)

    endpoint = (
        f"https://api.cloudflare.com/client/v4/accounts/{config.CLOUDFLARE_ACCOUNT_ID}"
        f"/ai/run/{config.CLOUDFLARE_IMAGE_MODEL}"
    )
    payload = {"prompt": request.prompt}

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.CLOUDFLARE_API_TOKEN}",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))

        if not result.get("success"):
            raise HTTPException(status_code=503, detail=f"Cloudflare AI error: {result.get('errors')}")

        image_data = result.get("result", {}).get("image")
        if not image_data:
            raise HTTPException(status_code=503, detail="Cloudflare AI did not return an image.")

        image_bytes = base64.b64decode(image_data)
        avatar_name = f"{current_user.user_code}-{uuid.uuid4().hex[:10]}.png"
        avatar_path = config.AVATARS_DIR / avatar_name
        avatar_path.write_bytes(image_bytes)

        avatar_url = f"/assets/avatars/{avatar_name}"
        updated_user = current_user.copy(update={"avatar_url": avatar_url})
        storage.save_user_profile(updated_user.dict())

        return GenerateAvatarResponse(avatar_url=avatar_url)

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="ignore")
        raise HTTPException(status_code=503, detail=f"Cloudflare request failed: {error_body}")
    except urllib.error.URLError as e:
        raise HTTPException(status_code=503, detail=f"Cloudflare network error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Avatar service error: {str(e)}")
