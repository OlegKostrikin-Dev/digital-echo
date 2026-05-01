"""HTTP-роуты digital-echo-core API."""

from __future__ import annotations

import os
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
)

from ..core import analytics
from ..deps import GraphState, get_state
from ..auth.routes import get_optional_user
from . import schemas

router = APIRouter(prefix="/api", tags=["analytics"])


# ------------------------------------------------------------------ health


@router.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


# ------------------------------------------------------------------ state


@router.get("/state", response_model=schemas.StateResponse, tags=["state"])
def get_state_snapshot(
    state: Annotated[GraphState, Depends(get_state)],
) -> dict:
    return state.snapshot()


@router.post("/recompute", response_model=schemas.StateResponse, tags=["state"])
async def recompute(
    payload: schemas.RecomputeRequest,
    state: Annotated[GraphState, Depends(get_state)],
) -> dict:
    """Запустить полный пересчёт графа и индекса КС.

    Ожидаемое время — ~80 секунд на 90 дней / 100K узлов.
    Запрос блокирующий: возвращается, когда расчёт завершён или упал.
    Если граф уже посчитан с такими же параметрами — возвращает текущий снимок.
    В режиме READONLY_SNAPSHOT всегда возвращает 503.
    """
    if state.readonly:
        raise HTTPException(
            status_code=503,
            detail=(
                "Сервис запущен в режиме демо-снимка (READONLY_SNAPSHOT). "
                "Перерасчёт недоступен. Доступны все запросы на чтение."
            ),
        )
    return await state.recompute(days=payload.days, force=payload.force)


# ------------------------------------------------------------------ guard


def _ensure_ready(state: GraphState) -> None:
    if not state.is_ready:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Граф не готов (status={state.snapshot()['status']}). "
                "Запустите POST /api/recompute"
            ),
        )


# ------------------------------------------------------------------ aggregate


@router.get("/aggregate", response_model=schemas.AggregateResponse)
def get_aggregate(
    state: Annotated[GraphState, Depends(get_state)],
) -> dict:
    _ensure_ready(state)
    return analytics.compute_aggregate(state.kz, state.graph)


# --------------------------------------------------------------- distribution


@router.get("/distribution", response_model=schemas.DistributionResponse)
def get_distribution(
    state: Annotated[GraphState, Depends(get_state)],
) -> dict:
    _ensure_ready(state)
    return analytics.compute_distribution(state.kz)


# --------------------------------------------------------------- top importers


@router.get("/top-importers", response_model=list[schemas.TopImporterRow])
def get_top_importers(
    state: Annotated[GraphState, Depends(get_state)],
    n: int = Query(10, ge=1, le=100),
) -> list:
    _ensure_ready(state)
    return analytics.compute_top_importers(state.kz, state.graph, n=n)


# ----------------------------------------------------------------- list cases


@router.get("/list-cases", response_model=schemas.ListCasesResponse)
def get_list_cases(
    state: Annotated[GraphState, Depends(get_state)],
    n: int = Query(5, ge=1, le=20),
) -> dict:
    _ensure_ready(state)
    return analytics.compute_list_cases(state.kz, state.graph, n=n)


# ---------------------------------------------------------------- company


@router.get("/company/{bin}", response_model=schemas.CompanyProfileResponse)
def get_company_profile(
    state: Annotated[GraphState, Depends(get_state)],
    bin: str = Path(..., min_length=1, max_length=12, description="БИН/ИИН"),
) -> dict:
    _ensure_ready(state)
    profile = analytics.compute_company_profile(state.kz, state.graph, target=bin)
    if profile is None:
        raise HTTPException(
            status_code=404,
            detail=f"Узел {bin!r} отсутствует в графе за текущий период.",
        )
    return profile


# -------------------------------------------------------------------- admin


@router.post("/admin/save-snapshot", tags=["admin"])
def admin_save_snapshot(
    request: Request,
    state: Annotated[GraphState, Depends(get_state)],
    x_admin_token: Annotated[Optional[str], Header()] = None,
    path: Optional[str] = Query(
        None, description="Куда писать (по умолчанию SNAPSHOT_PATH)."
    ),
) -> dict:
    """Сериализовать текущее состояние графа в pickle-файл.

    Доступ: заголовок X-Admin-Token (если задан ADMIN_TOKEN в окружении)
    **или** cookie-сессия с ролью admin (см. /api/auth).
    """
    expected = os.getenv("ADMIN_TOKEN")
    allowed = bool(expected and x_admin_token == expected)
    if not allowed:
        u = get_optional_user(request)
        if u and u.get("role") == "admin":
            allowed = True
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="Нужны права администратора или валидный X-Admin-Token.",
        )
    _ensure_ready(state)
    written = state.save_to_disk(path)
    return {
        "written": str(written),
        "size_bytes": written.stat().st_size,
    }
