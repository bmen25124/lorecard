from datetime import datetime
from enum import Enum
import json
from typing import Any, Dict, List, Optional, Union
from uuid import UUID, uuid4

from db.connection import get_db_connection
from db.common import PaginatedResponse, PaginationMeta
from pydantic import BaseModel, ValidationError, field_validator

from db.database import AsyncDBTransaction
from logging_config import get_logger

logger = get_logger(__name__)


class JobStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"
    cancelling = "cancelling"
    canceled = "canceled"


class TaskName(str, Enum):
    DISCOVER_AND_CRAWL_SOURCES = "discover_and_crawl_sources"
    CONFIRM_LINKS = "confirm_links"
    PROCESS_PROJECT_ENTRIES = "process_project_entries"
    GENERATE_SEARCH_PARAMS = "generate_search_params"
    RESCAN_LINKS = "rescan_links"
    FETCH_SOURCE_CONTENT = "fetch_source_content"
    GENERATE_CHARACTER_CARD = "generate_character_card"
    REGENERATE_CHARACTER_FIELD = "regenerate_character_field"


PARALLEL_LIMITS = {
    TaskName.DISCOVER_AND_CRAWL_SOURCES: 1,
    TaskName.CONFIRM_LINKS: 1,
    TaskName.PROCESS_PROJECT_ENTRIES: 1,
    TaskName.GENERATE_SEARCH_PARAMS: 1,
    TaskName.RESCAN_LINKS: 1,
    TaskName.FETCH_SOURCE_CONTENT: 1,
    TaskName.GENERATE_CHARACTER_CARD: 1,
    TaskName.REGENERATE_CHARACTER_FIELD: 1,
}


# Payloads
class DiscoverAndCrawlSourcesPayload(BaseModel):
    source_ids: List[UUID]


class ConfirmLinksPayload(BaseModel):
    urls: List[str]


class ProcessProjectEntriesPayload(BaseModel):
    link_ids: Optional[List[UUID]] = None


class GenerateSearchParamsPayload(BaseModel):
    pass


class FetchSourceContentPayload(BaseModel):
    source_ids: List[UUID]


class GenerateCharacterCardPayload(BaseModel):
    source_ids: Optional[List[UUID]] = None


class RegenerateCharacterFieldContextOptions(BaseModel):
    include_existing_fields: bool
    source_ids_to_include: List[UUID]


class RegenerateCharacterFieldPayload(BaseModel):
    field_to_regenerate: str
    custom_prompt: Optional[str] = None
    context_options: RegenerateCharacterFieldContextOptions


TaskPayload = Union[
    DiscoverAndCrawlSourcesPayload,
    ConfirmLinksPayload,
    ProcessProjectEntriesPayload,
    GenerateSearchParamsPayload,
    FetchSourceContentPayload,
    GenerateCharacterCardPayload,
    RegenerateCharacterFieldPayload,
]


class DiscoverAndCrawlSourcesResult(BaseModel):
    new_links: List[str]
    existing_links: List[str]
    new_sources_created: int
    selectors_generated: int
    sources_failed: List[str] = []

    @field_validator("sources_failed", mode="before")
    def serialize_sources_failed(cls, v):
        if v is None:
            return []
        ls = []
        for uuid in v:
            ls.append(str(uuid))
        return ls


class ConfirmLinksResult(BaseModel):
    links_saved: int


class ProcessProjectEntriesResult(BaseModel):
    entries_created: int
    entries_failed: int
    entries_skipped: int


class GenerateSearchParamsResult(BaseModel):
    pass


class FetchSourceContentResult(BaseModel):
    sources_fetched: int
    sources_failed: int


class GenerateCharacterCardResult(BaseModel):
    pass


class RegenerateCharacterFieldResult(BaseModel):
    field_regenerated: str


TaskResult = Union[
    DiscoverAndCrawlSourcesResult,
    ConfirmLinksResult,
    ProcessProjectEntriesResult,
    GenerateSearchParamsResult,
    FetchSourceContentResult,
    GenerateCharacterCardResult,
    RegenerateCharacterFieldResult,
]


class CreateBackgroundJob(BaseModel):
    """Model for creating a new background job."""

    task_name: TaskName
    project_id: str
    payload: TaskPayload


class UpdateBackgroundJob(BaseModel):
    """Model for updating an existing background job."""

    status: Optional[JobStatus] = None
    result: Optional[TaskResult] = None
    error_message: Optional[str] = None
    total_items: Optional[int] = None
    processed_items: Optional[int] = None
    progress: Optional[float] = None


class BackgroundJob(CreateBackgroundJob):
    """Represents a single asynchronous task."""

    id: UUID
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    result: Optional[TaskResult] = None
    error_message: Optional[str] = None
    total_items: Optional[int] = None
    processed_items: Optional[int] = None
    progress: Optional[float] = None


def _deserialize_job(db_row: Dict[str, Any]) -> BackgroundJob:
    """
    Deserialize a database row into a BackgroundJob model,
    gracefully handling parsing errors for payload and result.
    """
    task_name = db_row["task_name"]

    # --- Gracefully handle payload deserialization ---
    payload_map = {
        TaskName.DISCOVER_AND_CRAWL_SOURCES: DiscoverAndCrawlSourcesPayload,
        TaskName.CONFIRM_LINKS: ConfirmLinksPayload,
        TaskName.PROCESS_PROJECT_ENTRIES: ProcessProjectEntriesPayload,
        TaskName.GENERATE_SEARCH_PARAMS: GenerateSearchParamsPayload,
        TaskName.RESCAN_LINKS: DiscoverAndCrawlSourcesPayload,
        TaskName.FETCH_SOURCE_CONTENT: FetchSourceContentPayload,
        TaskName.GENERATE_CHARACTER_CARD: GenerateCharacterCardPayload,
        TaskName.REGENERATE_CHARACTER_FIELD: RegenerateCharacterFieldPayload,
    }
    if db_row.get("payload") is not None:
        try:
            payload_model: BaseModel = payload_map[task_name]
            db_row["payload"] = payload_model.model_validate(db_row["payload"])
        except (ValidationError, KeyError) as e:
            logger.warning(f"Failed to parse payload for job {db_row['id']}: {e}")
            db_row["payload"] = None  # Set to None on failure

    # --- Gracefully handle result deserialization ---
    result_map = {
        TaskName.DISCOVER_AND_CRAWL_SOURCES: DiscoverAndCrawlSourcesResult,
        TaskName.CONFIRM_LINKS: ConfirmLinksResult,
        TaskName.PROCESS_PROJECT_ENTRIES: ProcessProjectEntriesResult,
        TaskName.GENERATE_SEARCH_PARAMS: GenerateSearchParamsResult,
        TaskName.RESCAN_LINKS: DiscoverAndCrawlSourcesResult,
        TaskName.FETCH_SOURCE_CONTENT: FetchSourceContentResult,
        TaskName.GENERATE_CHARACTER_CARD: GenerateCharacterCardResult,
        TaskName.REGENERATE_CHARACTER_FIELD: RegenerateCharacterFieldResult,
    }
    if db_row.get("result") is not None:
        try:
            result_model: BaseModel = result_map[task_name]
            db_row["result"] = result_model.model_validate(db_row["result"])
        except (ValidationError, KeyError) as e:
            logger.warning(f"Failed to parse result for job {db_row['id']}: {e}")
            db_row["result"] = None  # Set to None on failure

    return BackgroundJob(**db_row)


async def create_background_job(
    job: CreateBackgroundJob, tx: Optional[AsyncDBTransaction] = None
) -> BackgroundJob:
    """Create a new background job and return it."""
    db = tx or await get_db_connection()
    query = """
        INSERT INTO "BackgroundJob" (id, task_name, project_id, payload)
        VALUES (%s, %s, %s, %s)
        RETURNING *
    """
    params = (
        uuid4(),
        job.task_name.value,
        job.project_id,
        job.payload.model_dump_json() if job.payload else None,
    )
    result = await db.execute_and_fetch_one(query, params)
    if not result:
        raise Exception("Failed to create background job")
    return _deserialize_job(result)


async def get_background_job(
    job_id: UUID, tx: Optional[AsyncDBTransaction] = None
) -> BackgroundJob | None:
    """Retrieve a background job by its ID."""
    db = tx or await get_db_connection()
    query = 'SELECT * FROM "BackgroundJob" WHERE id = %s'
    result = await db.fetch_one(query, (job_id,))
    return _deserialize_job(result) if result else None


async def list_background_jobs_paginated(
    limit: int = 50, offset: int = 0
) -> PaginatedResponse[BackgroundJob]:
    """List all background jobs with pagination, newest first."""
    db = await get_db_connection()
    query = 'SELECT * FROM "BackgroundJob" ORDER BY created_at DESC LIMIT %s OFFSET %s'
    results = await db.fetch_all(query, (limit, offset))
    jobs = [_deserialize_job(row) for row in results] if results else []
    total_items = await count_background_jobs()
    current_page = offset // limit + 1

    return PaginatedResponse(
        data=jobs,
        meta=PaginationMeta(
            current_page=current_page,
            per_page=limit,
            total_items=total_items,
        ),
    )


async def count_background_jobs() -> int:
    """Count all background jobs."""
    db = await get_db_connection()
    query = 'SELECT COUNT(*) as count FROM "BackgroundJob"'
    result = await db.fetch_one(query)
    return result["count"] if result and "count" in result else 0


async def count_in_progress_background_jobs_by_task_name(task_name: TaskName) -> int:
    """Count the number of 'in_progress' jobs for a specific task name."""
    db = await get_db_connection()
    query = """
        SELECT COUNT(*) as count
        FROM "BackgroundJob"
        WHERE task_name = %s AND status = 'in_progress'
    """
    result = await db.fetch_one(query, (task_name.value,))
    return result["count"] if result and "count" in result else 0


async def get_and_lock_pending_background_job() -> BackgroundJob | None:
    """
    Atomically retrieve the oldest pending job and set its status to 'in_progress'.
    This uses the underlying database's locking mechanism to prevent race conditions.
    """
    db = await get_db_connection()
    result = await db.get_and_lock_pending_background_job()
    return _deserialize_job(result) if result else None


async def update_background_job(
    job_id: UUID,
    job_update: UpdateBackgroundJob,
    tx: Optional[AsyncDBTransaction] = None,
) -> BackgroundJob | None:
    """Update a background job's state."""
    db = tx or await get_db_connection()
    update_data = job_update.model_dump(exclude_unset=True)
    if not update_data:
        return await get_background_job(job_id)

    set_clause_parts = []
    params: List[Any] = []
    for key, value in update_data.items():
        set_clause_parts.append(f'"{key}" = %s')
        if key == "result" and value is not None:
            params.append(json.dumps(value))
        else:
            params.append(value)

    if not set_clause_parts:
        return await get_background_job(job_id)

    params.append(job_id)
    set_clause = ", ".join(set_clause_parts)
    # The `updated_at` column is updated automatically by the database schema's default value.
    query = f'UPDATE "BackgroundJob" SET {set_clause} WHERE id = %s RETURNING *'

    result = await db.execute_and_fetch_one(query, tuple(params))
    if not result:
        return None
    return _deserialize_job(result)


async def delete_background_job(job_id: UUID) -> None:
    """Delete a background job from the database."""
    db = await get_db_connection()
    query = 'DELETE FROM "BackgroundJob" WHERE id = %s'
    await db.execute(query, (job_id,))


async def reset_in_progress_jobs_to_pending(
    tx: Optional[AsyncDBTransaction] = None,
) -> None:
    """
    Resets any jobs that were 'in_progress' or 'cancelling' back to 'pending'.
    This is useful for recovering from an unexpected application shutdown.
    """
    db = tx or await get_db_connection()
    query = """
        UPDATE "BackgroundJob"
        SET status = 'pending'
        WHERE status IN ('in_progress', 'cancelling')
    """
    await db.execute(query)
    logger.info("Reset stale 'in_progress' and 'cancelling' jobs to 'pending'.")


async def get_latest_job_by_task_name(
    project_id: str, task_name: TaskName, tx: Optional[AsyncDBTransaction] = None
) -> BackgroundJob | None:
    """Retrieve the most recent background job for a specific project and task name."""
    db = tx or await get_db_connection()
    query = """
        SELECT * FROM "BackgroundJob"
        WHERE project_id = %s AND task_name = %s
        ORDER BY created_at DESC
        LIMIT 1
    """
    result = await db.fetch_one(query, (project_id, task_name.value))
    return _deserialize_job(result) if result else None
