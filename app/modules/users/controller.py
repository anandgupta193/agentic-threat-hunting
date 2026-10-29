"""HTTP layer for users. Creating a user needs no X-User-Id (D23)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.modules.users.dtos import CreateUserRequest, UserDTO
from app.modules.users.service import UserService

router = APIRouter(prefix="/v1", tags=["users"])


def get_user_service(request: Request) -> UserService:
    return request.app.state.user_service


@router.post("/users", response_model=UserDTO, status_code=201)
async def create_user(
    body: CreateUserRequest,
    service: Annotated[UserService, Depends(get_user_service)],
) -> UserDTO:
    return await service.create(body)
