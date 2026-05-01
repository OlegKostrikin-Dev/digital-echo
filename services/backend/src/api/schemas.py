"""Pydantic-схемы для FastAPI ответов."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ----------------------------------------------------------------- state


class StateMeta(BaseModel):
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    days: Optional[int] = None
    raw_edges: Optional[int] = None
    edges_after_filter: Optional[int] = None
    edges_dropped: Optional[int] = None
    nodes: Optional[int] = None
    voltdb: Optional[dict[str, Any]] = None
    compute: Optional[dict[str, Any]] = None
    empty: Optional[bool] = None


class StateResponse(BaseModel):
    status: str = Field(..., description="idle | computing | ready | error")
    days: Optional[int] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    error: Optional[str] = None
    meta: Optional[StateMeta] = None
    readonly: bool = Field(
        False,
        description="True, если сервис запущен в режиме snapshot (без доступа к БД).",
    )
    snapshot_saved_at: Optional[str] = Field(
        None,
        description="Когда был сделан загруженный snapshot (только в readonly-режиме).",
    )


# ----------------------------------------------------------------- aggregate


class AggregateResponse(BaseModel):
    sellers_count: int
    total_sales: float
    import_value: float
    domestic_value: float
    import_share_pct: float
    domestic_share_pct: float


# --------------------------------------------------------------- distribution


class HistogramBucket(BaseModel):
    label: str
    count: int
    pct: float


class DistributionSummary(BaseModel):
    mean: float
    std: float
    min: float
    p25: float
    p50: float
    p75: float
    max: float


class DistributionResponse(BaseModel):
    total: int
    histogram: list[HistogramBucket]
    summary: DistributionSummary


# --------------------------------------------------------------- top importers


class TopImporterRow(BaseModel):
    tin: str
    name: Optional[str] = None
    is_non_resident: bool
    kz: float
    sales: float
    import_value: float


# ----------------------------------------------------------------- list cases


class ImporterCase(BaseModel):
    tin: str
    name: Optional[str] = None
    sales: float
    buyers_count: int


class DependentCase(BaseModel):
    tin: str
    name: Optional[str] = None
    sales: float
    kz: float


class CleanCase(BaseModel):
    tin: str
    name: Optional[str] = None
    sales: float
    kz: float


class CycleMember(BaseModel):
    tin: str
    name: Optional[str] = None
    kz: float
    sales: float


class CycleCase(BaseModel):
    size: int
    members: list[CycleMember]


class ListCasesResponse(BaseModel):
    importers: list[ImporterCase]
    dependents: list[DependentCase]
    clean: list[CleanCase]
    cycles: list[CycleCase]


# --------------------------------------------------------------- company profile


class CompanyCard(BaseModel):
    tin: str
    name: Optional[str] = None
    is_non_resident: Optional[bool] = None
    in_degree: int
    out_degree: int
    role: str
    purchases: float
    sales: float
    kz: float
    import_value_in_sales: float


class SupplierRow(BaseModel):
    tin: str
    name: Optional[str] = None
    is_non_resident: bool
    weight: float
    share: float
    kz: float


class DirectImport(BaseModel):
    value: float
    share: float
    non_resident_suppliers_count: int


class BackwardLayer(BaseModel):
    level: int
    size: int
    avg_kz: float
    non_resident_count: int


class BackwardView(BaseModel):
    applicable: bool
    reason: Optional[str] = None
    suppliers: list[SupplierRow] = []
    suppliers_total: int = 0
    direct_import: Optional[DirectImport] = None
    layers: list[BackwardLayer] = []
    cone_size: int = 1
    cone_share: float = 0.0


class CustomerRow(BaseModel):
    tin: str
    name: Optional[str] = None
    weight: float
    share_in_buyer: float
    kz: float


class ForwardLayer(BaseModel):
    level: int
    size: int
    layer_sales: float
    avg_kz: float
    end_consumers: int


class ForwardView(BaseModel):
    applicable: bool
    reason: Optional[str] = None
    customers: list[CustomerRow] = []
    customers_total: int = 0
    layers: list[ForwardLayer] = []
    cone_size: int = 1
    cone_share: float = 0.0


class CompanyProfileResponse(BaseModel):
    card: CompanyCard
    backward: BackwardView
    forward: ForwardView


# ----------------------------------------------------------------- compute request


class RecomputeRequest(BaseModel):
    days: int = Field(90, ge=1, le=3650, description="Глубина периода в днях")
    force: bool = Field(False, description="Пересчитать, даже если параметры совпадают")
