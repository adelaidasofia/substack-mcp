---
type: playbook
---

# Substack Visual Note Publishing Playbook

A scheduled task fires a Claude session with instructions to run this playbook.
Claude executes each step using MCP tools (Substack) plus the image generator
configured in `config.json` and helper scripts for deterministic queue work.

**Trigger prompt for scheduled task:**
> Execute the Substack visual publish flow. Read `visual_playbook.md` and follow
> it exactly. Language: es (or en). Image generator: pillow_local (or canva).
> Abort if anything fails; do not improvise.

The playbook is generator-agnostic. Step 3 varies by adapter. See the appendix
for adapter-specific choreography.

---

## Step 1: Get next visual queue entry

Run:
```bash
python3 visual_helper.py peek --lang es
```

Expected response:
```json
{
  "status": "ok",
  "queue_number": "5",
  "title": "Note title",
  "pillar": "P1",
  "quote_text": "The quote text for the card.",
  "context_line": "Optional caption for the Note body.",
  "figure_id": "fig_03_seated.png",
  "figure_rotation": true
}
```

If `status` is `"empty"`, exit cleanly. Log `VISUAL_QUEUE_EMPTY` to
`Substack Publishing Log.md` and stop. Nothing to publish this cycle.

---

## Step 2: Determine the image generator

Read `config.json`. Check `image_generator.default`. If not set, use `pillow_local`.

Supported adapters:
- `pillow_local` -- pure Pillow, renders locally. No external API. See Step 3a.
- `canva` -- Canva MCP choreography. See Appendix A.
- `nano_banana`, `midjourney`, `dalle` -- see adapter stubs in `image_generators/`.

---

## Step 3: Generate the image card

### Step 3a: pillow_local adapter

Run:
```bash
python3 render_card.py \
  --pillar <pillar from Step 1> \
  --quote "<quote_text from Step 1>" \
  --handle "@your-handle" \
  --output /tmp/substack_visual.png
```

For P1 with a figure:
```bash
python3 render_card.py \
  --pillar P1 \
  --quote "<quote_text>" \
  --handle "@your-handle" \
  --figure ~/your-vault/images/figures/<figure_id from Step 1> \
  --output /tmp/substack_visual.png
```

On success, the output PNG is at the path given by `--output`.

### Step 3b: Canva adapter

See **Appendix A** for the full Canva MCP choreography (clone template, replace
text, replace figure, commit, export). The choreography produces a download URL.
Download the PNG:
```bash
curl -o /tmp/substack_visual.png "<download_url from Canva export>"
```

### Step 3c: Other adapters

Call `get_image_generator(adapter_name, config["image_generator"])` and invoke
`.generate(spec)`. The returned `image_path` is the local PNG to upload.

---

## Step 4: Upload PNG to Substack

Use the Substack MCP:
```
substack__upload_image
  image_path: /tmp/substack_visual.png
  publication: secondary   (for ES) or main (for EN)
```

Save the returned `image_url`.

---

## Step 5: Create image attachment

Use the Substack MCP:
```
substack__create_note_attachment
  image_url: <image_url from Step 4>
  publication: secondary
```

Save the returned `attachment_id`.

---

## Step 6: Publish the Note with attachment and context line

Use the Substack MCP:
```
substack__publish_note
  text: <context_line from Step 1, or empty string for image-only>
  publication: secondary
  attachment_ids: [<attachment_id from Step 5>]
```

Save the returned `note_id`.

---

## Step 7: Mark queue entry published

Run:
```bash
python3 visual_helper.py mark \
  --lang es \
  --queue-number <queue_number from Step 1> \
  --note-id <note_id from Step 6> \
  --pillar <pillar from Step 1> \
  --figure-used <figure_id from Step 1>
```

This updates the Review Queue entry with a `PUBLISHED YYYY-MM-DD id:NNN visual:P1/fig_03`
marker and appends a row to `Substack Publishing Log.md`.

---

## Failure handling

At any step, if a tool call returns an error:
1. Log the failure to `Substack Publishing Log.md` with the step name and
   error message.
2. Do NOT mark the queue entry as published.
3. Do NOT retry automatically. The next scheduled fire will pick up the same
   queue entry.
4. Exit with a clear status so the user can diagnose on morning review.

If using the Canva adapter and the failure is in the commit step, call
`cancel-editing-transaction` before exiting so the clone is not left in a
broken state.

---

## Language routing

- `--lang es` routes to publication `secondary`
- `--lang en` routes to publication `main`

For separate language templates in Canva, give them different design IDs and
store them in distinct pillar keys (e.g. `P1` for EN, `P1_es` for ES) in
`config.json` under `image_generator.canva.pillars`.

---

## Dry-run mode

If the trigger prompt includes `--dry-run`, execute Steps 1 and 2 only
(fetch queue entry and determine adapter), report what would be generated,
then EXIT without uploading or publishing. Use this to validate the pipeline
is wired correctly without consuming API credits.

---

## Appendix A: Canva adapter choreography (adapter-specific)

This section is specific to the `canva` adapter. The main playbook above is
generator-agnostic; skip this appendix unless `image_generator.default` is
set to `"canva"`.

### A1: Clone the pillar template

Call `merge-designs` with:
- `type: "create_new_design"`
- `title`: "Substack Note clone PX {timestamp}"
- `operations`: `[{type: "insert_pages", source: {type: "design", design_id: <design_id from config>}}]`

Save the returned `design_id` as `clone_design_id`. The master template stays
untouched.

### A2: Start editing transaction on the clone

Call `start-editing-transaction` with `clone_design_id`.

Save:
- `transaction_id`
- `pages` array
- The text element ID for the placeholder quote (used in A3)

### A3: Replace the quote text

Call `perform-editing-operations` with:
- `transaction_id`
- `pages`
- One `find_and_replace_text` operation:
  - `element_id`: the quote element ID from A2
  - `find_text`: the placeholder quote string baked into the template
  - `replace_text`: `quote_text` from Step 1

### A4: Replace the figure (P1 only)

Only if `pillar == "P1"` AND `figure_rotation == true` AND `figure_id` is set.

1. Upload the figure:
   ```
   upload-asset-from-url
     url: file://{figure_library_path}/{figure_id}
   ```
   Save `asset_id`.

2. Replace the image element:
   ```
   perform-editing-operations
     transaction_id: {{transaction_id}}
     operations: [{type: "update_fill", asset_id: {{asset_id}}}]
   ```

If the figure library is empty, skip A4. The clone keeps the template's
default figure.

### A5: Commit the transaction

Call `commit-editing-transaction` with `transaction_id`.

On failure here, call `cancel-editing-transaction` before exiting.

### A6: Export the clone as PNG

Call `export-design` with:
- `design_id`: `clone_design_id`
- `format`: `{"type": "png", "width": 1080, "height": 1080, "export_quality": "pro"}`

Save the returned `download_url`, then continue at Step 4 of the main playbook.

### A7: Cleanup

The cloned design is no longer needed after export. Either delete it to keep
the Canva workspace clean or leave it for weekly housekeeping. Canva
auto-archives unused designs.
