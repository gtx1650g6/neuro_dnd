import uuid
from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import Response
from starlette import status

from server.core import storage
from server.core.models import (
    CreateCampaignRequest, CampaignMeta, CampaignJournal,
    CampaignDetailsResponse, AddJournalEntryRequest
)
from server.api.auth import get_current_user_code

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])


@router.post("", response_model=CampaignMeta)
async def create_campaign(
    request: CreateCampaignRequest,
    user_code: str = Depends(get_current_user_code)
):
    """Creates a new campaign for the logged-in user."""
    new_campaign_meta = CampaignMeta(
        name=request.name,
        tone=request.tone,
        difficulty=request.difficulty,
        host_user_code=user_code,
    )

    initial_journal = CampaignJournal()
    storage.create_campaign(new_campaign_meta, initial_journal)

    return new_campaign_meta


@router.get("", response_model=list[CampaignMeta])
async def list_user_campaigns(user_code: str = Depends(get_current_user_code)):
    """Lists all campaigns belonging to the current user."""
    return storage.list_campaigns(user_code)


@router.get("/{campaign_id}", response_model=CampaignDetailsResponse)
async def get_campaign_details(
    campaign_id: str,
    user_code: str = Depends(get_current_user_code)
):
    """Retrieves the metadata and journal for a specific campaign."""
    try:
        uuid.UUID(campaign_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid campaign ID format.")

    campaign = storage.get_campaign(user_code, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    meta, journal = campaign
    return CampaignDetailsResponse(meta=meta, journal=journal)


@router.post("/{campaign_id}/journal", response_model=CampaignJournal)
async def add_journal_entry(
    campaign_id: str,
    request: AddJournalEntryRequest,
    user_code: str = Depends(get_current_user_code)
):
    """Adds a new entry to the campaign's journal."""
    try:
        uuid.UUID(campaign_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid campaign ID format.")

    journal = storage.append_campaign_journal_entry(user_code, campaign_id, request.message.dict())
    if journal is None:
        raise HTTPException(status_code=404, detail="Campaign journal not found.")

    return journal


@router.post("/{campaign_id}/checkpoint")
async def save_campaign_checkpoint(
    campaign_id: str,
    user_code: str = Depends(get_current_user_code)
):
    """Saves a snapshot of the current campaign state."""
    campaign_details = await get_campaign_details(campaign_id, user_code)
    timestamp = storage.save_campaign_checkpoint(user_code, campaign_id, campaign_details.dict())

    return {"message": "Checkpoint saved successfully", "timestamp": timestamp}


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    campaign_id: str,
    user_code: str = Depends(get_current_user_code)
):
    """Deletes a user's campaign, including all its data."""
    try:
        uuid.UUID(campaign_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid campaign ID format.")

    deleted = storage.delete_campaign(user_code, campaign_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    return Response(status_code=status.HTTP_204_NO_CONTENT)
