from fastapi import APIRouter, Depends, HTTPException
import base64
import json
import urllib.request
import urllib.error
import uuid
from pydantic import BaseModel
from typing import Optional

from server.core import storage, config
from server.core.models import UserSettings, UserProfile, UserProfileResponse, GenerateAvatarRequest, GenerateAvatarResponse
from server.api.auth import get_current_user_code, get_current_user

router = APIRouter(prefix="/users", tags=["Users"])


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
        raise HTTPException(
            status_code=503,
            detail="Avatar generation requires configured Cloudflare AI credentials on the server."
        )

    endpoint = (
        f"https://api.cloudflare.com/client/v4/accounts/{config.CLOUDFLARE_ACCOUNT_ID}"
        f"/ai/run/{config.CLOUDFLARE_IMAGE_MODEL}"
    )
    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt must not be empty.")

    # Forward the user prompt as-is; if a style hint is needed, default to realism.
    payload = {"prompt": prompt, "style": "realism"}

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
            response_body = response.read()
            content_type = (response.headers.get("Content-Type") or "").lower()

        if "application/json" in content_type:
            result = json.loads(response_body.decode("utf-8"))

            if not result.get("success"):
                raise HTTPException(status_code=503, detail=f"Cloudflare AI error: {result.get('errors')}")

            image_data = result.get("result", {}).get("image")
            if not image_data:
                raise HTTPException(status_code=503, detail="Cloudflare AI did not return an image.")

            image_bytes = base64.b64decode(image_data)
        elif content_type.startswith("image/"):
            image_bytes = response_body
        else:
            raise HTTPException(
                status_code=503,
                detail=f"Unexpected avatar response format from Cloudflare (Content-Type: {content_type or 'unknown'})."
            )

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
