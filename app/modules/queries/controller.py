"""HTTP layer for query generation: DTO in → service → DTO out."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.common.guards import read_user_id
from app.modules.queries.dtos import QueryRequest, QueryResponse
from app.modules.queries.service import QueryService

router = APIRouter(prefix="/v1", tags=["queries"])


def get_query_service(request: Request) -> QueryService:
    return request.app.state.query_service


@router.post("/queries", response_model=QueryResponse)
async def create_query(
    body: QueryRequest,
    user_id: Annotated[str, Depends(read_user_id)],
    service: Annotated[QueryService, Depends(get_query_service)],
) -> QueryResponse:
    return await service.generate(user_id, body)
