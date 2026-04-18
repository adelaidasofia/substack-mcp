#!/usr/bin/env python3
"""CLI: render a Substack visual card using PillowLocalAdapter.

Usage:
  python3 render_card.py --pillar P1 --quote "..." --handle "@your-handle" \
      --figure /path/to/fig.png --output /tmp/card.png

  python3 render_card.py --pillar P2 --quote "..." --handle "@your-handle" \
      --output /tmp/card.png

Returns JSON: {status, adapter, image_path, width, height, pillar}
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from image_generators import get_image_generator


def main():
    ap = argparse.ArgumentParser(description="Render a Substack visual card locally")
    ap.add_argument("--pillar", required=True, choices=["P1", "P2", "P3"])
    ap.add_argument("--quote", required=True, help="Quote text for the card")
    ap.add_argument("--handle", required=True, help="Handle shown at the bottom (e.g. @your-handle)")
    ap.add_argument("--figure", help="Figure PNG path (P1 only)")
    ap.add_argument("--output", required=True, help="Output PNG path")
    args = ap.parse_args()

    gen = get_image_generator("pillow_local", {})
    result = gen.generate({
        "pillar": args.pillar,
        "quote": args.quote,
        "handle": args.handle,
        "figure_path": args.figure,
        "output_path": args.output,
    })
    print(json.dumps(result))
    sys.exit(0 if result.get("status") == "ok" else 1)


if __name__ == "__main__":
    main()
