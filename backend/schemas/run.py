"""Pydantic schemas for pipeline runs."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class CreateRunRequest(BaseModel):
    clients: List[str] = Field(..., min_length=1)
    geos: List[str] = Field(..., min_length=1)
    reports: List[str] = Field(..., min_length=1)
