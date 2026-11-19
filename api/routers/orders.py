from typing import Annotated

from fastapi import APIRouter, Header, Response, status

from dependencies import CurrentUser, OrderServiceDep
from schemas.order import OrderCreate, OrderResponse

router = APIRouter()


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    data: OrderCreate,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=100)],
    service: OrderServiceDep,
    current_user: CurrentUser,
    response: Response,
):
    order = await service.create(current_user.id, data, idempotency_key)
    response.headers["Location"] = f"/v1/orders/{order.id}"
    return order


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(order_id: int, service: OrderServiceDep, current_user: CurrentUser):
    return await service.get_by_id(order_id, current_user.id)


@router.post("/{order_id}/accept", response_model=OrderResponse)
async def accept_order(order_id: int, service: OrderServiceDep, current_user: CurrentUser):
    return await service.accept(order_id, current_user.id)
