from litestar import Controller, get, post, patch, delete
from litestar.exceptions import NotFoundException
from litestar.params import Body
from pydantic import BaseModel
from typing import Optional

from logging_config import get_logger
from db.projects import (
    Project,
    ProjectStatus,
    ProjectType,
    CreateProject,
    UpdateProject,
    create_project as db_create_project,
    get_project as db_get_project,
    list_projects_paginated as db_list_projects_paginated,
    update_project as db_update_project,
    delete_project as db_delete_project,
)
from db.links import (
    Link,
    count_processable_links_by_project as db_count_processable_links_by_project,
    list_links_by_project_paginated as db_list_links_by_project_paginated,
)
from db.lorebook_entries import (
    LorebookEntry,
    list_entries_by_project_paginated as db_list_entries_by_project_paginated,
    list_all_entries_by_project as db_list_all_entries_by_project,
)
from db.api_request_logs import (
    ApiRequestLog,
    list_logs_by_project_paginated as db_list_logs_by_project_paginated,
)
from db.common import PaginatedResponse, SingleResponse

logger = get_logger(__name__)


class CountResponse(BaseModel):
    count: int


class ProjectController(Controller):
    path = "/projects"

    @post("/")
    async def create_project(
        self, data: CreateProject = Body()
    ) -> SingleResponse[Project]:
        """Create a new project."""
        logger.debug(f"Creating project {data.id} of type {data.project_type}")
        project = await db_create_project(data)
        return SingleResponse(data=project)

    @get("/")
    async def list_projects(
        self,
        limit: int = 50,
        offset: int = 0,
        q: Optional[str] = None,
        status: Optional[ProjectStatus] = None,
        project_type: Optional[ProjectType] = None,
        sort_by: str = "updated_at",
        sort_direction: str = "desc",
    ) -> PaginatedResponse[Project]:
        """List all projects with pagination."""
        logger.debug("Listing all projects")
        return await db_list_projects_paginated(
            limit=limit,
            offset=offset,
            search_query=q,
            status=status,
            project_type=project_type,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    @get("/{project_id:str}/links")
    async def list_project_links(
        self, project_id: str, limit: int = 100, offset: int = 0
    ) -> PaginatedResponse[Link]:
        """List all links for a project with pagination."""
        logger.debug(f"Listing links for project {project_id}")
        return await db_list_links_by_project_paginated(project_id, limit, offset)

    @get("/{project_id:str}/links/processable-count")
    async def get_processable_links_count(
        self, project_id: str
    ) -> SingleResponse[CountResponse]:
        """Get the count of processable (pending or failed) links for a project."""
        logger.debug(f"Counting processable links for project {project_id}")
        count = await db_count_processable_links_by_project(project_id)
        return SingleResponse(data=CountResponse(count=count))

    @get("/{project_id:str}/entries")
    async def list_project_entries(
        self,
        project_id: str,
        limit: int = 100,
        offset: int = 0,
        q: Optional[str] = None,
    ) -> PaginatedResponse[LorebookEntry]:
        """List all lorebook entries for a project with pagination and optional search."""
        logger.debug(f"Listing entries for project {project_id}")
        return await db_list_entries_by_project_paginated(
            project_id, limit, offset, search_query=q
        )

    @get("/{project_id:str}/logs")
    async def list_project_api_logs(
        self, project_id: str, limit: int = 100, offset: int = 0
    ) -> PaginatedResponse[ApiRequestLog]:
        """List all API request logs for a project with pagination."""
        logger.debug(f"Listing API logs for project {project_id}")
        return await db_list_logs_by_project_paginated(project_id, limit, offset)

    @get("/{project_id:str}")
    async def get_project(self, project_id: str) -> SingleResponse[Project]:
        """Retrieve a single project by its ID."""
        logger.debug(f"Retrieving project {project_id}")
        project = await db_get_project(project_id)
        if not project:
            raise NotFoundException(f"Project '{project_id}' not found.")
        return SingleResponse(data=project)

    @patch("/{project_id:str}")
    async def update_project(
        self, project_id: str, data: UpdateProject = Body()
    ) -> SingleResponse[Project]:
        """Update a project."""
        logger.debug(f"Updating project {project_id}")
        project = await db_update_project(project_id, data)
        if not project:
            raise NotFoundException(f"Project '{project_id}' not found.")
        return SingleResponse(data=project)

    @delete("/{project_id:str}")
    async def delete_project(self, project_id: str) -> None:
        """Delete a project."""
        logger.debug(f"Deleting project {project_id}")
        await db_delete_project(project_id)

    @get("/{project_id:str}/lorebook/download")
    async def download_project_lorebook(
        self,
        project_id: str,
    ) -> dict:
        """Get the lorebook in downloadable format with numbered entries."""
        project = await db_get_project(project_id)
        if not project:
            raise NotFoundException(detail="Project not found")

        entries = await db_list_all_entries_by_project(project_id)
        if not entries:
            raise NotFoundException(
                detail="Lorebook not generated yet or generation failed."
            )

        # Transform to downloadable format
        entries_dict = {}
        # Ensure entries exist before iterating
        for i, entry in enumerate(entries):
            entries_dict[str(i)] = {
                "key": entry.keywords,
                "keysecondary": [],
                "comment": entry.title,
                "content": entry.content,
                "order": 100,  # Default order for all entries
                "position": 4,  # Sequential position
                "disable": False,
                "probability": 100,
                "useProbability": True,
                "depth": 0,
                "uid": i,  # Use index as UID
            }

        return {"entries": entries_dict}
