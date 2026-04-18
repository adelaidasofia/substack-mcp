"""Substack MCP Server — full Substack integration for Claude Code.

29 tools across 3 phases:
  Phase 1: Notes publishing + vault pipeline
  Phase 2: Post management + engagement
  Phase 3: Analytics + scale features

Built with FastMCP v3. Auth via substack.sid session cookie.
Multi-publication support (switch between pubs per tool call).
"""

import json
import os
import re
from datetime import datetime, date
from pathlib import Path

import httpx
from fastmcp import FastMCP

from prosemirror import md_to_prosemirror, md_to_note_body

# ---------------------------------------------------------------------------
# Server init
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "Substack",
    instructions=(
        "Substack integration: publish Notes, manage posts, pull analytics, "
        "and bridge your Obsidian vault drafts directly to Substack."
    ),
)

CONFIG_PATH = Path(__file__).parent / "config.json"
GLOBAL_BASE = "https://substack.com/api/v1"


def _load_config() -> dict:
    """Load config from disk (re-read each call so edits take effect)."""
    if not CONFIG_PATH.exists():
        return {"publications": [], "default_publication": "main", "vault_drafts_path": ""}
    return json.loads(CONFIG_PATH.read_text())


def _get_pub(name: str | None = None) -> dict:
    """Get publication config by name (or default)."""
    cfg = _load_config()
    target = name or cfg.get("default_publication", "main")
    for pub in cfg.get("publications", []):
        if pub["name"] == target:
            return pub
    if cfg.get("publications"):
        return cfg["publications"][0]
    raise ValueError("No publications configured. Copy config.example.json to config.json and fill in your publication(s).")


def _pub_base(pub: dict) -> str:
    """Base URL for a publication-scoped API."""
    return f"https://{pub['subdomain']}.substack.com/api/v1"


def _headers(pub: dict) -> dict:
    """Auth headers for API calls."""
    cookie = pub.get("cookie", "")
    # Accept raw cookie value or full "substack.sid=..." format
    if not cookie.startswith("substack.sid="):
        cookie = f"substack.sid={cookie}"
    return {
        "Cookie": cookie,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "SubstackMCP/1.0",
    }


async def _get(url: str, pub: dict, params: dict | None = None) -> dict | list:
    """Authenticated GET."""
    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=_headers(pub), params=params, timeout=20)
        if r.status_code in (401, 403):
            return {"error": "Auth failed. Cookie may be expired. Re-extract from Chrome DevTools."}
        if r.status_code >= 400:
            try:
                err_body = r.json()
            except Exception:
                err_body = r.text
            return {"error": f"HTTP {r.status_code}", "response": err_body}
        r.raise_for_status()
        return r.json()


async def _post(url: str, pub: dict, body: dict | None = None) -> dict | list:
    """Authenticated POST (JSON)."""
    async with httpx.AsyncClient() as client:
        r = await client.post(url, headers=_headers(pub), json=body or {}, timeout=30)
        if r.status_code in (401, 403):
            return {"error": "Auth failed. Cookie may be expired. Re-extract from Chrome DevTools."}
        if r.status_code >= 400:
            # Return the error body so callers can surface what Substack said.
            try:
                err_body = r.json()
            except Exception:
                err_body = r.text
            return {"error": f"HTTP {r.status_code}", "response": err_body}
        r.raise_for_status()
        return r.json()


async def _put(url: str, pub: dict, body: dict | None = None) -> dict | list:
    """Authenticated PUT (JSON)."""
    async with httpx.AsyncClient() as client:
        r = await client.put(url, headers=_headers(pub), json=body or {}, timeout=30)
        if r.status_code in (401, 403):
            return {"error": "Auth failed. Cookie may be expired. Re-extract from Chrome DevTools."}
        if r.status_code >= 400:
            try:
                err_body = r.json()
            except Exception:
                err_body = r.text
            return {"error": f"HTTP {r.status_code}", "response": err_body}
        r.raise_for_status()
        return r.json()


async def _delete(url: str, pub: dict) -> dict:
    """Authenticated DELETE."""
    async with httpx.AsyncClient() as client:
        r = await client.delete(url, headers=_headers(pub), timeout=20)
        if r.status_code in (401, 403):
            return {"error": "Auth failed. Cookie may be expired."}
        r.raise_for_status()
        return {"status": "deleted"}


async def _post_form(url: str, pub: dict, data: dict) -> dict:
    """Authenticated POST with form data (for image upload)."""
    headers = _headers(pub)
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    async with httpx.AsyncClient() as client:
        r = await client.post(url, headers=headers, data=data, timeout=60)
        if r.status_code in (401, 403):
            return {"error": "Auth failed. Cookie may be expired."}
        r.raise_for_status()
        return r.json()


# ===========================================================================
# PHASE 1: Notes + Vault Pipeline
# ===========================================================================

@mcp.tool()
async def test_connection(publication: str | None = None) -> dict:
    """Verify auth works for a publication. Returns your profile info.

    Args:
        publication: Publication name from config (default: default_publication)
    """
    pub = _get_pub(publication)
    result = await _get(f"{GLOBAL_BASE}/user/profile/self", pub)
    if isinstance(result, dict) and "error" in result:
        return result
    return {
        "status": "connected",
        "publication": pub["name"],
        "subdomain": pub["subdomain"],
        "user_id": result.get("id"),
        "name": result.get("name"),
        "email": result.get("email"),
        "primary_publication": result.get("primaryPublication", {}).get("subdomain"),
    }


@mcp.tool()
async def list_publications() -> list[dict]:
    """Show all configured publications and which is default."""
    cfg = _load_config()
    default = cfg.get("default_publication", "main")
    return [
        {
            "name": p["name"],
            "subdomain": p["subdomain"],
            "is_default": p["name"] == default,
            "has_cookie": bool(p.get("cookie")) and "PASTE" not in p.get("cookie", ""),
        }
        for p in cfg.get("publications", [])
    ]


@mcp.tool()
async def publish_note(
    text: str,
    publication: str | None = None,
    attachment_ids: list[str] | None = None,
) -> dict:
    """Publish a Note to Substack, optionally with image or link attachments.

    Args:
        text: The note content (markdown supported: bold, italic, links, lists). Can be empty string for image-only notes.
        publication: Publication name from config (default: default_publication)
        attachment_ids: Optional list of attachment UUIDs previously created via create_note_attachment.
    """
    pub = _get_pub(publication)
    body_json = md_to_note_body(text or " ")

    payload = {
        "bodyJson": body_json,
        "tabId": "for-you",
        "surface": "feed",
        "replyMinimumRole": "everyone",
        "attachmentIds": attachment_ids or [],
    }

    result = await _post(f"{GLOBAL_BASE}/comment/feed/", pub, payload)
    if isinstance(result, dict) and "error" in result:
        return result
    return {
        "status": "published",
        "note_id": result.get("id"),
        "date": result.get("date"),
        "url": f"https://substack.com/notes/post/p-{result.get('id', '')}",
        "attachment_count": len(attachment_ids or []),
    }


@mcp.tool()
async def create_note_attachment(
    image_path: str | None = None,
    image_url: str | None = None,
    link_url: str | None = None,
    publication: str | None = None,
) -> dict:
    """Create a Note attachment (image or link) and return its UUID for use with publish_note.

    Provide exactly one of image_path, image_url, or link_url.

    Flow for image attachment:
      1. If image_path, upload to Substack CDN first via /image endpoint.
      2. POST to /comment/attachment with {type: "image", imageUrl, imageWidth, imageHeight}.
      3. Return the attachment UUID.

    Args:
        image_path: Local file path to an image to upload and attach.
        image_url: Already-hosted image URL (skips upload step).
        link_url: URL to attach as a link-type attachment.
        publication: Publication name from config.

    Returns:
        dict with keys: attachment_id, type, and the original url/path.
    """
    import base64
    from PIL import Image as PILImage

    pub = _get_pub(publication)

    if link_url:
        payload = {"type": "link", "url": link_url}
        result = await _post(f"{GLOBAL_BASE}/comment/attachment", pub, payload)
        if isinstance(result, dict) and "error" in result:
            return result
        return {"attachment_id": result.get("id"), "type": "link", "url": link_url}

    # Image attachment path
    if image_path:
        path = Path(image_path).expanduser()
        if not path.exists():
            return {"error": f"File not found: {image_path}"}

        # Detect dimensions
        with PILImage.open(path) as im:
            width, height = im.size

        # Upload to Substack CDN first
        suffix = path.suffix.lower()
        mime_map = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".gif": "gif", ".webp": "webp"}
        mime = mime_map.get(suffix, "png")
        img_data = base64.b64encode(path.read_bytes()).decode("utf-8")
        data_uri = f"data:image/{mime};base64,{img_data}"

        upload_result = await _post_form(
            f"{_pub_base(pub)}/image",
            pub,
            data={"image": data_uri},
        )
        if isinstance(upload_result, dict) and "error" in upload_result:
            return upload_result
        uploaded_url = upload_result.get("url", "")
        if not uploaded_url:
            return {"error": "CDN upload returned no URL", "detail": upload_result}
    elif image_url:
        uploaded_url = image_url
        # Best-effort: probe dimensions if the URL is accessible
        width, height = 1080, 1080
    else:
        return {"error": "Provide image_path, image_url, or link_url"}

    # Create the note-scoped image attachment.
    # IMPORTANT: endpoint REQUIRES trailing slash, and field is "url" not "imageUrl".
    # Discovered 2026-04-17 after 500 errors with other shapes.
    attach_payload = {
        "type": "image",
        "url": uploaded_url,
    }
    result = await _post(f"{GLOBAL_BASE}/comment/attachment/", pub, attach_payload)
    if isinstance(result, dict) and "error" in result:
        return result
    return {
        "attachment_id": result.get("id"),
        "type": "image",
        "image_url": uploaded_url,
        "width": width,
        "height": height,
    }


@mcp.tool()
async def list_my_notes(
    limit: int = 20,
    publication: str | None = None,
) -> list[dict]:
    """Read your own recent Notes.

    Args:
        limit: Max notes to return (default 20)
        publication: Publication name from config
    """
    pub = _get_pub(publication)
    # First get user ID
    profile = await _get(f"{GLOBAL_BASE}/user/profile/self", pub)
    if isinstance(profile, dict) and "error" in profile:
        return [profile]

    user_id = profile.get("id")
    result = await _get(
        f"{GLOBAL_BASE}/reader/feed/profile/{user_id}",
        pub,
        params={"types": "note", "limit": str(limit)},
    )
    if isinstance(result, dict) and "error" in result:
        return [result]

    items = result.get("items", [])
    notes = []
    for item in items[:limit]:
        comment = item.get("comment", item)
        notes.append({
            "id": comment.get("id"),
            "date": comment.get("date"),
            "body_preview": (comment.get("body", "") or "")[:200],
            "reactions": comment.get("reaction_count", 0),
            "comments": comment.get("children_count", 0),
        })
    return notes


@mcp.tool()
async def reply_to_note(
    note_id: int,
    text: str,
    publication: str | None = None,
) -> dict:
    """Reply to a Note by ID.

    Args:
        note_id: The ID of the note to reply to
        text: Reply content (markdown supported)
        publication: Publication name from config
    """
    pub = _get_pub(publication)
    body_json = md_to_note_body(text)

    payload = {
        "bodyJson": body_json,
        "parentCommentId": note_id,
    }

    result = await _post(f"{GLOBAL_BASE}/comment/feed/", pub, payload)
    if isinstance(result, dict) and "error" in result:
        return result
    return {
        "status": "replied",
        "reply_id": result.get("id"),
        "parent_note_id": note_id,
    }


def _parse_vault_drafts() -> list[dict]:
    """Parse the vault drafts file into individual drafts with metadata."""
    cfg = _load_config()
    drafts_path = Path(cfg.get("vault_drafts_path", "")).expanduser()
    if not drafts_path.exists():
        return []

    content = drafts_path.read_text(encoding="utf-8")

    # Find sections
    sections = {"essay_seeds": [], "ready_to_post": [], "published": [], "other": []}
    current_section = "other"

    # Split by --- separators
    raw_drafts = re.split(r"\n---+\n", content)

    for chunk in raw_drafts:
        chunk = chunk.strip()
        if not chunk:
            continue

        # Detect section headers
        lower = chunk.lower()
        if "## essay seeds" in lower or "## essay seed" in lower:
            current_section = "essay_seeds"
            # Remove the header line and continue with remaining text
            lines = chunk.split("\n")
            chunk = "\n".join(line for line in lines if not line.strip().lower().startswith("## essay seed"))
            chunk = chunk.strip()
            if not chunk:
                continue
        elif "## ready to post" in lower:
            current_section = "ready_to_post"
            lines = chunk.split("\n")
            chunk = "\n".join(line for line in lines if not line.strip().lower().startswith("## ready to post"))
            chunk = chunk.strip()
            if not chunk:
                continue
        elif "## published" in lower:
            current_section = "published"
            continue
        elif chunk.startswith("# Substack Notes"):
            continue
        elif chunk.startswith("## Substack Notes Best"):
            continue  # Skip the best practices section
        elif "best practices" in lower and len(chunk) > 500:
            continue  # Skip large best-practices blocks

        # Extract source metadata
        source_match = re.search(r"\*\(Source:.*?\)\*", chunk)
        source = source_match.group(0) if source_match else None

        # Extract title (first bold text or first sentence)
        title_match = re.match(r"\*\*(.+?)\*\*", chunk)
        if title_match:
            title = title_match.group(1)
        else:
            first_line = chunk.split("\n")[0][:80]
            title = first_line

        sections[current_section].append({
            "title": title,
            "text": chunk,
            "source": source,
            "section": current_section,
        })

    # Combine essay_seeds and ready_to_post, then other
    all_drafts = []
    for i, d in enumerate(sections["ready_to_post"]):
        d["index"] = i
        d["section_label"] = "Ready to Post"
        all_drafts.append(d)
    for d in sections["essay_seeds"]:
        d["index"] = len(all_drafts)
        d["section_label"] = "Essay Seeds"
        all_drafts.append(d)
    for d in sections["other"]:
        d["index"] = len(all_drafts)
        d["section_label"] = "Uncategorized"
        all_drafts.append(d)

    return all_drafts


@mcp.tool()
async def list_vault_drafts() -> list[dict]:
    """Parse Substack Notes Drafts.md from the vault and show all drafts with index numbers.

    Returns drafts organized by section (Ready to Post, Essay Seeds, Uncategorized)
    with index numbers for use with publish_vault_draft.
    """
    drafts = _parse_vault_drafts()
    return [
        {
            "index": d["index"],
            "section": d["section_label"],
            "title": d["title"][:100],
            "preview": d["text"][:200] + ("..." if len(d["text"]) > 200 else ""),
            "source": d.get("source"),
            "char_count": len(d["text"]),
        }
        for d in drafts
    ]


@mcp.tool()
async def publish_vault_draft(
    index: int,
    publication: str | None = None,
    move_to_published: bool = True,
) -> dict:
    """Publish a draft from the vault file as a Substack Note.

    Args:
        index: Draft index from list_vault_drafts
        publication: Publication name from config
        move_to_published: If true, move the draft to a Published section in the vault file
    """
    drafts = _parse_vault_drafts()
    if index < 0 or index >= len(drafts):
        return {"error": f"Invalid index {index}. Use list_vault_drafts to see available drafts."}

    draft = drafts[index]
    text = draft["text"]

    # Strip wikilinks for Substack (convert [[X|Y]] to Y, [[X]] to X)
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)

    # Publish
    result = await publish_note(text=text, publication=publication)

    if isinstance(result, dict) and result.get("status") == "published" and move_to_published:
        _move_draft_to_published(draft, result)

    return result


def _move_draft_to_published(draft: dict, publish_result: dict):
    """Move a draft from its current section to Published in the vault file."""
    cfg = _load_config()
    drafts_path = Path(cfg.get("vault_drafts_path", "")).expanduser()
    if not drafts_path.exists():
        return

    content = drafts_path.read_text(encoding="utf-8")
    draft_text = draft["text"]

    # Remove the draft from its current location
    content = content.replace(draft_text, "")
    # Clean up double separators
    content = re.sub(r"\n---\n\s*\n---\n", "\n---\n", content)

    # Add to Published section
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    url = publish_result.get("url", "")
    published_entry = f"\n\n---\n\n{draft_text}\n\n*Published: {now} | {url}*"

    if "## Published" in content:
        content = content.replace("## Published", f"## Published{published_entry}", 1)
    else:
        content += f"\n\n## Published\n{published_entry}"

    drafts_path.write_text(content, encoding="utf-8")


@mcp.tool()
async def batch_publish_vault_drafts(
    indices: list[int],
    publication: str | None = None,
) -> list[dict]:
    """Publish multiple vault drafts as Notes immediately.

    Args:
        indices: List of draft indices from list_vault_drafts
        publication: Publication name from config
    """
    results = []
    for idx in indices:
        result = await publish_vault_draft(index=idx, publication=publication)
        results.append({"index": idx, **result})
    return results


# ===========================================================================
# PHASE 2: Post Management + Engagement
# ===========================================================================

@mcp.tool()
async def create_draft(
    title: str,
    body: str,
    subtitle: str = "",
    audience: str = "everyone",
    publication: str | None = None,
) -> dict:
    """Create a post draft. Body accepts markdown (auto-converted to Substack format).

    Args:
        title: Post title
        body: Post body in markdown
        subtitle: Optional subtitle
        audience: "everyone", "only_paid", "founding", "only_free"
        publication: Publication name from config
    """
    pub = _get_pub(publication)
    pm_body = md_to_prosemirror(body)

    profile = await _get(f"{GLOBAL_BASE}/user/profile/self", pub)
    if isinstance(profile, dict) and "error" in profile:
        return profile
    user_id = profile.get("id") if isinstance(profile, dict) else None
    if not user_id:
        return {"error": "Could not fetch user_id for draft_bylines. Check your session cookie."}

    payload = {
        "draft_title": title,
        "draft_subtitle": subtitle or None,
        "draft_body": json.dumps(pm_body),
        "draft_bylines": [{"id": user_id, "is_guest": False}],
        "audience": audience,
        "should_send_email": False,
        "section_chosen": False,
    }

    result = await _post(f"{_pub_base(pub)}/drafts", pub, payload)
    if isinstance(result, dict) and "error" in result:
        return result
    return {
        "status": "draft_created",
        "draft_id": result.get("id"),
        "title": title,
        "edit_url": f"https://{pub['subdomain']}.substack.com/publish/post/{result.get('id')}",
    }


@mcp.tool()
async def update_draft(
    draft_id: int,
    title: str | None = None,
    body: str | None = None,
    subtitle: str | None = None,
    audience: str = "everyone",
    publication: str | None = None,
) -> dict:
    """Update an existing draft.

    Args:
        draft_id: The draft ID to update
        title: New title (optional)
        body: New body in markdown (optional)
        subtitle: New subtitle (optional)
        audience: "everyone", "only_paid", "founding", "only_free"
        publication: Publication name from config
    """
    pub = _get_pub(publication)
    payload = {}
    if title is not None:
        payload["draft_title"] = title
    if subtitle is not None:
        payload["draft_subtitle"] = subtitle
    if body is not None:
        payload["draft_body"] = json.dumps(md_to_prosemirror(body))
    if audience:
        payload["audience"] = audience

    result = await _put(f"{_pub_base(pub)}/drafts/{draft_id}", pub, payload)
    if isinstance(result, dict) and "error" in result:
        return result
    return {"status": "updated", "draft_id": draft_id}


@mcp.tool()
async def publish_post(
    draft_id: int,
    send_email: bool = True,
    audience: str = "everyone",
    publication: str | None = None,
) -> dict:
    """Publish a draft post live to subscribers.

    Args:
        draft_id: The draft ID to publish
        send_email: Whether to email subscribers (default true)
        audience: "everyone", "only_paid", "founding", "only_free"
        publication: Publication name from config
    """
    pub = _get_pub(publication)
    payload = {
        "send": send_email,
        "share_automatically": False,
        "audience": audience,
    }

    result = await _post(f"{_pub_base(pub)}/drafts/{draft_id}/publish", pub, payload)
    if isinstance(result, dict) and "error" in result:
        return result
    return {
        "status": "published",
        "post_id": result.get("id"),
        "slug": result.get("slug"),
        "url": f"https://{pub['subdomain']}.substack.com/p/{result.get('slug', '')}",
    }


@mcp.tool()
async def schedule_post(
    draft_id: int,
    publish_at: str,
    publication: str | None = None,
) -> dict:
    """Schedule a draft for future publication.

    Args:
        draft_id: The draft ID to schedule
        publish_at: ISO 8601 datetime (e.g., "2026-04-20T14:00:00.000Z")
        publication: Publication name from config
    """
    pub = _get_pub(publication)
    payload = {"post_date": publish_at}
    result = await _post(f"{_pub_base(pub)}/drafts/{draft_id}/schedule", pub, payload)
    if isinstance(result, dict) and "error" in result:
        return result
    return {"status": "scheduled", "draft_id": draft_id, "publish_at": publish_at}


@mcp.tool()
async def list_drafts(
    limit: int = 25,
    publication: str | None = None,
) -> list[dict]:
    """Show unpublished drafts.

    Args:
        limit: Max drafts to return
        publication: Publication name from config
    """
    pub = _get_pub(publication)
    result = await _get(
        f"{_pub_base(pub)}/drafts",
        pub,
        params={"offset": "0", "limit": str(limit)},
    )
    if isinstance(result, dict) and "error" in result:
        return [result]
    if isinstance(result, list):
        drafts = result
    else:
        drafts = result.get("drafts", result.get("items", []))

    return [
        {
            "id": d.get("id"),
            "title": d.get("draft_title", d.get("title", "Untitled")),
            "subtitle": d.get("draft_subtitle"),
            "created": d.get("draft_created_at", d.get("created_at")),
            "word_count": d.get("word_count", 0),
        }
        for d in drafts[:limit]
    ]


@mcp.tool()
async def list_published(
    limit: int = 25,
    publication: str | None = None,
) -> list[dict]:
    """Show published posts with basic stats.

    Args:
        limit: Max posts to return
        publication: Publication name from config
    """
    pub = _get_pub(publication)
    # Try the post_management endpoint first, fall back to /posts
    try:
        result = await _get(
            f"{_pub_base(pub)}/post_management/published",
            pub,
            params={"offset": "0", "limit": str(limit)},
        )
    except Exception:
        # Fallback: use the posts endpoint
        result = await _get(
            f"{_pub_base(pub)}/posts",
            pub,
            params={"offset": "0", "limit": str(limit)},
        )
    if isinstance(result, dict) and "error" in result:
        return [result]

    posts = result if isinstance(result, list) else result.get("posts", result.get("items", []))
    return [
        {
            "id": p.get("id"),
            "title": p.get("title", "Untitled"),
            "slug": p.get("slug"),
            "date": p.get("post_date"),
            "audience": p.get("audience"),
            "reactions": p.get("reaction_count", 0),
            "comments": p.get("comment_count", 0),
            "url": f"https://{pub['subdomain']}.substack.com/p/{p.get('slug', '')}",
        }
        for p in posts[:limit]
    ]


@mcp.tool()
async def get_post(
    identifier: str,
    publication: str | None = None,
) -> dict:
    """Get full post content by slug or numeric ID.

    Args:
        identifier: Post slug (e.g. "my-post-title") or numeric ID
        publication: Publication name from config
    """
    pub = _get_pub(publication)
    if identifier.isdigit():
        result = await _get(f"{GLOBAL_BASE}/posts/by-id/{identifier}", pub)
    else:
        result = await _get(f"{_pub_base(pub)}/posts/{identifier}", pub)

    if isinstance(result, dict) and "error" in result:
        return result
    return {
        "id": result.get("id"),
        "title": result.get("title"),
        "subtitle": result.get("subtitle"),
        "slug": result.get("slug"),
        "date": result.get("post_date"),
        "audience": result.get("audience"),
        "body_html": (result.get("body_html", "") or "")[:2000],
        "reactions": result.get("reaction_count", 0),
        "comments": result.get("comment_count", 0),
    }


@mcp.tool()
async def upload_image(
    image_path: str,
    publication: str | None = None,
) -> dict:
    """Upload an image to Substack's CDN. Returns the CDN URL for use in posts.

    Args:
        image_path: Local file path to the image
        publication: Publication name from config
    """
    import base64

    pub = _get_pub(publication)
    path = Path(image_path).expanduser()
    if not path.exists():
        return {"error": f"File not found: {image_path}"}

    # Detect MIME type
    suffix = path.suffix.lower()
    mime_map = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".gif": "gif", ".webp": "webp"}
    mime = mime_map.get(suffix, "jpeg")

    img_data = base64.b64encode(path.read_bytes()).decode("utf-8")
    data_uri = f"data:image/{mime};base64,{img_data}"

    result = await _post_form(
        f"{_pub_base(pub)}/image",
        pub,
        data={"image": data_uri},
    )
    if isinstance(result, dict) and "error" in result:
        return result
    return {"status": "uploaded", "url": result.get("url", "")}


@mcp.tool()
async def react(
    post_id: int,
    publication: str | None = None,
) -> dict:
    """Heart/like a post.

    Args:
        post_id: The post ID to react to
        publication: Publication name from config
    """
    pub = _get_pub(publication)
    result = await _post(f"{_pub_base(pub)}/post/{post_id}/reaction", pub, {"reaction": "❤"})
    if isinstance(result, dict) and "error" in result:
        return result
    return {"status": "reacted", "post_id": post_id}


@mcp.tool()
async def restack(
    post_id: int,
    publication: str | None = None,
) -> dict:
    """Restack a post.

    Args:
        post_id: The post ID to restack
        publication: Publication name from config
    """
    pub = _get_pub(publication)
    result = await _post(f"{GLOBAL_BASE}/restack", pub, {"post_id": post_id})
    if isinstance(result, dict) and "error" in result:
        return result
    return {"status": "restacked", "post_id": post_id}


@mcp.tool()
async def comment(
    post_id: int,
    body: str,
    publication: str | None = None,
) -> dict:
    """Leave a comment on a post.

    Args:
        post_id: The post ID to comment on
        body: Comment text
        publication: Publication name from config
    """
    pub = _get_pub(publication)
    payload = {"body": body, "post_id": post_id}
    result = await _post(f"{_pub_base(pub)}/comment", pub, payload)
    if isinstance(result, dict) and "error" in result:
        return result
    return {"status": "commented", "post_id": post_id, "comment_id": result.get("id")}


@mcp.tool()
async def get_feed(
    limit: int = 20,
    publication: str | None = None,
) -> list[dict]:
    """Get your reader feed (posts from publications you follow).

    Args:
        limit: Max items to return
        publication: Publication name from config
    """
    pub = _get_pub(publication)
    result = await _get(f"{GLOBAL_BASE}/reader/feed", pub, params={"limit": str(limit)})
    if isinstance(result, dict) and "error" in result:
        return [result]

    items = result.get("items", []) if isinstance(result, dict) else result
    feed = []
    for item in items[:limit]:
        post = item.get("post", item)
        feed.append({
            "id": post.get("id"),
            "title": post.get("title", ""),
            "subtitle": post.get("subtitle", ""),
            "author": post.get("publishedBylines", [{}])[0].get("name", "") if post.get("publishedBylines") else "",
            "publication": post.get("publication", {}).get("subdomain", ""),
            "date": post.get("post_date"),
            "url": post.get("canonical_url", ""),
        })
    return feed


# ===========================================================================
# PHASE 3: Analytics + Scale Features
# ===========================================================================

@mcp.tool()
async def get_dashboard(
    days: int = 30,
    publication: str | None = None,
) -> dict:
    """Get dashboard KPIs: total subscribers (free/paid), views, open rates, growth rate.

    Args:
        days: Lookback period (30, 60, or 90)
        publication: Publication name from config
    """
    pub = _get_pub(publication)
    result = await _get(
        f"{_pub_base(pub)}/publish-dashboard/summary-v2",
        pub,
        params={"range": str(days)},
    )
    if isinstance(result, dict) and "error" in result:
        return result

    # Cross-reference pledges endpoint for accurate pledge data
    # (dashboard inflates pledgedArr with hypothetical conversion projections)
    try:
        pledges = await _get(f"{_pub_base(pub)}/publication/stats/payment_pledges/summary", pub)
        real_pledges = pledges.get("totalPledges", 0)
        real_pledge_amount = pledges.get("totalPledgeAmount", 0)
    except Exception:
        real_pledges = None
        real_pledge_amount = None

    out = {
        "publication": pub["subdomain"],
        "period_days": days,
        "subscribers_total": result.get("totalSubscribersEnd"),
        "subscribers_start": result.get("totalSubscribersStart"),
        "subscribers_growth": (result.get("totalSubscribersEnd", 0) or 0) - (result.get("totalSubscribersStart", 0) or 0),
        "paid_subscribers": result.get("paidSubscribersEnd"),
        "arr": result.get("arrEnd"),
        "views": result.get("totalViewsEnd"),
        "views_start": result.get("totalViewsStart"),
        "views_growth": (result.get("totalViewsEnd", 0) or 0) - (result.get("totalViewsStart", 0) or 0),
        "real_pledge_count": real_pledges,
        "real_pledge_amount": real_pledge_amount,
        "note": "pledgedArr from dashboard is a projection, not real pledges. Use real_pledge_count for truth.",
    }
    return out


@mcp.tool()
async def get_post_stats(
    post_id: int,
    publication: str | None = None,
) -> dict:
    """Get detailed stats for a specific post: views, opens, clicks, shares, conversions.

    Args:
        post_id: The post ID to get stats for
        publication: Publication name from config
    """
    pub = _get_pub(publication)
    result = await _get(f"{_pub_base(pub)}/post_management/detail/{post_id}", pub)
    if isinstance(result, dict) and "error" in result:
        return result
    return {"post_id": post_id, **result}


@mcp.tool()
async def get_subscriber_growth(
    publication: str | None = None,
) -> dict:
    """Get subscriber count over time (daily/weekly chart data).

    Args:
        publication: Publication name from config
    """
    pub = _get_pub(publication)
    result = await _get(f"{_pub_base(pub)}/publication/stats/subscribers", pub)
    if isinstance(result, dict) and "error" in result:
        return result
    return {"publication": pub["subdomain"], **result}


@mcp.tool()
async def get_growth_sources(
    publication: str | None = None,
) -> dict:
    """Get subscriber growth breakdown by source (direct, search, recommendations, social).

    Args:
        publication: Publication name from config
    """
    pub = _get_pub(publication)
    result = await _get(f"{_pub_base(pub)}/publication/stats/growth/sources", pub)
    if isinstance(result, dict) and "error" in result:
        return result
    return {"publication": pub["subdomain"], **result}


@mcp.tool()
async def get_top_posts(
    limit: int = 10,
    publication: str | None = None,
) -> list[dict]:
    """Get posts ranked by engagement (reactions + comments).

    Args:
        limit: Max posts to return
        publication: Publication name from config
    """
    pub = _get_pub(publication)
    result = await _get(
        f"{_pub_base(pub)}/post_management/published",
        pub,
        params={"offset": "0", "limit": "50", "order_by": "reaction_count", "order_direction": "desc"},
    )
    if isinstance(result, dict) and "error" in result:
        return [result]

    posts = result if isinstance(result, list) else result.get("posts", [])
    return [
        {
            "id": p.get("id"),
            "title": p.get("title", "Untitled"),
            "reactions": p.get("reaction_count", 0),
            "comments": p.get("comment_count", 0),
            "date": p.get("post_date"),
            "engagement_score": (p.get("reaction_count", 0) or 0) + (p.get("comment_count", 0) or 0) * 5,
        }
        for p in posts[:limit]
    ]


@mcp.tool()
async def get_earnings(
    publication: str | None = None,
) -> dict:
    """Get revenue and earnings data for paid publications.

    Args:
        publication: Publication name from config
    """
    pub = _get_pub(publication)
    result = await _get(f"{_pub_base(pub)}/publication/stats/payment_pledges/summary", pub)
    if isinstance(result, dict) and "error" in result:
        return result
    return {"publication": pub["subdomain"], **result}


@mcp.tool()
async def get_recommendation_stats(
    direction: str = "inbound",
    publication: str | None = None,
) -> dict:
    """Get recommendation network performance (which pubs recommend you, and vice versa).

    Args:
        direction: "inbound" (who recommends you) or "outbound" (who you recommend)
        publication: Publication name from config
    """
    pub = _get_pub(publication)
    endpoint = "to" if direction == "inbound" else "from"
    result = await _get(f"{_pub_base(pub)}/recommendations/stats/{endpoint}", pub)
    if isinstance(result, dict) and "error" in result:
        return result
    return {"publication": pub["subdomain"], "direction": direction, **result}


@mcp.tool()
async def capture_analytics_to_vault(
    publication: str | None = None,
) -> dict:
    """Pull a weekly analytics snapshot and write it as a formatted note to the vault.

    Args:
        publication: Publication name from config
    """
    pub = _get_pub(publication)

    # Gather data
    dashboard = await get_dashboard(days=30, publication=pub["name"])
    growth = await get_subscriber_growth(publication=pub["name"])
    top = await get_top_posts(limit=5, publication=pub["name"])

    # Build markdown
    today = date.today().isoformat()
    md = f"""---
type: analytics
date: {today}
publication: {pub['subdomain']}
---

# Substack Analytics Snapshot - {today}

## Dashboard ({pub['subdomain']})
```json
{json.dumps(dashboard, indent=2, default=str)[:2000]}
```

## Subscriber Growth
```json
{json.dumps(growth, indent=2, default=str)[:1000]}
```

## Top 5 Posts by Engagement
"""
    for i, p in enumerate(top, 1):
        md += f"{i}. **{p.get('title', 'Untitled')}** - {p.get('reactions', 0)} hearts, {p.get('comments', 0)} comments\n"

    # Write to vault
    cfg = _load_config()
    vault_drafts_path = cfg.get("vault_drafts_path", "")
    if not vault_drafts_path:
        return {"error": "vault_drafts_path not configured. Set it in config.json to enable vault capture."}
    vault_base = Path(vault_drafts_path).expanduser().parent.parent
    analytics_dir = vault_base / "Substack General"
    analytics_dir.mkdir(parents=True, exist_ok=True)
    out_path = analytics_dir / f"Analytics {today}.md"
    out_path.write_text(md, encoding="utf-8")

    return {
        "status": "captured",
        "path": str(out_path),
        "publication": pub["subdomain"],
        "date": today,
    }
