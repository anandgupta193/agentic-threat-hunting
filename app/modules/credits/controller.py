"""HTTP layer for credits: a caller may read only their own credits and usage (403 otherwise)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.common.guards import require_self
from app.modules.credits.dtos import CreditsDTO, UsageDTO
from app.modules.credits.service import CreditService

router = APIRouter(prefix="/v1/users", tags=["credits"])


def get_credit_service(request: Request) -> CreditService:
    return request.app.state.credit_service


@router.get("/{user_id}/credits", response_model=CreditsDTO)
async def get_credits(
    user_id: Annotated[str, Depends(require_self)],
    service: Annotated[CreditService, Depends(get_credit_service)],
) -> CreditsDTO:
    return await service.get_credits(user_id)


@router.get("/{user_id}/usage", response_model=UsageDTO)
async def get_usage(
    user_id: Annotated[str, Depends(require_self)],
    service: Annotated[CreditService, Depends(get_credit_service)],
) -> UsageDTO:
    return await service.get_usage(user_id)
