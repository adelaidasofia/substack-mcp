"""Stub adapter for Gemini 3 Pro Image via the nano-banana skill.

To implement:
    1. Build a text prompt from spec["quote"], spec["pillar"], and optional
       spec["style_prompt"].
    2. Call the nano-banana skill's image generation endpoint with that prompt.
    3. Download or copy the resulting image to spec["output_path"] (or a
       default in config["nano_banana"]["output_dir"]).
    4. Return a GenerateResult dict with status="ok", image_path, width, height.

Config keys (under image_generator.nano_banana in config.json):
  output_dir (str): Directory for downloaded images. Default /tmp.
  style_prompt (str): Optional prompt prefix to steer the visual style.
  model (str): Gemini model identifier (default "gemini-3-pro-image").

Contributions welcome.
"""

from .base import ImageGenerator


class NanaBananaAdapter(ImageGenerator):
    """Stub: Gemini 3 Pro Image via nano-banana skill."""

    @property
    def name(self) -> str:
        return "nano_banana"

    def generate(self, spec: dict) -> dict:
        # STUB: replace with nano-banana skill call
        raise NotImplementedError(
            "NanaBananaAdapter is not yet implemented. "
            "See image_generators/nano_banana.py for the implementation contract."
        )
