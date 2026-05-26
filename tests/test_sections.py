"""Section selection tests.

Substack requires posts to be filed under a publication section before
publishing. The MCP exposes:
  - list_sections(publication) -> [{id, name, slug, description, ...}]
  - section_id param on create_draft / update_draft / publish_post / schedule_post

When section_id is set, the request body carries draft_section_id=<id> AND
section_chosen=True. When omitted, behavior is unchanged from pre-section
versions.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import server  # noqa: E402

_FAKE_PUB = {"name": "main", "subdomain": "testpub", "cookie": "x"}
_FAKE_USER_ID = 99
_FAKE_PROFILE = {"id": _FAKE_USER_ID, "name": "Tester"}


@pytest.fixture
def fake_pub():
    """Patch _get_pub to return a deterministic publication config."""
    with patch.object(server, "_get_pub", return_value=_FAKE_PUB):
        yield _FAKE_PUB


@pytest.mark.asyncio
class TestListSections:
    async def test_calls_publication_sections_endpoint(self, fake_pub):
        fake_sections = [
            {"id": 1, "name": "Section A", "slug": "a", "description": "first"},
            {"id": 2, "name": "Section B", "slug": "b", "description": "second"},
        ]
        with patch.object(server, "_get", new=AsyncMock(return_value=fake_sections)) as m:
            result = await server.list_sections(publication="main")
        called_url = m.call_args.args[0]
        assert called_url == "https://testpub.substack.com/api/v1/publication/sections"
        assert result == [
            {"id": 1, "name": "Section A", "slug": "a", "description": "first"},
            {"id": 2, "name": "Section B", "slug": "b", "description": "second"},
        ]

    async def test_propagates_http_error(self, fake_pub):
        err = {"error": "HTTP 401", "response": "auth failed"}
        with patch.object(server, "_get", new=AsyncMock(return_value=err)):
            result = await server.list_sections()
        assert result == [err]


@pytest.mark.asyncio
class TestCreateDraftSection:
    async def test_section_id_patches_after_create(self, fake_pub):
        """Substack's POST /drafts silently ignores section fields, so the tool
        must follow up with a PUT after the draft is created."""
        post_calls = []
        put_calls = []

        async def fake_get(url, pub, params=None):
            return _FAKE_PROFILE

        async def fake_post(url, pub, body=None):
            post_calls.append({"url": url, "body": body})
            return {"id": 123}

        async def fake_put(url, pub, body=None):
            put_calls.append({"url": url, "body": body})
            return {"id": 123}

        with patch.object(server, "_get", new=fake_get), patch.object(
            server, "_post", new=fake_post
        ), patch.object(server, "_put", new=fake_put):
            result = await server.create_draft(
                title="t", body="hello", section_id=42, publication="main"
            )

        assert result["status"] == "draft_created"
        assert result["draft_id"] == 123
        # POST body itself does NOT need section fields — the API ignores them.
        # The follow-up PUT is what actually attaches the section.
        assert len(put_calls) == 1
        assert put_calls[0]["url"].endswith("/drafts/123")
        assert put_calls[0]["body"]["draft_section_id"] == 42
        assert put_calls[0]["body"]["section_chosen"] is True

    async def test_no_section_id_skips_patch(self, fake_pub):
        post_calls = []
        put_calls = []

        async def fake_get(url, pub, params=None):
            return _FAKE_PROFILE

        async def fake_post(url, pub, body=None):
            post_calls.append({"body": body})
            return {"id": 124}

        async def fake_put(url, pub, body=None):
            put_calls.append({"body": body})
            return {"id": 124}

        with patch.object(server, "_get", new=fake_get), patch.object(
            server, "_post", new=fake_post
        ), patch.object(server, "_put", new=fake_put):
            await server.create_draft(title="t", body="hello")

        assert post_calls[0]["body"]["section_chosen"] is False
        assert "draft_section_id" not in post_calls[0]["body"]
        assert put_calls == []

    async def test_section_patch_failure_returns_error(self, fake_pub):
        async def fake_get(url, pub, params=None):
            return _FAKE_PROFILE

        async def fake_post(url, pub, body=None):
            return {"id": 125}

        async def fake_put(url, pub, body=None):
            return {"error": "HTTP 401", "response": "auth failed"}

        with patch.object(server, "_get", new=fake_get), patch.object(
            server, "_post", new=fake_post
        ), patch.object(server, "_put", new=fake_put):
            result = await server.create_draft(title="t", body="hello", section_id=42)

        assert "error" in result


@pytest.mark.asyncio
class TestUpdateDraftSection:
    async def test_section_id_sets_draft_section_id_and_section_chosen(self, fake_pub):
        captured = {}

        async def fake_put(url, pub, body=None):
            captured["url"] = url
            captured["body"] = body
            return {"id": 200}

        with patch.object(server, "_put", new=fake_put):
            result = await server.update_draft(draft_id=200, section_id=42)

        assert result["status"] == "updated"
        assert captured["body"]["draft_section_id"] == 42
        assert captured["body"]["section_chosen"] is True

    async def test_no_section_id_omits_fields(self, fake_pub):
        captured = {}

        async def fake_put(url, pub, body=None):
            captured["body"] = body
            return {"id": 200}

        with patch.object(server, "_put", new=fake_put):
            await server.update_draft(draft_id=200, title="x")

        assert "draft_section_id" not in captured["body"]
        assert "section_chosen" not in captured["body"]


@pytest.mark.asyncio
class TestPublishPostSection:
    async def test_section_id_patches_draft_before_publishing(self, fake_pub):
        put_calls = []
        post_calls = []

        async def fake_put(url, pub, body=None):
            put_calls.append({"url": url, "body": body})
            return {"id": 199326297}

        async def fake_post(url, pub, body=None):
            post_calls.append({"url": url, "body": body})
            return {"id": 555, "slug": "test-slug"}

        with patch.object(server, "_put", new=fake_put), patch.object(server, "_post", new=fake_post):
            result = await server.publish_post(draft_id=199326297, section_id=42)

        assert result["status"] == "published"
        assert len(put_calls) == 1
        assert put_calls[0]["body"]["draft_section_id"] == 42
        assert put_calls[0]["body"]["section_chosen"] is True
        assert put_calls[0]["url"].endswith("/drafts/199326297")
        assert len(post_calls) == 1
        assert post_calls[0]["url"].endswith("/drafts/199326297/publish")

    async def test_section_patch_failure_short_circuits(self, fake_pub):
        put_called = False
        post_called = False

        async def fake_put(url, pub, body=None):
            nonlocal put_called
            put_called = True
            return {"error": "HTTP 401", "response": "auth failed"}

        async def fake_post(url, pub, body=None):
            nonlocal post_called
            post_called = True
            return {"id": 555}

        with patch.object(server, "_put", new=fake_put), patch.object(server, "_post", new=fake_post):
            result = await server.publish_post(draft_id=1, section_id=42)

        assert put_called is True
        assert post_called is False
        assert "error" in result

    async def test_no_section_id_skips_patch(self, fake_pub):
        put_called = False

        async def fake_put(url, pub, body=None):
            nonlocal put_called
            put_called = True
            return {"id": 1}

        async def fake_post(url, pub, body=None):
            return {"id": 555, "slug": "s"}

        with patch.object(server, "_put", new=fake_put), patch.object(server, "_post", new=fake_post):
            await server.publish_post(draft_id=1)

        assert put_called is False


@pytest.mark.asyncio
class TestSchedulePostSection:
    async def test_section_id_patches_draft_before_scheduling(self, fake_pub):
        put_calls = []
        post_calls = []

        async def fake_put(url, pub, body=None):
            put_calls.append({"url": url, "body": body})
            return {"id": 1}

        async def fake_post(url, pub, body=None):
            post_calls.append({"url": url, "body": body})
            return {"status": "scheduled"}

        with patch.object(server, "_put", new=fake_put), patch.object(server, "_post", new=fake_post):
            result = await server.schedule_post(
                draft_id=1, publish_at="2026-12-01T14:00:00.000Z", section_id=42
            )

        assert result["status"] == "scheduled"
        assert len(put_calls) == 1
        assert put_calls[0]["body"]["draft_section_id"] == 42
        assert put_calls[0]["body"]["section_chosen"] is True
        assert post_calls[0]["url"].endswith("/drafts/1/schedule")

    async def test_no_section_id_skips_patch(self, fake_pub):
        put_called = False

        async def fake_put(url, pub, body=None):
            nonlocal put_called
            put_called = True
            return {"id": 1}

        async def fake_post(url, pub, body=None):
            return {"status": "scheduled"}

        with patch.object(server, "_put", new=fake_put), patch.object(server, "_post", new=fake_post):
            await server.schedule_post(draft_id=1, publish_at="2026-12-01T14:00:00.000Z")

        assert put_called is False
