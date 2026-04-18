"""Stub adapter for Midjourney image generation.

To implement:
    1. Build a prompt from spec["quote"], spec["pillar"], and optional style hints.
    2. Submit to the Midjourney API (or an unofficial proxy such as useapi.net).
    3. Poll until the job completes, download the resulting image.
    4. Write to spec["output_path"] (or config["midjourney"]["output_dir"]).
    5. Return a GenerateResult dict with status="ok", image_path, width, height.

Config keys (under image_generator.midjourney in config.json):
  api_key (str): Your Midjourney API key.
  output_dir (str): Directory for downloaded images. Default /tmp.
  aspect_ratio (str): Aspect ratio flag. Default "1:1" for 1080x1080 cards.
  style_suffix (str): Optional prompt suffix (e.g. "--style raw --v 6").

Contributions welcome.
"""

from .base import ImageGenerator


class MidjourneyAdapter(ImageGenerator):
    """Stub: Midjourney API."""

    @property
    def name(self) -> str:
        return "midjourney"

    def generate(self, spec: dict) -> dict:
        # STUB: replace with Midjourney API call
        raise NotImplementedError(
            "MidjourneyAdapter is not yet implemented. "
            "See image_generators/midjourney.py for the implementation contract."
        )
