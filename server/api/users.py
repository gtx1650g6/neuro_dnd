import mimetypes
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.responses import FileResponse

from server.core import image_generation, storage
from server.core.models import AvatarGenerationRequest, UserSettings, UserProfile, UserProfileResponse
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


@router.post("/avatar/generate", response_model=UserProfileResponse)
async def generate_user_avatar(
    request: AvatarGenerationRequest,
    current_user: UserProfile = Depends(get_current_user),
):
    """Generates, stores, and applies a character avatar for the current user."""
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Avatar prompt cannot be empty.")

    prompt = image_generation.build_avatar_prompt(request.prompt)
    try:
        image_data_uri = image_generation.call_cloudflare_image_api(
            prompt=prompt,
            seed=request.seed,
            steps=request.steps,
        )
    except image_generation.ImageGenerationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    avatar_url = storage.save_user_avatar_image(current_user.user_code, image_data_uri)
    updated_user = current_user.copy(update={"avatar_url": avatar_url})
    storage.save_user_profile(updated_user.dict())
    return updated_user


@router.get("/{user_code}/avatar")
async def get_user_avatar(user_code: str):
    """Serves a stored generated avatar image."""
    if not storage.user_exists(user_code):
        raise HTTPException(status_code=404, detail="User not found.")

    avatar_path = storage.get_user_avatar_file(user_code)
    if not avatar_path:
        raise HTTPException(status_code=404, detail="Avatar not found.")

    media_type = mimetypes.guess_type(avatar_path.name)[0] or "image/jpeg"
    return FileResponse(avatar_path, media_type=media_type)


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
