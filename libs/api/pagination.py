"""统一分页参数与分页响应模型。"""

from __future__ import annotations

import math
from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field, computed_field

T = TypeVar("T")

MAX_PAGE_SIZE = 100


class PageParams(BaseModel):
    """分页参数（页码从 1 开始）。"""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=MAX_PAGE_SIZE)

    @property
    def limit(self) -> int:
        return self.page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def pagination_params(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE, description="每页条数（1-100）"),
) -> PageParams:
    """FastAPI 依赖：从 query string 解析分页参数。"""
    return PageParams(page=page, page_size=page_size)


class Page(BaseModel, Generic[T]):
    """统一分页响应：items + total + 页码信息。"""

    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_pages(self) -> int:
        return math.ceil(self.total / self.page_size) if self.page_size else 0

    @classmethod
    def build(cls, items: list[T], total: int, params: PageParams) -> "Page[T]":
        return cls(
            items=items,
            total=total,
            page=params.page,
            page_size=params.page_size,
        )
