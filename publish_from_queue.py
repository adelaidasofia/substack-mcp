#!/usr/bin/env python3
"""
Substack Notes auto-publisher. Reads Review Queue, publishes next approved item,
verifies it landed, logs the result, and marks the queue.

Invocation:
  python3 publish_from_queue.py --lang en                # publish next EN-approved Note
  python3 publish_from_queue.py --lang es                # publish next ES-approved Note
  python3 publish_from_queue.py --lang en --dry-run      # show what would happen
  python3 publish_from_queue.py --test                   # publish a [TEST] placeholder to verify pipeline

Exit 0 on success, non-zero on failure (cron / scheduled task should alert).
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

import os

CONFIG_PATH = Path(__file__).parent / "config.json"
QUEUE_PATH = Path(os.environ.get("SUBSTACK_QUEUE_PATH", "~/substack-queue/Notes Review Queue.md")).expanduser()
LOG_PATH = Path(os.environ.get("SUBSTACK_LOG_PATH", "~/substack-queue/Substack Publishing Log.md")).expanduser()
GLOBAL_BASE = "https://substack.com/api/v1"


def load_config():
    return json.loads(CONFIG_PATH.read_text())


def get_pub(lang: str):
    """Map language to publication. EN goes to `main`, ES goes to `secondary`."""
    cfg = load_config()
    target = "main" if lang == "en" else "secondary"
    for p in cfg["publications"]:
        if p["name"] == target:
            return p
    raise ValueError(f"No publication found for lang={lang}")


def headers(pub):
    cookie = pub["cookie"]
    if not cookie.startswith("substack.sid="):
        cookie = f"substack.sid={cookie}"
    return {
        "Cookie": cookie,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "SubstackAutoPublisher/1.0",
    }


def api_post(url, pub, body):
    req = urllib.request.Request(
        url,
        headers=headers(pub),
        data=json.dumps(body).encode("utf-8"),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "detail": e.read().decode("utf-8", "replace")[:500]}
    except Exception as e:
        return {"error": str(e)}


def api_get(url, pub):
    req = urllib.request.Request(url, headers=headers(pub))
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "detail": e.read().decode("utf-8", "replace")[:500]}
    except Exception as e:
        return {"error": str(e)}


def md_to_note_body(text: str) -> dict:
    """Minimal markdown-to-ProseMirror. Splits paragraphs on blank lines, emits doc JSON."""
    paragraphs = [p.strip() for p in text.strip().split("\n\n") if p.strip()]
    content = []
    for p in paragraphs:
        text_collapsed = " ".join(line.strip() for line in p.split("\n"))
        content.append({
            "type": "paragraph",
            "content": [{"type": "text", "text": text_collapsed}],
        })
    return {"type": "doc", "attrs": {"schemaVersion": "v1"}, "content": content}


def parse_queue(queue_text: str, lang: str):
    """
    Parse the Review Queue to find the next approved, unpublished item for the given language.

    Approval format:
        - [ ] EN                           (not approved)
        - [x] EN                           (approved, not yet published)
        - [x] EN PUBLISHED 2026-04-15 id:243665382   (already published, skip)
        - [x] EN SKIP                      (manually skipped)
    """
    lines = queue_text.split("\n")
    sections = []
    current = None
    current_lang_block = None
    current_block_lines = []

    for i, line in enumerate(lines):
        m = re.match(r"^## (\d+(?:-\d+)?)\. (.+)", line)
        if m:
            if current:
                if current_lang_block and current_block_lines:
                    current["text"][current_lang_block] = "\n".join(current_block_lines).strip()
                sections.append(current)
            current = {
                "header_idx": i,
                "title": m.group(2).strip(),
                "number": m.group(1),
                "text": {"en": "", "es": ""},
                "approval_idx": {"en": None, "es": None},
                "status": {"en": "none", "es": "none"},
            }
            current_lang_block = None
            current_block_lines = []
            continue

        if current is None:
            continue

        m_en = re.match(r"^\s*-\s*\[([ xX])\]\s*EN\b(.*)", line)
        m_es = re.match(r"^\s*-\s*\[([ xX])\]\s*ES\b(.*)", line)
        m_old = re.match(r"^\s*-\s*\[([ xX])\]\s*\*\*APPROVE\*\*", line)

        if m_en:
            if current_lang_block and current_block_lines:
                current["text"][current_lang_block] = "\n".join(current_block_lines).strip()
                current_block_lines = []
            current_lang_block = None
            checked = m_en.group(1).strip().lower() == "x"
            rest = m_en.group(2)
            current["approval_idx"]["en"] = i
            if "PUBLISHED" in rest.upper():
                current["status"]["en"] = "published"
            elif "SKIP" in rest.upper():
                current["status"]["en"] = "skip"
            elif checked:
                current["status"]["en"] = "approved"
            else:
                current["status"]["en"] = "unapproved"
            continue
        if m_es:
            if current_lang_block and current_block_lines:
                current["text"][current_lang_block] = "\n".join(current_block_lines).strip()
                current_block_lines = []
            current_lang_block = None
            checked = m_es.group(1).strip().lower() == "x"
            rest = m_es.group(2)
            current["approval_idx"]["es"] = i
            if "PUBLISHED" in rest.upper():
                current["status"]["es"] = "published"
            elif "SKIP" in rest.upper():
                current["status"]["es"] = "skip"
            elif checked:
                current["status"]["es"] = "approved"
            else:
                current["status"]["es"] = "unapproved"
            continue
        if m_old:
            checked = m_old.group(1).strip().lower() == "x"
            status = "approved" if checked else "unapproved"
            if current["status"]["en"] == "none":
                current["status"]["en"] = status
            if current["status"]["es"] == "none":
                current["status"]["es"] = status
            continue

        if re.match(r"^\s*\*\*EN:?\*\*\s*$", line):
            if current_lang_block and current_block_lines:
                current["text"][current_lang_block] = "\n".join(current_block_lines).strip()
            current_lang_block = "en"
            current_block_lines = []
            continue
        if re.match(r"^\s*\*\*ES:?\*\*\s*$", line):
            if current_lang_block and current_block_lines:
                current["text"][current_lang_block] = "\n".join(current_block_lines).strip()
            current_lang_block = "es"
            current_block_lines = []
            continue

        if line.strip() == "---":
            if current_lang_block and current_block_lines:
                current["text"][current_lang_block] = "\n".join(current_block_lines).strip()
                current_block_lines = []
            current_lang_block = None
            continue

        if current_lang_block:
            current_block_lines.append(line)

    if current:
        if current_lang_block and current_block_lines:
            current["text"][current_lang_block] = "\n".join(current_block_lines).strip()
        sections.append(current)

    for s in sections:
        if s["status"][lang] == "approved" and s["text"][lang].strip():
            return s, sections
    return None, sections


def publish_note(text: str, pub: dict) -> dict:
    body_json = md_to_note_body(text)
    payload = {
        "bodyJson": body_json,
        "tabId": "for-you",
        "surface": "feed",
        "replyMinimumRole": "everyone",
        "attachmentIds": [],
    }
    return api_post(f"{GLOBAL_BASE}/comment/feed/", pub, payload)


def verify_note_landed(note_id, pub, user_id):
    """Fetch recent Notes, confirm the new ID appears."""
    time.sleep(1.5)
    result = api_get(f"{GLOBAL_BASE}/reader/feed/profile/{user_id}?types=note&limit=5", pub)
    if "error" in result:
        return False, f"verify failed: {result['error']}"
    items = result.get("items", [])
    for it in items:
        if str(it.get("comment", {}).get("id")) == str(note_id):
            return True, "verified via list_my_notes"
    return False, f"note_id {note_id} not in latest 5 Notes"


def append_log(entry: dict):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_PATH.exists():
        LOG_PATH.write_text(
            "---\ntype: publishing-log\ncreationDate: 2026-04-15\n---\n\n"
            "# Substack Publishing Log\n\n"
            "Auto-generated by publish_from_queue.py. Each row: timestamp, lang, status, note_id, section, preview.\n\n"
            "| Timestamp | Lang | Status | Note ID | Section | Preview |\n"
            "|---|---|---|---|---|---|\n"
        )
    ts = entry["timestamp"]
    row = f"| {ts} | {entry['lang']} | {entry['status']} | {entry.get('note_id', '.')} | {entry.get('section', '.')} | {entry.get('preview', '.')} |\n"
    with LOG_PATH.open("a") as f:
        f.write(row)


def mark_published(queue_text: str, section, lang: str, note_id, date_str: str) -> str:
    """Replace the approval line with a PUBLISHED marker."""
    lines = queue_text.split("\n")
    idx = section["approval_idx"][lang]
    if idx is None:
        header_idx = section["header_idx"]
        new_line = f"- [x] {lang.upper()} PUBLISHED {date_str} id:{note_id}"
        lines.insert(header_idx + 1, new_line)
    else:
        old = lines[idx]
        m = re.match(r"(\s*-\s*\[[xX]\]\s*(EN|ES))\b.*", old)
        if m:
            lines[idx] = f"{m.group(1)} PUBLISHED {date_str} id:{note_id}"
        else:
            lines[idx] = f"- [x] {lang.upper()} PUBLISHED {date_str} id:{note_id}"
    return "\n".join(lines)


def user_id_for(pub):
    result = api_get(f"{GLOBAL_BASE}/user/profile/self", pub)
    if "error" in result:
        return None
    return result.get("id")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=["en", "es"], help="Language to publish")
    ap.add_argument("--dry-run", action="store_true", help="Show what would happen, don't post")
    ap.add_argument("--test", action="store_true", help="Publish a [TEST] placeholder to verify pipeline end-to-end")
    args = ap.parse_args()

    if args.test:
        lang = args.lang or "en"
        pub = get_pub(lang)
        test_text = f"[TEST] Pipeline verification ping at {datetime.utcnow().isoformat()}Z. Please ignore."
        print(f"TEST MODE: publishing to {pub['subdomain']} ({lang})")
        if args.dry_run:
            print(f"DRY RUN: would publish: {test_text}")
            return 0
        result = publish_note(test_text, pub)
        print(json.dumps(result, indent=2)[:500])
        if "error" in result:
            return 2
        note_id = result.get("id")
        uid = user_id_for(pub)
        ok, msg = verify_note_landed(note_id, pub, uid)
        print(f"VERIFY: {ok}. {msg}")
        append_log({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "lang": lang,
            "status": "TEST_OK" if ok else "TEST_UNVERIFIED",
            "note_id": note_id,
            "section": "[TEST]",
            "preview": test_text[:60],
        })
        print(f"URL: https://substack.com/notes/post/p-{note_id}")
        return 0 if ok else 3

    if not args.lang:
        ap.error("--lang is required unless --test")

    pub = get_pub(args.lang)
    queue_text = QUEUE_PATH.read_text()
    section, all_sections = parse_queue(queue_text, args.lang)

    if section is None:
        approved = sum(1 for s in all_sections if s["status"][args.lang] == "approved")
        published = sum(1 for s in all_sections if s["status"][args.lang] == "published")
        unapproved = sum(1 for s in all_sections if s["status"][args.lang] == "unapproved")
        print(f"NO APPROVED UNPUBLISHED {args.lang.upper()} ITEMS. "
              f"Stats: approved={approved} published={published} unapproved={unapproved}")
        append_log({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "lang": args.lang,
            "status": "QUEUE_EMPTY",
            "section": ".",
            "preview": f"approved={approved} published={published} unapproved={unapproved}",
        })
        return 1

    text = section["text"][args.lang]
    preview = text[:60].replace("\n", " ")
    print(f"Next {args.lang.upper()}: #{section['number']} {section['title']}")
    print(f"  Preview: {preview}")
    print(f"  Length: {len(text)} chars, {len(text.split())} words")

    if args.dry_run:
        print("DRY RUN: not publishing.")
        return 0

    print(f"Publishing to {pub['subdomain']}...")
    result = publish_note(text, pub)
    if "error" in result:
        print(f"FAILED: {result}")
        append_log({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "lang": args.lang,
            "status": "FAIL",
            "section": f"#{section['number']} {section['title']}",
            "preview": f"{preview} // error: {result['error']}",
        })
        return 2

    note_id = result.get("id")
    date_str = result.get("date", datetime.utcnow().isoformat() + "Z")[:10]
    print(f"Published. note_id={note_id}")

    uid = user_id_for(pub)
    ok, msg = verify_note_landed(note_id, pub, uid)
    print(f"VERIFY: {ok}. {msg}")

    new_queue = mark_published(queue_text, section, args.lang, note_id, date_str)
    QUEUE_PATH.write_text(new_queue)
    print(f"Queue updated: marked {args.lang.upper()} published for section {section['number']}")

    append_log({
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "lang": args.lang,
        "status": "OK" if ok else "PUBLISHED_UNVERIFIED",
        "note_id": note_id,
        "section": f"#{section['number']} {section['title']}",
        "preview": preview,
    })
    print(f"URL: https://substack.com/notes/post/p-{note_id}")
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
