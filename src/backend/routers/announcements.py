"""Announcement management endpoints for the High School Management System API."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4
import re

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..database import announcements_collection, teachers_collection

router = APIRouter(
    prefix="/announcements",
    tags=["announcements"],
)


class AnnouncementInput(BaseModel):
    """Payload used to create or update an announcement."""

    title: str = Field(min_length=3, max_length=120)
    message: str = Field(min_length=5, max_length=500)
    starts_at: Optional[str] = None
    expires_at: str


def _normalize_iso_datetime(value: Optional[str], field_name: str) -> Optional[str]:
    """Validate ISO datetime string and normalize to second precision."""
    if value is None or value == "":
        return None

    normalized_value = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized_value)
        return parsed.isoformat(timespec="seconds")
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid datetime for {field_name}. Use ISO format.",
        ) from exc


def _require_authenticated_teacher(username: Optional[str]) -> Dict[str, Any]:
    """Validate that management requests are made by an authenticated teacher."""
    if not username:
        raise HTTPException(status_code=401, detail="Authentication required")

    teacher = teachers_collection.find_one({"_id": username})
    if not teacher:
        raise HTTPException(status_code=401, detail="Invalid teacher credentials")

    return teacher


def _serialize_announcement(document: Dict[str, Any]) -> Dict[str, Any]:
    """Convert MongoDB document to API output format."""
    return {
        "id": document["_id"],
        "title": document["title"],
        "message": document["message"],
        "starts_at": document.get("starts_at"),
        "expires_at": document["expires_at"],
        "created_by": document.get("created_by"),
        "updated_at": document.get("updated_at"),
    }


def _build_announcement_id(title: str) -> str:
    """Generate a readable unique identifier for announcement records."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    short_suffix = uuid4().hex[:8]
    return f"{slug or 'announcement'}-{short_suffix}"


@router.get("/active", response_model=List[Dict[str, Any]])
def get_active_announcements() -> List[Dict[str, Any]]:
    """Get announcements currently visible to all users based on date windows."""
    now = datetime.now().isoformat(timespec="seconds")

    query = {
        "expires_at": {"$gt": now},
        "$or": [
            {"starts_at": None},
            {"starts_at": {"$lte": now}},
        ],
    }

    documents = announcements_collection.find(query).sort(
        [
            ("starts_at", 1),
            ("expires_at", 1),
        ]
    )

    return [_serialize_announcement(doc) for doc in documents]


@router.get("", response_model=List[Dict[str, Any]])
def get_all_announcements(teacher_username: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """List all announcements for management, including future and expired items."""
    _require_authenticated_teacher(teacher_username)

    documents = announcements_collection.find({}).sort([("expires_at", 1)])
    return [_serialize_announcement(doc) for doc in documents]


@router.post("", response_model=Dict[str, Any])
def create_announcement(
    payload: AnnouncementInput,
    teacher_username: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Create a new announcement. Expiration date is required."""
    teacher = _require_authenticated_teacher(teacher_username)

    starts_at = _normalize_iso_datetime(payload.starts_at, "starts_at")
    expires_at = _normalize_iso_datetime(payload.expires_at, "expires_at")

    if not expires_at:
        raise HTTPException(status_code=400, detail="expires_at is required")

    if starts_at and starts_at >= expires_at:
        raise HTTPException(
            status_code=400,
            detail="expires_at must be greater than starts_at",
        )

    now = datetime.now().isoformat(timespec="seconds")
    new_announcement = {
        "_id": _build_announcement_id(payload.title),
        "title": payload.title.strip(),
        "message": payload.message.strip(),
        "starts_at": starts_at,
        "expires_at": expires_at,
        "created_by": teacher["_id"],
        "updated_at": now,
    }

    announcements_collection.insert_one(new_announcement)

    return _serialize_announcement(new_announcement)


@router.put("/{announcement_id}", response_model=Dict[str, Any])
def update_announcement(
    announcement_id: str,
    payload: AnnouncementInput,
    teacher_username: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Update an existing announcement by its identifier."""
    _require_authenticated_teacher(teacher_username)

    starts_at = _normalize_iso_datetime(payload.starts_at, "starts_at")
    expires_at = _normalize_iso_datetime(payload.expires_at, "expires_at")

    if not expires_at:
        raise HTTPException(status_code=400, detail="expires_at is required")

    if starts_at and starts_at >= expires_at:
        raise HTTPException(
            status_code=400,
            detail="expires_at must be greater than starts_at",
        )

    now = datetime.now().isoformat(timespec="seconds")
    update_payload = {
        "title": payload.title.strip(),
        "message": payload.message.strip(),
        "starts_at": starts_at,
        "expires_at": expires_at,
        "updated_at": now,
    }

    result = announcements_collection.update_one(
        {"_id": announcement_id},
        {"$set": update_payload},
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    updated = announcements_collection.find_one({"_id": announcement_id})
    if not updated:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return _serialize_announcement(updated)


@router.delete("/{announcement_id}")
def delete_announcement(
    announcement_id: str,
    teacher_username: Optional[str] = Query(None),
) -> Dict[str, str]:
    """Delete an existing announcement by its identifier."""
    _require_authenticated_teacher(teacher_username)

    result = announcements_collection.delete_one({"_id": announcement_id})

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement deleted successfully"}
