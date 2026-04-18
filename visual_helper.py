#!/usr/bin/env python3
"""
Deterministic helper for the Substack visual publishing pipeline.

Subcommands:
  peek  --lang es|en           Pick next approved queue item with [VISUAL:PX] tag. Print JSON.
  mark  --lang --queue-number --note-id --pillar --figure-used
                                Mark queue entry published plus append to publishing log.
  rotate-figure --pillar P1    Return next figure ID from the rotation library.

All Canva and Substack work is done by the caller (Claude session) via MCP tools.
This script stays deterministic: queue parsing, figure rotation, log writes.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"
ROTATION_STATE_PATH = Path(__file__).parent / "figure_rotation_state.json"
QUEUE_PATH = Path(os.environ.get("SUBSTACK_QUEUE_PATH", "~/substack-queue/Notes Review Queue.md")).expanduser()
# Optionally auto-resolve the queue path by scanning a vault root.
# Set SUBSTACK_VAULT_ROOT to the folder containing a "Writing" subfolder and a
# "Substack General/Notes Review Queue.md" inside it.
_VAULT_ROOT = Path(os.environ.get("SUBSTACK_VAULT_ROOT", "")).expanduser()
if _VAULT_ROOT and _VAULT_ROOT.exists():
    for _sg in _VAULT_ROOT.iterdir():
        if _sg.is_dir() and "Writing" in _sg.name:
            _candidate = _sg / "Substack General" / "Notes Review Queue.md"
            if _candidate.exists():
                QUEUE_PATH = _candidate
                break

LOG_PATH = QUEUE_PATH.parent / "Substack Publishing Log.md"


def load_config():
    return json.loads(CONFIG_PATH.read_text())


def _pillar_config(cfg: dict) -> dict:
    """Read pillar config. Checks image_generator.canva.pillars first, falls back to canva_pillars."""
    ig = cfg.get("image_generator", {})
    canva_ig = ig.get("canva", {})
    return canva_ig.get("pillars") or cfg.get("canva_pillars", {})


def _figure_library_path(cfg: dict) -> str:
    """Read figure library path. Checks image_generator.canva first, falls back to canva_figure_library_path."""
    ig = cfg.get("image_generator", {})
    canva_ig = ig.get("canva", {})
    return canva_ig.get("figure_library_path") or cfg.get("canva_figure_library_path", "")


def parse_queue(queue_text: str, lang: str):
    """
    Return list of sections with: number, title, text per lang, approval state, visual tag.

    Approval line formats supported:
        - [ ] EN
        - [x] EN
        - [x] EN [VISUAL:P1]
        - [x] EN [VISUAL:P1] PUBLISHED 2026-04-17 id:12345 visual:P1/fig_03
        - [x] EN SKIP
    """
    lines = queue_text.split("\n")
    sections = []
    current = None
    block_lang = None
    block_lines = []

    for i, line in enumerate(lines):
        m_head = re.match(r"^## (\d+(?:-\d+)?)\. (.+)", line)
        if m_head:
            if current:
                if block_lang and block_lines:
                    current["text"][block_lang] = "\n".join(block_lines).strip()
                sections.append(current)
            current = {
                "header_idx": i,
                "title": m_head.group(2).strip(),
                "number": m_head.group(1),
                "text": {"en": "", "es": ""},
                "approval_idx": {"en": None, "es": None},
                "status": {"en": "none", "es": "none"},
                "visual_tag": {"en": None, "es": None},
                "context_line": {"en": None, "es": None},
            }
            block_lang = None
            block_lines = []
            continue
        if current is None:
            continue

        m_lang = re.match(r"^\s*-\s*\[([ xX])\]\s*(EN|ES)\b(.*)", line)
        if m_lang:
            if block_lang and block_lines:
                current["text"][block_lang] = "\n".join(block_lines).strip()
                block_lines = []
            block_lang = None
            checked = m_lang.group(1).lower() == "x"
            which = m_lang.group(2).lower()
            rest = m_lang.group(3)
            current["approval_idx"][which] = i

            # Parse visual tag
            vm = re.search(r"\[VISUAL:(P[123])\]", rest)
            if vm:
                current["visual_tag"][which] = vm.group(1)

            # Parse context line (optional: CONTEXT: "..." after the visual tag)
            cm = re.search(r'CONTEXT:\s*"([^"]*)"', rest)
            if cm:
                current["context_line"][which] = cm.group(1)

            # Parse explicit short quote for the visual card (optional, overrides body text)
            qm = re.search(r'QUOTE:\s*"([^"]*)"', rest)
            if qm:
                current["visual_quote"] = current.get("visual_quote") or {"en": None, "es": None}
                current["visual_quote"][which] = qm.group(1)

            if "PUBLISHED" in rest.upper():
                current["status"][which] = "published"
            elif "SKIP" in rest.upper():
                current["status"][which] = "skip"
            elif checked:
                current["status"][which] = "approved"
            else:
                current["status"][which] = "unapproved"
            continue

        if re.match(r"^\s*\*\*EN:?\*\*\s*$", line):
            if block_lang and block_lines:
                current["text"][block_lang] = "\n".join(block_lines).strip()
            block_lang = "en"
            block_lines = []
            continue
        if re.match(r"^\s*\*\*ES:?\*\*\s*$", line):
            if block_lang and block_lines:
                current["text"][block_lang] = "\n".join(block_lines).strip()
            block_lang = "es"
            block_lines = []
            continue

        if line.strip() == "---":
            if block_lang and block_lines:
                current["text"][block_lang] = "\n".join(block_lines).strip()
                block_lines = []
            block_lang = None
            continue

        if block_lang:
            block_lines.append(line)

    if current:
        if block_lang and block_lines:
            current["text"][block_lang] = "\n".join(block_lines).strip()
        sections.append(current)

    return sections


def rotate_figure(pillar: str) -> str:
    """Return the next figure filename for the given pillar, cycling through the library."""
    cfg = load_config()
    pillar_cfg = _pillar_config(cfg).get(pillar, {})
    if not pillar_cfg.get("figure_rotation"):
        return ""

    raw_path = _figure_library_path(cfg)
    if not raw_path:
        return ""
    lib_path = Path(raw_path).expanduser()
    if not lib_path.exists():
        return ""
    figures = sorted([f.name for f in lib_path.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg")])
    if not figures:
        return ""

    state = {}
    if ROTATION_STATE_PATH.exists():
        state = json.loads(ROTATION_STATE_PATH.read_text())

    last_used_idx = state.get(pillar, -1)
    next_idx = (last_used_idx + 1) % len(figures)
    state[pillar] = next_idx
    ROTATION_STATE_PATH.write_text(json.dumps(state, indent=2))
    return figures[next_idx]


def peek(lang: str):
    """Find next approved, unpublished visual queue entry."""
    cfg = load_config()
    pillars = _pillar_config(cfg)

    if not QUEUE_PATH.exists():
        print(json.dumps({"status": "error", "message": f"Queue not found at {QUEUE_PATH}"}))
        sys.exit(1)

    sections = parse_queue(QUEUE_PATH.read_text(), lang)
    for s in sections:
        if s["status"][lang] != "approved":
            continue
        if s["visual_tag"][lang] is None:
            continue
        if not s["text"][lang].strip():
            continue
        pillar = s["visual_tag"][lang]
        pillar_cfg = pillars.get(pillar)
        if not pillar_cfg:
            continue
        figure_id = rotate_figure(pillar) if pillar_cfg.get("figure_rotation") else ""
        # Prefer explicit QUOTE: override for visual card; fall back to stripped body text.
        vq = s.get("visual_quote", {}).get(lang) if s.get("visual_quote") else None
        if vq:
            card_quote = vq
        else:
            # Strip [[wikilinks|alias]] to alias; [[wikilink]] to wikilink
            card_quote = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", s["text"][lang])
            card_quote = re.sub(r"\[\[([^\]]+)\]\]", r"\1", card_quote)
        result = {
            "status": "ok",
            "queue_number": s["number"],
            "title": s["title"],
            "pillar": pillar,
            "template_design_id": pillar_cfg["design_id"],
            "template_edit_url": pillar_cfg.get("edit_url"),
            "template_view_url": pillar_cfg.get("edit_url", "").replace("/edit", "/view"),
            "quote_text": card_quote,
            "full_body_text": s["text"][lang],
            "context_line": s["context_line"][lang] or "",
            "figure_id": figure_id,
            "figure_rotation": bool(pillar_cfg.get("figure_rotation")),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(json.dumps({"status": "empty", "message": f"No approved unpublished visual {lang.upper()} items."}, indent=2))
    return 1


def mark(lang: str, queue_number: str, note_id: str, pillar: str, figure_used: str):
    """Mark a queue entry published and append to the log."""
    queue_text = QUEUE_PATH.read_text()
    sections = parse_queue(queue_text, lang)
    target = None
    for s in sections:
        if s["number"] == queue_number:
            target = s
            break
    if target is None:
        print(json.dumps({"status": "error", "message": f"Queue entry {queue_number} not found"}))
        return 1

    lines = queue_text.split("\n")
    idx = target["approval_idx"][lang]
    date_str = datetime.now().strftime("%Y-%m-%d")
    marker_suffix = f" PUBLISHED {date_str} id:{note_id} visual:{pillar}"
    if figure_used:
        marker_suffix += f"/{figure_used}"

    if idx is None:
        new_line = f"- [x] {lang.upper()} [VISUAL:{pillar}]{marker_suffix}"
        lines.insert(target["header_idx"] + 1, new_line)
    else:
        old = lines[idx]
        # Strip any prior PUBLISHED marker, keep the checkbox + lang + visual tag, append new marker
        stripped = re.sub(r"\s*PUBLISHED\s+\S+\s+id:\S+(?:\s+visual:\S+)?", "", old)
        lines[idx] = stripped.rstrip() + marker_suffix

    QUEUE_PATH.write_text("\n".join(lines))

    # Append log
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_PATH.exists():
        LOG_PATH.write_text(
            "---\ntype: publishing-log\ncreationDate: 2026-04-17\n---\n\n"
            "# Substack Publishing Log\n\n"
            "Auto-generated. Each row: timestamp, lang, status, note_id, section, preview, pillar, figure.\n\n"
            "| Timestamp | Lang | Status | Note ID | Section | Pillar | Figure |\n"
            "|---|---|---|---|---|---|---|\n"
        )
    with LOG_PATH.open("a") as f:
        ts = datetime.utcnow().isoformat() + "Z"
        row = f"| {ts} | {lang} | OK_VISUAL | {note_id} | #{queue_number} {target['title']} | {pillar} | {figure_used or 'default'} |\n"
        f.write(row)

    print(json.dumps({"status": "ok", "queue_number": queue_number, "note_id": note_id, "pillar": pillar}))
    return 0


def publish_visual(lang: str, png_path: str, note_body: str, publication_name: str | None = None):
    """Upload a PNG to Substack, create a note image attachment, publish a Note with it. Returns {note_id, url}."""
    import base64
    import urllib.parse
    import urllib.request
    import urllib.error

    cfg = load_config()
    # Map lang to publication
    target = "main" if lang == "en" else "secondary"
    if publication_name:
        target = publication_name
    pub = next((p for p in cfg["publications"] if p["name"] == target), None)
    if not pub:
        return {"error": f"Publication {target} not found in config"}

    cookie = pub["cookie"]
    if not cookie.startswith("substack.sid="):
        cookie = f"substack.sid={cookie}"
    headers = {"Cookie": cookie, "Accept": "application/json", "User-Agent": "SubstackVisual/1.0"}

    subdomain = pub["subdomain"]
    pub_base = f"https://{subdomain}.substack.com/api/v1"
    global_base = "https://substack.com/api/v1"

    # 1. Upload image to Substack CDN
    from PIL import Image as PILImage
    with PILImage.open(png_path) as im:
        width, height = im.size
    img_data = base64.b64encode(open(png_path, "rb").read()).decode("utf-8")
    data_uri = f"data:image/png;base64,{img_data}"

    form_data = urllib.parse.urlencode({"image": data_uri}).encode("utf-8")
    req = urllib.request.Request(
        f"{pub_base}/image",
        data=form_data,
        headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            upload_result = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": f"upload HTTP {e.code}", "detail": e.read().decode("utf-8", "replace")[:500]}
    uploaded_url = upload_result.get("url")
    if not uploaded_url:
        return {"error": "CDN upload returned no URL", "detail": upload_result}

    # 2. Create note attachment.
    # Endpoint REQUIRES trailing slash and field name is "url" (not imageUrl).
    attach_headers = {**headers, "Content-Type": "application/json"}
    attach_payload = json.dumps({
        "type": "image",
        "url": uploaded_url,
    }).encode("utf-8")
    req = urllib.request.Request(f"{global_base}/comment/attachment/", data=attach_payload, headers=attach_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            attach_result = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": f"attachment HTTP {e.code}", "detail": e.read().decode("utf-8", "replace")[:500]}
    attachment_id = attach_result.get("id")
    if not attachment_id:
        return {"error": "No attachment_id returned", "detail": attach_result}

    # 3. Publish Note with attachment
    body_json = {
        "type": "doc",
        "attrs": {"schemaVersion": "v1"},
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": (note_body or " ").strip()}]}
        ],
    }
    note_payload = json.dumps({
        "bodyJson": body_json,
        "tabId": "for-you",
        "surface": "feed",
        "replyMinimumRole": "everyone",
        "attachmentIds": [attachment_id],
    }).encode("utf-8")
    req = urllib.request.Request(f"{global_base}/comment/feed/", data=note_payload, headers=attach_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            publish_result = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": f"publish HTTP {e.code}", "detail": e.read().decode("utf-8", "replace")[:500]}

    note_id = publish_result.get("id")
    return {
        "status": "ok",
        "note_id": note_id,
        "url": f"https://substack.com/notes/post/p-{note_id}",
        "attachment_id": attachment_id,
        "cdn_url": uploaded_url,
        "width": width,
        "height": height,
    }


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp_peek = sub.add_parser("peek", help="Find next approved visual queue entry")
    sp_peek.add_argument("--lang", choices=["en", "es"], required=True)

    sp_mark = sub.add_parser("mark", help="Mark a queue entry published")
    sp_mark.add_argument("--lang", choices=["en", "es"], required=True)
    sp_mark.add_argument("--queue-number", required=True)
    sp_mark.add_argument("--note-id", required=True)
    sp_mark.add_argument("--pillar", choices=["P1", "P2", "P3"], required=True)
    sp_mark.add_argument("--figure-used", default="")

    sp_rot = sub.add_parser("rotate-figure", help="Get next figure for a pillar")
    sp_rot.add_argument("--pillar", choices=["P1", "P2", "P3"], required=True)

    args = ap.parse_args()

    if args.cmd == "peek":
        sys.exit(peek(args.lang))
    elif args.cmd == "mark":
        sys.exit(mark(args.lang, args.queue_number, args.note_id, args.pillar, args.figure_used))
    elif args.cmd == "rotate-figure":
        fig = rotate_figure(args.pillar)
        print(json.dumps({"figure_id": fig, "pillar": args.pillar}))
        sys.exit(0 if fig else 1)


if __name__ == "__main__":
    main()
