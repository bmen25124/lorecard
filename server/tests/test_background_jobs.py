import os
import pytest
import pytest_asyncio
from litestar.testing import AsyncTestClient
from uuid import UUID

from db.database import AsyncDB, PostgresDB, SQLiteDB
from db.projects import (
    CreateProject,
    ProjectTemplates,
    ProjectType,
)
from default_templates import (
    selector_prompt,
    entry_creation_prompt,
    search_params_prompt,
    character_generation_prompt,
    character_field_regeneration_prompt,
)
from services.background_jobs import process_background_job


@pytest_asyncio.fixture(autouse=True)
async def cleanup_tables(db: AsyncDB):
    """Fixture to clean up tables after each test."""
    yield
    if isinstance(db, PostgresDB):
        await db.execute(
            'TRUNCATE "Project", "ProjectSource", "ProjectSourceHierarchy", "BackgroundJob", "ApiRequestLog", "Link", "LorebookEntry", "GlobalTemplate", "Credential", "CharacterCard" CASCADE;'
        )
    elif isinstance(db, SQLiteDB):
        tables = [
            "Project",
            "ProjectSource",
            "ProjectSourceHierarchy",
            "BackgroundJob",
            "ApiRequestLog",
            "Link",
            "LorebookEntry",
            "GlobalTemplate",
            "Credential",
            "CharacterCard",
        ]
        for table in tables:
            await db.execute(f'DELETE FROM "{table}";')


@pytest_asyncio.fixture
async def credential_id(client_test: AsyncTestClient) -> UUID:
    """Fixture to create a default credential and return its ID."""
    credential_payload = {
        "name": "Test Credential",
        "provider_type": "openrouter",
        "values": {"api_key": os.getenv("OPENROUTER_API_KEY")},
    }
    response = await client_test.post("/api/credentials", json=credential_payload)
    assert response.status_code == 201
    return UUID(response.json()["data"]["id"])


@pytest.fixture
def lorebook_project_payload(credential_id: UUID) -> CreateProject:
    """Fixture to return a project payload for a LOREBOOK project."""
    return CreateProject(
        id="skyrim-locations-test",
        name="Skyrim Locations (Integration Test)",
        project_type=ProjectType.LOREBOOK,
        prompt="Skyrim locations",
        templates=ProjectTemplates(
            selector_generation=selector_prompt,
            entry_creation=entry_creation_prompt,
            search_params_generation=search_params_prompt,
            character_generation=character_generation_prompt,
            character_field_regeneration=character_field_regeneration_prompt,
        ),
        credential_id=credential_id,
        model_name="google/gemini-2.5-flash",
        model_parameters={"temperature": 0.7},
    )


@pytest.fixture
def character_project_payload(credential_id: UUID) -> CreateProject:
    """Fixture to return a project payload for a CHARACTER project."""
    return CreateProject(
        id="lydia-character-test",
        name="Lydia Character (Integration Test)",
        project_type=ProjectType.CHARACTER,
        prompt="Lydia, the loyal housecarl from Whiterun in Skyrim.",
        templates=ProjectTemplates(
            character_generation=character_generation_prompt,
            character_field_regeneration=character_field_regeneration_prompt,
            entry_creation=entry_creation_prompt,
            search_params_generation=search_params_prompt,
            selector_generation=selector_prompt,
        ),
        credential_id=credential_id,
        model_name="google/gemini-2.5-flash",
        model_parameters={"temperature": 0.7},
    )


# --- Character Creator Tests ---


@pytest.mark.asyncio
async def test_fetch_source_content_job(
    client_test: AsyncTestClient,
    character_project_payload: CreateProject,
    credential_id: UUID,
):
    """
    End-to-end test for the FETCH_SOURCE_CONTENT job.
    """
    # Arrange
    project_id = character_project_payload.id
    character_project_payload.credential_id = credential_id
    response = await client_test.post(
        "/api/projects", json=character_project_payload.model_dump(mode="json")
    )
    assert response.status_code == 201

    source_payload = {
        "url": "https://elderscrolls.fandom.com/wiki/Lydia_(Skyrim)",
    }
    response = await client_test.post(
        f"/api/projects/{project_id}/sources", json=source_payload
    )
    assert response.status_code == 201
    source_id = response.json()["data"]["id"]

    # Act
    response = await client_test.post(
        "/api/jobs/fetch-content",
        json={"project_id": project_id, "source_ids": [source_id]},
    )
    assert response.status_code == 201
    job_id = response.json()["data"]["id"]
    await process_background_job(job_id)

    # Assert
    job_response = await client_test.get(f"/api/jobs/{job_id}")
    assert job_response.status_code == 200
    job_data = job_response.json()["data"]
    assert job_data["status"] == "completed"
    assert job_data["result"]["sources_fetched"] == 1

    source_response = await client_test.get(
        f"/api/projects/{project_id}/sources/{source_id}"
    )
    assert source_response.status_code == 200
    source_data = source_response.json()["data"]
    assert source_data["raw_content"] is not None
    assert source_data["content_char_count"] > 0
    assert source_data["content_type"] == "markdown"

    logs_response = await client_test.get(f"/api/projects/{project_id}/logs")
    assert logs_response.json()["meta"]["total_items"] == 0  # No LLM call


@pytest.mark.asyncio
async def test_generate_character_card_job(
    client_test: AsyncTestClient,
    character_project_payload: CreateProject,
    credential_id: UUID,
):
    """
    End-to-end test for the GENERATE_CHARACTER_CARD job.
    """
    # Arrange: Create project, source, and fetch content first
    project_id = character_project_payload.id
    character_project_payload.credential_id = credential_id
    await client_test.post(
        "/api/projects", json=character_project_payload.model_dump(mode="json")
    )
    response = await client_test.post(
        f"/api/projects/{project_id}/sources",
        json={"url": "https://elderscrolls.fandom.com/wiki/Lydia_(Skyrim)"},
    )
    source_id = response.json()["data"]["id"]
    response = await client_test.post(
        "/api/jobs/fetch-content",
        json={"project_id": project_id, "source_ids": [source_id]},
    )
    fetch_job_id = response.json()["data"]["id"]
    await process_background_job(fetch_job_id)

    # Act
    response = await client_test.post(
        "/api/jobs/generate-character",
        json={"project_id": project_id, "source_ids": [source_id]},
    )
    assert response.status_code == 201
    job_id = response.json()["data"]["id"]
    await process_background_job(job_id)

    # Assert
    job_response = await client_test.get(f"/api/jobs/{job_id}")
    assert job_response.status_code == 200
    assert job_response.json()["data"]["status"] == "completed"

    card_response = await client_test.get(f"/api/projects/{project_id}/character")
    assert card_response.status_code == 200
    card_data = card_response.json()["data"]
    assert card_data["name"] is not None and len(card_data["name"]) > 0
    assert card_data["description"] is not None and len(card_data["description"]) > 0

    project_response = await client_test.get(f"/api/projects/{project_id}")
    assert project_response.json()["data"]["status"] == "completed"

    logs_response = await client_test.get(f"/api/projects/{project_id}/logs")
    assert logs_response.json()["meta"]["total_items"] == 1  # One LLM call


@pytest.mark.asyncio
async def test_regenerate_character_field_job(
    client_test: AsyncTestClient,
    character_project_payload: CreateProject,
    credential_id: UUID,
):
    """
    End-to-end test for the REGENERATE_CHARACTER_FIELD job.
    """
    # Arrange: Create a full character card first
    project_id = character_project_payload.id
    character_project_payload.credential_id = credential_id
    await client_test.post(
        "/api/projects", json=character_project_payload.model_dump(mode="json")
    )
    response = await client_test.post(
        f"/api/projects/{project_id}/sources",
        json={"url": "https://elderscrolls.fandom.com/wiki/Lydia_(Skyrim)"},
    )
    source_id = response.json()["data"]["id"]
    response = await client_test.post(
        "/api/jobs/fetch-content",
        json={"project_id": project_id, "source_ids": [source_id]},
    )
    await process_background_job(response.json()["data"]["id"])
    response = await client_test.post(
        "/api/jobs/generate-character",
        json={"project_id": project_id, "source_ids": [source_id]},
    )
    await process_background_job(response.json()["data"]["id"])

    # Get the original description to compare against
    initial_card_response = await client_test.get(
        f"/api/projects/{project_id}/character"
    )
    original_description = initial_card_response.json()["data"]["description"]
    assert original_description is not None

    # Act
    regenerate_payload = {
        "project_id": project_id,
        "field_to_regenerate": "description",
        "custom_prompt": "Make it more concise and focus on her warrior aspects.",
        "context_options": {
            "include_existing_fields": True,
            "source_ids_to_include": [source_id],
        },
    }
    response = await client_test.post(
        "/api/jobs/regenerate-field", json=regenerate_payload
    )
    assert response.status_code == 201
    job_id = response.json()["data"]["id"]
    await process_background_job(job_id)

    # Assert
    job_response = await client_test.get(f"/api/jobs/{job_id}")
    assert job_response.status_code == 200
    assert job_response.json()["data"]["status"] == "completed"

    updated_card_response = await client_test.get(
        f"/api/projects/{project_id}/character"
    )
    assert updated_card_response.status_code == 200
    updated_description = updated_card_response.json()["data"]["description"]
    assert updated_description is not None
    assert updated_description != original_description  # Verify it changed

    logs_response = await client_test.get(f"/api/projects/{project_id}/logs")
    assert logs_response.json()["meta"]["total_items"] == 2  # Gen + Regen calls


# --- Existing Lorebook Tests ---


@pytest.mark.asyncio
async def test_discover_and_crawl_job_with_test_client(
    client_test: AsyncTestClient,
    lorebook_project_payload: CreateProject,
    credential_id: UUID,
):
    """
    End-to-end test for the DISCOVER_AND_CRAWL_SOURCES job using the AsyncTestClient.
    """
    # Arrange
    project_id = lorebook_project_payload.id
    lorebook_project_payload.credential_id = credential_id

    # 1. Create the project
    response = await client_test.post(
        "/api/projects", json=lorebook_project_payload.model_dump()
    )
    assert response.status_code == 201

    # 2a. Create a ProjectSource for the project
    source_payload = {
        "url": "https://elderscrolls.fandom.com/wiki/Category:Skyrim:_Locations",
        "max_pages_to_crawl": 1,
    }
    response = await client_test.post(
        f"/api/projects/{project_id}/sources", json=source_payload
    )
    assert response.status_code == 201
    source_id = response.json()["data"]["id"]

    # 2b. Update the project for setting search_params
    response = await client_test.patch(
        f"/api/projects/{project_id}",
        json={
            "search_params": {
                "purpose": "To gather detailed character information including backgrounds, traits, and relationships",
                "extraction_notes": "Focus extraction on the specific type of content requested. For characters: extract names, aliases, descriptions, personality, history, and relationships. For locations: extract features, history, significance. For other topics: extract key aspects relevant to the subject.",
                "criteria": "Page must be specifically created as a character article (e.g., character profile, biography page). Reject pages that only mention or reference the character within other content.",
            },
            "status": "search_params_generated",
        },
    )
    assert response.status_code == 200

    # 3. Start the 'discover_and_crawl_sources' job
    response = await client_test.post(
        "/api/jobs/discover-and-crawl",
        json={"project_id": project_id, "source_ids": [source_id]},
    )
    assert response.status_code == 201
    job_id = response.json()["data"]["id"]

    # 4. Run the worker to process the job
    await process_background_job(job_id)

    # 5. Check the job status and result via the API
    response = await client_test.get(f"/api/jobs/{job_id}")
    assert response.status_code == 200
    job_data = response.json()["data"]
    assert job_data["status"] == "completed"
    assert job_data["result"] is not None
    assert "new_links" in job_data["result"]
    assert "existing_links" in job_data["result"]
    assert len(job_data["result"]["new_links"]) > 0
    assert job_data["result"]["selectors_generated"] == 1

    # 6. Verify the Project and ProjectSource were updated
    project_response = await client_test.get(f"/api/projects/{project_id}")
    assert project_response.status_code == 200
    assert project_response.json()["data"]["status"] == "selector_generated"

    sources_response = await client_test.get(f"/api/projects/{project_id}/sources")
    assert sources_response.status_code == 200
    sources_data = sources_response.json()
    assert len(sources_data) >= 1
    source_data = next(s for s in sources_data if s["id"] == source_id)
    assert source_data["link_extraction_selector"] is not None
    assert len(source_data["link_extraction_selector"]) > 0

    # 7. Verify the API log was created
    response = await client_test.get(f"/api/projects/{project_id}/logs")
    assert response.status_code == 200
    logs_data = response.json()
    assert logs_data["meta"]["total_items"] == 1
    assert logs_data["data"][0]["error"] is False
    assert logs_data["data"][0]["job_id"] == job_id


@pytest.mark.asyncio
async def test_rescan_links_job_with_test_client(
    client_test: AsyncTestClient,
    lorebook_project_payload: CreateProject,
    credential_id: UUID,
):
    """
    End-to-end test for the RESCAN_LINKS job, ensuring it crawls but doesn't call an LLM.
    """
    # Arrange

    project_id = lorebook_project_payload.id
    # 1. Create the project
    lorebook_project_payload.credential_id = credential_id
    response = await client_test.post(
        "/api/projects", json=lorebook_project_payload.model_dump()
    )
    assert response.status_code == 201

    # 2. Create and configure a source with pre-existing selectors
    source_payload = {
        "url": "https://elderscrolls.fandom.com/wiki/Category:Skyrim:_Locations"
    }
    response = await client_test.post(
        f"/api/projects/{project_id}/sources", json=source_payload
    )
    assert response.status_code == 201
    source_id = response.json()["data"]["id"]

    # Manually add selectors to simulate a pre-scanned source
    response = await client_test.patch(
        f"/api/projects/{project_id}/sources/{source_id}",
        json={"link_extraction_selector": ["a.category-page__member-link"]},
    )
    assert response.status_code == 200

    # 3. Start the 'rescan_links' job
    response = await client_test.post(
        "/api/jobs/rescan-links",
        json={"project_id": project_id, "source_ids": [source_id]},
    )
    assert response.status_code == 201
    job_id = response.json()["data"]["id"]

    # 4. Run the worker to process the job
    await process_background_job(job_id)

    # 5. Check job status and result
    response = await client_test.get(f"/api/jobs/{job_id}")
    assert response.status_code == 200
    job_data = response.json()["data"]
    assert job_data["status"] == "completed"
    assert job_data["result"] is not None
    assert len(job_data["result"]["new_links"]) > 0
    assert job_data["result"]["selectors_generated"] == 0

    # 6. Verify NO API log was created, as rescan should not use an LLM
    response = await client_test.get(f"/api/projects/{project_id}/logs")
    assert response.status_code == 200
    logs_data = response.json()
    assert logs_data["meta"]["total_items"] == 0


@pytest.mark.asyncio
async def test_generate_search_params_job_with_test_client(
    client_test: AsyncTestClient,
    lorebook_project_payload: CreateProject,
    credential_id: UUID,
):
    """
    End-to-end test for the GENERATE_SEARCH_PARAMS job using the AsyncTestClient.
    """
    # Arrange
    project_id = lorebook_project_payload.id

    # 1. Create the project
    lorebook_project_payload.credential_id = credential_id
    response = await client_test.post(
        "/api/projects", json=lorebook_project_payload.model_dump()
    )
    assert response.status_code == 201

    # 2. Start the 'generate_search_params' job
    response = await client_test.post(
        "/api/jobs/generate-search-params", json={"project_id": project_id}
    )
    assert response.status_code == 201
    job_id = response.json()["data"]["id"]

    # 3. Run the worker to process the job
    await process_background_job(job_id)

    # 4. Check the job status via the API
    response = await client_test.get(f"/api/jobs/{job_id}")
    assert response.status_code == 200
    job_data = response.json()["data"]
    assert job_data["status"] == "completed"

    # 5. Verify the project was updated
    response = await client_test.get(f"/api/projects/{project_id}")
    assert response.status_code == 200
    project_data = response.json()["data"]
    assert project_data["search_params"] is not None
    assert "purpose" in project_data["search_params"]
    assert "extraction_notes" in project_data["search_params"]
    assert "criteria" in project_data["search_params"]

    # 6. Verify the API log was created
    response = await client_test.get(f"/api/projects/{project_id}/logs")
    assert response.status_code == 200
    logs_data = response.json()
    assert logs_data["meta"]["total_items"] == 1
    assert logs_data["data"][0]["error"] is False
    assert logs_data["data"][0]["job_id"] == job_id


@pytest.mark.asyncio
async def test_confirm_links_job_with_test_client(
    client_test: AsyncTestClient,
    lorebook_project_payload: CreateProject,
    credential_id: UUID,
):
    """
    End-to-end test for the CONFIRM_LINKS job using the AsyncTestClient.
    """
    # Arrange
    project_id = lorebook_project_payload.id
    lorebook_project_payload.credential_id = credential_id
    test_links = [
        "https://elderscrolls.fandom.com/wiki/A_Bandit%27s_Book",
        "https://elderscrolls.fandom.com/wiki/A_Bloody_Trail",
        "https://elderscrolls.fandom.com/wiki/Abandoned_House_(Markarth)",
    ]

    # 1. Create the project
    response = await client_test.post(
        "/api/projects", json=lorebook_project_payload.model_dump()
    )
    assert response.status_code == 201

    # 2. Manually set the project status to simulate the correct state
    response = await client_test.patch(
        f"/api/projects/{project_id}",
        json={"status": "selector_generated"},
    )
    assert response.status_code == 200

    # 3. Start the 'confirm_links' job
    response = await client_test.post(
        "/api/jobs/confirm-links",
        json={"project_id": project_id, "urls": test_links},
    )
    assert response.status_code == 201
    job_id = response.json()["data"]["id"]

    # 4. Run the worker to process the job
    await process_background_job(job_id)

    # 5. Check the job status via the API
    response = await client_test.get(f"/api/jobs/{job_id}")
    assert response.status_code == 200
    job_data = response.json()["data"]
    assert job_data["status"] == "completed"
    assert job_data["result"]["links_saved"] == len(test_links)

    # 6. Verify the project was updated
    response = await client_test.get(f"/api/projects/{project_id}")
    assert response.status_code == 200
    project_data = response.json()["data"]
    assert project_data["status"] == "links_extracted"

    # 7. Verify the links were created
    response = await client_test.get(f"/api/projects/{project_id}/links")
    assert response.status_code == 200
    links_data = response.json()
    assert links_data["meta"]["total_items"] == len(test_links)
    # Check if one of the URLs is in the created links
    assert any(
        link["url"] == "https://elderscrolls.fandom.com/wiki/A_Bandit%27s_Book"
        for link in links_data["data"]
    )


@pytest.mark.asyncio
async def test_process_project_entries_job_with_test_client(
    client_test: AsyncTestClient,
    lorebook_project_payload: CreateProject,
    credential_id: UUID,
):
    """
    End-to-end test for the PROCESS_PROJECT_ENTRIES job using the AsyncTestClient.
    """
    # Arrange
    project_id = lorebook_project_payload.id
    lorebook_project_payload.credential_id = credential_id
    test_links = [
        "https://elderscrolls.fandom.com/wiki/A_Bandit%27s_Book",
        "https://elderscrolls.fandom.com/wiki/A_Bloody_Trail",
        "https://elderscrolls.fandom.com/wiki/Abandoned_House_(Markarth)",
    ]

    response = await client_test.post(
        "/api/projects", json=lorebook_project_payload.model_dump()
    )
    assert response.status_code == 201

    # 2. Create links by calling the confirm-links job first
    response = await client_test.post(
        "/api/jobs/confirm-links",
        json={"project_id": project_id, "urls": test_links},
    )
    assert response.status_code == 201
    confirm_links_job_id = response.json()["data"]["id"]
    await process_background_job(confirm_links_job_id)

    # Verify links were created
    response = await client_test.get(f"/api/projects/{project_id}/links")
    assert response.json()["meta"]["total_items"] == len(test_links)

    # 3. Start the 'process-project-entries' job
    response = await client_test.post(
        "/api/jobs/process-project-entries", json={"project_id": project_id}
    )
    assert response.status_code == 201
    process_entries_job_id = response.json()["data"]["id"]

    # 4. Run the worker to process the job
    await process_background_job(process_entries_job_id)

    # 5. Check the job status via the API
    response = await client_test.get(f"/api/jobs/{process_entries_job_id}")
    assert response.status_code == 200
    job_data = response.json()["data"]
    assert job_data["status"] == "completed"
    assert (job_data["result"]["entries_created"]) >= 1 or (
        job_data["result"]["entries_skipped"] >= 1
    )
    assert job_data["result"]["entries_failed"] == 0

    # 6. Verify the project was updated
    response = await client_test.get(f"/api/projects/{project_id}")
    assert response.status_code == 200
    project_data = response.json()["data"]
    assert project_data["status"] == "completed"

    # 7. Verify the lorebook entries were created and have content
    response = await client_test.get(f"/api/projects/{project_id}/entries")
    assert response.status_code == 200
    entries_data = response.json()
    assert entries_data["meta"]["total_items"] >= 0
    for entry in entries_data["data"]:
        assert entry["content"] is not None
        assert len(entry["content"]) > 0

    # 8. Verify the API logs were created
    response = await client_test.get(f"/api/projects/{project_id}/logs")
    assert response.status_code == 200
    logs_data = response.json()
    # One for each link
    assert logs_data["meta"]["total_items"] >= 1
    assert all(log["error"] is False for log in logs_data["data"])


@pytest.mark.asyncio
async def test_discover_and_crawl_with_url_exclusions(
    client_test: AsyncTestClient,
    lorebook_project_payload: CreateProject,
    credential_id: UUID,
):
    """
    Tests that the DISCOVER_AND_CRAWL_SOURCES job correctly uses
    url_exclusion_patterns for both plain strings and regex.
    """
    # Arrange
    project_id = lorebook_project_payload.id
    lorebook_project_payload.credential_id = credential_id
    await client_test.post("/api/projects", json=lorebook_project_payload.model_dump())

    # 2a. Create a source with exclusion patterns
    source_payload = {
        "url": "https://elderscrolls.fandom.com/wiki/Category:Skyrim:_Locations",
        "max_pages_to_crawl": 1,
        "url_exclusion_patterns": [
            "A_Bloody_Trail",  # Plain string exclusion
            "/wiki/Special:",  # Another plain string
            "/\\(Online\\)/",  # Regex to exclude ESO locations
        ],
    }
    response = await client_test.post(
        f"/api/projects/{project_id}/sources", json=source_payload
    )
    assert response.status_code == 201
    source_id = response.json()["data"]["id"]

    # 2b. Update project status
    await client_test.patch(
        f"/api/projects/{project_id}",
        json={
            "search_params": {
                "purpose": "To gather detailed location information from Skyrim.",
                "extraction_notes": "Focus extraction on location names and useful lore details.",
                "criteria": "Page must describe a Skyrim location.",
            },
            "status": "search_params_generated",
        },
    )

    # Act: Start and process the job
    response = await client_test.post(
        "/api/jobs/discover-and-crawl",
        json={"project_id": project_id, "source_ids": [source_id]},
    )
    assert response.status_code == 201
    job_id = response.json()["data"]["id"]
    await process_background_job(job_id)

    # Assert
    response = await client_test.get(f"/api/jobs/{job_id}")
    job_data = response.json()["data"]
    assert job_data["status"] == "completed"

    new_links = job_data["result"]["new_links"]
    assert len(new_links) > 0

    # Check that excluded links are not present
    for link in new_links:
        assert "A_Bloody_Trail" not in link
        assert "/wiki/Special:" not in link
        assert "(Online)" not in link
