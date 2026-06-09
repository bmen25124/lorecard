from enum import Enum
import json
from typing import Any, Dict, Optional, List
from uuid import UUID

from pydantic import BaseModel, Field, field_serializer
from db.connection import get_db_connection
from datetime import datetime
from db.common import PaginatedResponse, PaginationMeta
from db.database import AsyncDBTransaction


class ProjectType(str, Enum):
    LOREBOOK = "lorebook"
    CHARACTER = "character"


class SearchParams(BaseModel):
    purpose: str
    extraction_notes: str
    criteria: str


class ProjectTemplates(BaseModel):
    """Jinja templates for various tasks."""

    # Lorebook-specific templates
    selector_generation: Optional[str] = Field(
        None,
        description="The prompt used to instruct an LLM to analyze HTML and return a CSS selector.",
    )
    entry_creation: Optional[str] = Field(
        None,
        description="The prompt used to instruct an LLM to process a scraped web page into a structured lorebook entry.",
    )
    search_params_generation: Optional[str] = Field(
        None,
        description="The prompt used to instruct an LLM to generate search parameters from a user prompt.",
    )

    # Character-specific templates
    character_generation: Optional[str] = Field(
        None,
        description="The prompt used to generate a full character card from source material.",
    )
    character_field_regeneration: Optional[str] = Field(
        None,
        description="The prompt used to regenerate a single field of a character card.",
    )


class ProjectStatus(str, Enum):
    draft = "draft"
    search_params_generated = "search_params_generated"
    selector_generated = "selector_generated"
    links_extracted = "links_extracted"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class JsonEnforcementMode(str, Enum):
    API_NATIVE = "api_native"
    prompt_engineering = "prompt_engineering"


class CreateProject(BaseModel):
    id: str
    name: str
    project_type: ProjectType = ProjectType.LOREBOOK
    prompt: Optional[str] = None
    templates: ProjectTemplates
    requests_per_minute: int = 15
    credential_id: Optional[UUID] = None
    model_name: str
    model_parameters: Dict[str, Any]
    json_enforcement_mode: JsonEnforcementMode = JsonEnforcementMode.API_NATIVE

    @field_serializer("credential_id")
    def serialize_credential_id(self, value: UUID) -> str:
        if not value:
            return None
        return str(value)


class UpdateProject(BaseModel):
    name: Optional[str] = None
    templates: Optional[ProjectTemplates] = None
    requests_per_minute: Optional[int] = None
    status: Optional[ProjectStatus] = None
    prompt: Optional[str] = None
    search_params: Optional[SearchParams] = None
    credential_id: Optional[UUID] = None
    model_name: Optional[str] = None
    model_parameters: Optional[Dict[str, Any]] = None
    json_enforcement_mode: Optional[JsonEnforcementMode] = None


class Project(CreateProject):
    search_params: Optional[SearchParams] = None
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime


def _deserialize_project(row: Optional[Dict[str, Any]]) -> Optional[Project]:
    """
    Takes a raw DB row and correctly deserializes JSON string fields
    before validating with the Pydantic model.
    """
    if not row:
        return None

    # These are the keys that are stored as JSON strings in SQLite
    json_keys = ["search_params", "templates", "model_parameters"]

    for key in json_keys:
        if key in row and isinstance(row[key], str):
            try:
                # This correctly handles 'null', '{}', '[]', etc.
                row[key] = json.loads(row[key])
            except (json.JSONDecodeError, TypeError):
                # If parsing fails, it might be an empty string or malformed data.
                # Setting it to None is a safe fallback.
                row[key] = None

    return Project(**row)


async def create_project(project: CreateProject) -> Project:
    db = await get_db_connection()
    query = """
        INSERT INTO "Project" (id, name, project_type, prompt, templates, credential_id, model_name, model_parameters, requests_per_minute)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
    """
    params = (
        project.id,
        project.name,
        project.project_type.value,
        project.prompt,
        json.dumps(project.templates.model_dump()),
        project.credential_id,
        project.model_name,
        json.dumps(project.model_parameters),
        project.requests_per_minute,
    )
    result = await db.execute_and_fetch_one(query, params)
    if not result:
        raise Exception("Failed to create project")

    deserialized_project = _deserialize_project(result)
    if not deserialized_project:
        raise Exception("Failed to deserialize created project")
    return deserialized_project


async def get_project(
    project_id: str, tx: Optional[AsyncDBTransaction] = None
) -> Project | None:
    """Retrieve a project by its ID."""
    db = tx or await get_db_connection()
    query = 'SELECT * FROM "Project" WHERE id = %s'
    result = await db.fetch_one(query, (project_id,))
    return _deserialize_project(result)


async def count_projects() -> int:
    """Count all projects."""
    db = await get_db_connection()
    query = 'SELECT COUNT(*) as count FROM "Project"'
    result = await db.fetch_one(query)
    return result["count"] if result and "count" in result else 0


def _build_project_filters(
    search_query: Optional[str] = None,
    status: Optional[ProjectStatus] = None,
    project_type: Optional[ProjectType] = None,
) -> tuple[str, List[Any]]:
    conditions: List[str] = []
    params: List[Any] = []

    if search_query:
        conditions.append('(LOWER(name) LIKE %s OR LOWER(id) LIKE %s)')
        search_value = f"%{search_query.lower()}%"
        params.extend([search_value, search_value])

    if status:
        conditions.append("status = %s")
        params.append(status.value)

    if project_type:
        conditions.append("project_type = %s")
        params.append(project_type.value)

    if not conditions:
        return "", params

    return " WHERE " + " AND ".join(conditions), params


async def count_filtered_projects(
    search_query: Optional[str] = None,
    status: Optional[ProjectStatus] = None,
    project_type: Optional[ProjectType] = None,
) -> int:
    """Count projects after applying list filters."""
    db = await get_db_connection()
    where_clause, params = _build_project_filters(search_query, status, project_type)
    query = f'SELECT COUNT(*) as count FROM "Project"{where_clause}'
    result = await db.fetch_one(query, tuple(params))
    return result["count"] if result and "count" in result else 0


async def list_projects_paginated(
    limit: int = 50,
    offset: int = 0,
    search_query: Optional[str] = None,
    status: Optional[ProjectStatus] = None,
    project_type: Optional[ProjectType] = None,
    sort_by: str = "updated_at",
    sort_direction: str = "desc",
) -> PaginatedResponse[Project]:
    """List all projects with pagination."""
    db = await get_db_connection()
    sort_columns = {
        "name": "LOWER(name)",
        "created_at": "created_at",
        "updated_at": "updated_at",
        "status": "status",
        "project_type": "project_type",
    }
    order_column = sort_columns.get(sort_by, "updated_at")
    order_direction = "ASC" if sort_direction.lower() == "asc" else "DESC"
    where_clause, params = _build_project_filters(search_query, status, project_type)
    query = f'SELECT * FROM "Project"{where_clause} ORDER BY {order_column} {order_direction}, created_at DESC LIMIT %s OFFSET %s'
    results = await db.fetch_all(query, tuple([*params, limit, offset]))
    projects = [_deserialize_project(row) for row in results if row]
    projects = [p for p in projects if p]
    total_items = await count_filtered_projects(search_query, status, project_type)
    current_page = offset // limit + 1

    return PaginatedResponse(
        data=projects,
        meta=PaginationMeta(
            current_page=current_page,
            per_page=limit,
            total_items=total_items,
        ),
    )


async def update_project(
    project_id: str,
    project_update: UpdateProject,
    tx: Optional[AsyncDBTransaction] = None,
) -> Project | None:
    db = tx or await get_db_connection()
    update_data = project_update.model_dump(exclude_unset=True)
    if not update_data:
        return await get_project(project_id, tx=tx)

    set_clause_parts = []
    params: List[Any] = []
    for key, value in update_data.items():
        set_clause_parts.append(f'"{key}" = %s')
        if key in ["templates", "search_params", "model_parameters"]:
            if hasattr(value, "model_dump"):
                params.append(json.dumps(value.model_dump()))
            else:
                params.append(json.dumps(value))
        elif isinstance(value, Enum):
            params.append(value.value)
        else:
            params.append(value)

    if not set_clause_parts:
        return await get_project(project_id, tx=tx)

    params.append(project_id)
    set_clause = ", ".join(set_clause_parts)
    query = f'UPDATE "Project" SET {set_clause} WHERE id = %s RETURNING *'

    result = await db.execute_and_fetch_one(query, tuple(params))
    return _deserialize_project(result)


async def delete_project(project_id: str):
    """Delete a project from the database."""
    db = await get_db_connection()
    query = 'DELETE FROM "Project" WHERE id = %s'
    await db.execute(query, (project_id,))
