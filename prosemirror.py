"""Markdown to ProseMirror JSON converter for Substack's editor format.

Converts standard markdown into the ProseMirror document schema that Substack's
Notes and Posts APIs expect. Handles: paragraphs, headings, bold, italic, links,
lists (bullet + ordered), blockquotes, code blocks, horizontal rules, images.
"""

import re


def md_to_prosemirror(text: str) -> dict:
    """Convert markdown text to ProseMirror doc JSON."""
    lines = text.split("\n")
    blocks = _split_blocks(lines)
    content = []
    for block in blocks:
        node = _parse_block(block)
        if node:
            content.append(node)
    return {"type": "doc", "attrs": {"schemaVersion": "v1"}, "content": content}


def md_to_note_body(text: str) -> dict:
    """Convert markdown text to Note body JSON (simpler schema, no headings)."""
    lines = text.split("\n")
    blocks = _split_blocks(lines)
    content = []
    for block in blocks:
        node = _parse_block(block, note_mode=True)
        if node:
            content.append(node)
    return {"type": "doc", "attrs": {"schemaVersion": "v1"}, "content": content}


def _split_blocks(lines: list[str]) -> list[list[str]]:
    """Split lines into logical blocks separated by blank lines."""
    blocks = []
    current = []
    in_code_block = False

    for line in lines:
        if line.strip().startswith("```"):
            if in_code_block:
                current.append(line)
                blocks.append(current)
                current = []
                in_code_block = False
            else:
                if current:
                    blocks.append(current)
                current = [line]
                in_code_block = True
        elif in_code_block:
            current.append(line)
        elif line.strip() == "":
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(line)

    if current:
        blocks.append(current)
    return blocks


def _parse_block(lines: list[str], note_mode: bool = False) -> dict | None:
    """Parse a block of lines into a ProseMirror node."""
    if not lines:
        return None

    first = lines[0]

    # Horizontal rule
    if first.strip() in ("---", "***", "___") and len(lines) == 1:
        return {"type": "horizontal_rule"}

    # Code block
    if first.strip().startswith("```"):
        lang = first.strip().lstrip("`").strip()
        code_lines = lines[1:]
        # Remove closing ```
        if code_lines and code_lines[-1].strip().startswith("```"):
            code_lines = code_lines[:-1]
        code_text = "\n".join(code_lines)
        node = {"type": "codeBlock", "content": [{"type": "text", "text": code_text}]}
        if lang:
            node["attrs"] = {"language": lang}
        return node

    # Heading (convert to paragraph with bold in note mode)
    heading_match = re.match(r"^(#{1,6})\s+(.+)$", first)
    if heading_match:
        level = len(heading_match.group(1))
        text = heading_match.group(2)
        if note_mode:
            return _make_paragraph(_parse_inline("**" + text + "**"))
        return {
            "type": "heading",
            "attrs": {"level": level},
            "content": _parse_inline(text),
        }

    # Blockquote
    if first.startswith("> "):
        quote_text = "\n".join(line.lstrip("> ").lstrip(">") for line in lines)
        inner_lines = quote_text.split("\n")
        inner_blocks = _split_blocks(inner_lines)
        inner_content = []
        for block in inner_blocks:
            node = _parse_block(block, note_mode)
            if node:
                inner_content.append(node)
        if not inner_content:
            inner_content = [_make_paragraph(_parse_inline(quote_text))]
        return {"type": "blockquote", "content": inner_content}

    # Bullet list
    if re.match(r"^[\-\*]\s+", first):
        items = _parse_list_items(lines, r"^[\-\*]\s+")
        return {
            "type": "bulletList",
            "content": [
                {
                    "type": "listItem",
                    "content": [_make_paragraph(_parse_inline(item))],
                }
                for item in items
            ],
        }

    # Ordered list
    if re.match(r"^\d+\.\s+", first):
        items = _parse_list_items(lines, r"^\d+\.\s+")
        return {
            "type": "orderedList",
            "content": [
                {
                    "type": "listItem",
                    "content": [_make_paragraph(_parse_inline(item))],
                }
                for item in items
            ],
        }

    # Image (standalone line)
    img_match = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", first.strip())
    if img_match and len(lines) == 1:
        alt = img_match.group(1)
        src = img_match.group(2)
        return {
            "type": "captionedImage",
            "attrs": {"src": src, "alt": alt, "title": alt},
        }

    # Default: paragraph
    full_text = "\n".join(lines)
    inline = _parse_inline(full_text)
    if not inline:
        return None
    return _make_paragraph(inline)


def _make_paragraph(content: list[dict]) -> dict:
    """Wrap inline content in a paragraph node."""
    return {"type": "paragraph", "content": content}


def _parse_list_items(lines: list[str], pattern: str) -> list[str]:
    """Extract list item texts from consecutive list lines."""
    items = []
    for line in lines:
        cleaned = re.sub(pattern, "", line, count=1)
        items.append(cleaned)
    return items


def _parse_inline(text: str) -> list[dict]:
    """Parse inline markdown (bold, italic, links, code) into text nodes with marks."""
    if not text.strip():
        return [{"type": "text", "text": " "}]

    nodes = []
    # Regex for inline elements: bold, italic, bold+italic, code, links
    # Order matters: bold+italic before bold before italic
    pattern = re.compile(
        r"(\*\*\*(.+?)\*\*\*)"  # bold+italic
        r"|(\*\*(.+?)\*\*)"  # bold
        r"|(\*(.+?)\*)"  # italic
        r"|(`([^`]+)`)"  # inline code
        r"|(\[([^\]]+)\]\(([^)]+)\))"  # link
        r"|(~~(.+?)~~)"  # strikethrough
    )

    pos = 0
    for m in pattern.finditer(text):
        # Plain text before this match
        if m.start() > pos:
            plain = text[pos : m.start()]
            if plain:
                nodes.append({"type": "text", "text": plain})

        if m.group(2):  # bold+italic
            nodes.append(
                {
                    "type": "text",
                    "text": m.group(2),
                    "marks": [{"type": "bold"}, {"type": "italic"}],
                }
            )
        elif m.group(4):  # bold
            nodes.append(
                {
                    "type": "text",
                    "text": m.group(4),
                    "marks": [{"type": "bold"}],
                }
            )
        elif m.group(6):  # italic
            nodes.append(
                {
                    "type": "text",
                    "text": m.group(6),
                    "marks": [{"type": "italic"}],
                }
            )
        elif m.group(8):  # code
            nodes.append(
                {
                    "type": "text",
                    "text": m.group(8),
                    "marks": [{"type": "code"}],
                }
            )
        elif m.group(10):  # link
            link_text = m.group(10)
            link_href = m.group(11)
            nodes.append(
                {
                    "type": "text",
                    "text": link_text,
                    "marks": [{"type": "link", "attrs": {"href": link_href}}],
                }
            )
        elif m.group(13):  # strikethrough
            nodes.append(
                {
                    "type": "text",
                    "text": m.group(13),
                    "marks": [{"type": "strikethrough"}],
                }
            )

        pos = m.end()

    # Remaining plain text
    if pos < len(text):
        remaining = text[pos:]
        if remaining:
            nodes.append({"type": "text", "text": remaining})

    return nodes if nodes else [{"type": "text", "text": text}]
