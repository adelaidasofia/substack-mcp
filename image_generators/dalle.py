"""Stub adapter for OpenAI DALL-E image generation.

To implement:
    1. Build a prompt from spec["quote"], spec["pillar"], and optional
       style hints from config.
    2. Call the OpenAI Images API (client.images.generate).
    3. Download the resulting image to spec["output_path"] (or a default
       under config["dalle"]["output_dir"]).
    4. Return a GenerateResult dict with status="ok", image_path, width, height.

Config keys (under image_generator.dalle in config.json):
  api_key (str): OpenAI API key. Reads OPENAI_API_KEY env var if omitted.
  model (str): "dall-e-3" or "dall-e-2". Default "dall-e-3".
  size (str): Image size. Default "1024x1024".
  output_dir (str): Directory for downloaded images. Default /tmp.
  style (str): "vivid" or "natural" (dall-e-3 only). Default "natural".

Contributions welcome.
"""

from .base import ImageGenerator


class DalleAdapter(ImageGenerator):
    """Stub: OpenAI DALL-E."""

    @property
    def name(self) -> str:
        return "dalle"

    def generate(self, spec: dict) -> dict:
        # STUB: replace with openai.images.generate call
        raise NotImplementedError(
            "DalleAdapter is not yet implemented. "
            "Install the openai package and see image_generators/dalle.py "
            "for the implementation contract."
        )
