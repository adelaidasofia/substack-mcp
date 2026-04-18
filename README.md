# substack-mcp

FastMCP server for Substack: publish Notes and posts, pull analytics, manage drafts, bridge Obsidian vault drafts to Substack, and generate visual cards with pluggable image generators.

## Quick reference

```
substack__test_connection             -- verify auth (start here)
substack__publish_note text=...       -- publish a Note immediately
substack__list_vault_drafts           -- show drafts from your vault file
substack__publish_vault_draft index=N -- publish one vault draft as a Note
substack__create_draft title=... body=... -- create a post draft
substack__get_dashboard days=30       -- subscriber + view KPIs
substack__capture_analytics_to_vault  -- snapshot analytics to vault markdown
```

## Tool inventory (29)

### Notes + vault pipeline

- `test_connection(publication?)` -- verify auth, return your profile
- `list_publications()` -- show configured publications and which is default
- `publish_note(text, publication?, attachment_ids?)` -- publish a Note immediately; markdown supported
- `create_note_attachment(image_path?, image_url?, link_url?, publication?)` -- upload image or register link; returns attachment UUID for use with publish_note
- `list_my_notes(limit?, publication?)` -- your recent Notes with reaction + comment counts
- `reply_to_note(note_id, text, publication?)` -- reply to a Note by ID
- `list_vault_drafts()` -- parse vault drafts file, return index + preview for each draft
- `publish_vault_draft(index, publication?, move_to_published?)` -- publish one vault draft as a Note
- `batch_publish_vault_drafts(indices, publication?)` -- publish multiple vault drafts in sequence

### Post management

- `create_draft(title, body, subtitle?, audience?, publication?)` -- create a post draft; body is markdown
- `update_draft(draft_id, title?, body?, subtitle?, audience?, publication?)` -- edit an existing draft
- `publish_post(draft_id, send_email?, audience?, publication?)` -- publish a draft live to subscribers
- `schedule_post(draft_id, publish_at, publication?)` -- schedule a draft for future publication (ISO 8601)
- `list_drafts(limit?, publication?)` -- list unpublished drafts
- `list_published(limit?, publication?)` -- list published posts with basic stats
- `get_post(identifier, publication?)` -- get full post by slug or numeric ID
- `upload_image(image_path, publication?)` -- upload an image to Substack CDN; returns CDN URL
- `react(post_id, publication?)` -- heart a post
- `restack(post_id, publication?)` -- restack a post
- `comment(post_id, body, publication?)` -- comment on a post
- `get_feed(limit?, publication?)` -- your reader feed (posts from publications you follow)

### Analytics

- `get_dashboard(days?, publication?)` -- KPIs: total/paid subscribers, views, growth, ARR
- `get_post_stats(post_id, publication?)` -- views, opens, clicks, shares, conversions for one post
- `get_subscriber_growth(publication?)` -- subscriber count over time
- `get_growth_sources(publication?)` -- subscriber growth by source (search, recommendations, direct, social)
- `get_top_posts(limit?, publication?)` -- posts ranked by engagement
- `get_earnings(publication?)` -- revenue data for paid publications
- `get_recommendation_stats(direction?, publication?)` -- recommendation network performance
- `capture_analytics_to_vault(publication?)` -- write a weekly analytics snapshot to your vault

## Install

```bash
git clone https://github.com/adelaidasofia/substack-mcp
cd substack-mcp
pip3 install -r requirements.txt
python3 -c "import server; print('OK')"
```

## Configuration

Copy `config.example.json` to `config.json` and fill in your values:

```bash
cp config.example.json config.json
```

`config.json` is gitignored. Key fields:

| Field | Description |
|---|---|
| `publications[].name` | Internal name used in tool calls |
| `publications[].subdomain` | Your Substack subdomain (e.g. `yourname`) |
| `publications[].cookie` | Session cookie (see below) |
| `default_publication` | Which publication to use when `publication` arg is omitted |
| `vault_drafts_path` | Path to your vault drafts markdown file |
| `image_generator.default` | Active image adapter: `pillow_local` or `canva` |

## Session cookie setup

Substack does not have a public API with OAuth. Auth uses your browser session cookie.

1. Open Chrome and log in to Substack.
2. Open DevTools (F12) and go to the Application tab.
3. Under Cookies, find `substack.com`.
4. Copy the value of `substack.sid`.
5. Paste it into `config.json` under the matching publication's `cookie` field.

The raw value works; the server accepts both `abc123` and `substack.sid=abc123`.

Session cookies expire. If tools return `{"error": "Auth failed"}`, re-extract the cookie.

## Register in Claude Code

Add to your `.mcp.json` (project-scoped) or via `claude mcp add -s user`:

```json
{
  "mcpServers": {
    "substack": {
      "command": "python3",
      "args": ["/path/to/substack-mcp/server.py"]
    }
  }
}
```

Restart Claude Code after editing `.mcp.json`. Verify with `claude mcp list`.

## Vault integration

Set `vault_drafts_path` in `config.json` to a markdown file in your Obsidian vault.
Format each draft as a section separated by `---`. Sections under `## Ready to Post`
are surfaced first by `list_vault_drafts`. Sections under `## Essay Seeds` come next.

After publishing, `publish_vault_draft` moves the draft to a `## Published` section
and appends the Substack URL and timestamp.

## Pluggable image generators

Visual card generation is handled by the adapter set in `config.json` under
`image_generator.default`.

### Shipped adapters

**`pillow_local`** (default) -- pure Pillow, no external API. Renders 1080x1080 PNG
cards locally using fonts from the `fonts/` directory. Three pillar templates: warm
mustard with optional figure (P1), deep burgundy bold quote (P2), mustard with section
tag (P3). Use with `render_card.py` as a standalone CLI.

**`canva`** -- Canva MCP choreography. Returns a `steps` list describing the Canva MCP
tool calls needed to clone a template, replace text, replace the figure, and export PNG.
The Claude session executing the playbook follows these steps. Requires Canva MCP
connected in Claude Code and design IDs filled in under `image_generator.canva.pillars`.

### Stubbed adapters (contributions welcome)

**`nano_banana`** -- Gemini 3 Pro Image via the nano-banana skill. Stub in
`image_generators/nano_banana.py`. Implement `generate()` by calling the skill's
image endpoint with a prompt built from the card spec.

**`midjourney`** -- Midjourney API (or proxy). Stub in `image_generators/midjourney.py`.
Implement `generate()` by submitting a prompt, polling for completion, and downloading
the result.

**`dalle`** -- OpenAI DALL-E. Stub in `image_generators/dalle.py`. Implement `generate()`
using `openai.images.generate`.

### Writing your own adapter

Subclass `ImageGenerator` from `image_generators.base`:

```python
from image_generators.base import ImageGenerator

class MyAdapter(ImageGenerator):
    @property
    def name(self) -> str:
        return "my_adapter"

    def generate(self, spec: dict) -> dict:
        # spec keys: pillar, quote, handle, figure_path, output_path
        # return: {status: "ok", adapter: ..., image_path: ..., width: ..., height: ...}
        ...
```

Register it in `image_generators/__init__.py` and add a config block under
`image_generator.my_adapter` in `config.json`.

## Visual publishing pipeline

The `visual_helper.py` script handles the deterministic side of the visual queue
pipeline: parsing a Review Queue markdown file, rotating through figures, and
marking entries published. See `visual_playbook.md` for the full end-to-end flow
including image generation, upload, and publishing steps.

```bash
python3 visual_helper.py peek --lang es        # get next approved visual item
python3 visual_helper.py mark --lang es ...    # mark published + update log
python3 visual_helper.py rotate-figure --pillar P1
```

## Known gotchas

1. **Cookie expiry.** `substack.sid` cookies expire after a few weeks. Re-extract from
   Chrome DevTools when `test_connection` returns auth errors.

2. **`draft_bylines` is required but undocumented.** `create_draft` will 400 without it.
   The server fetches your `user_id` from `/user/profile/self` automatically and injects
   it into every draft POST.

3. **Note attachment endpoint requires trailing slash.** `POST /comment/attachment/` (with
   slash) works. Without slash it returns 404. The server handles this correctly.

4. **Publication-scoped vs global endpoints.** Notes use `substack.com/api/v1/comment/feed/`.
   Post drafts use `{subdomain}.substack.com/api/v1/drafts`. Mixing them returns 404 or 403.

5. **`pledgedArr` in the dashboard is a projection, not real pledges.** Use
   `get_earnings` for actual revenue data.

6. **Multi-publication support.** Pass `publication="name"` to any tool to target a
   specific publication. Omit it to use `default_publication` from config.

## License

MIT
