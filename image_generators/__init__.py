"""Pluggable image generator package for substack-mcp.

Usage:
    from image_generators import get_image_generator

    gen = get_image_generator("pillow_local", config.get("image_generator", {}))
    result = gen.generate({"pillar": "P2", "quote": "...", "handle": "@you"})
    # result["image_path"] -> local PNG path

Shipped adapters:
    pillow_local  -- pure Pillow, no external API (default)
    canva         -- Canva MCP choreography

Stubbed adapters (contributions welcome):
    nano_banana   -- Gemini 3 Pro Image via nano-banana skill
    midjourney    -- Midjourney API
    dalle         -- OpenAI DALL-E
"""

from .base import ImageGenerator

_REGISTRY = {
    "pillow_local": ("pillow_local", "PillowLocalAdapter"),
    "canva": ("canva", "CanvaAdapter"),
    "nano_banana": ("nano_banana", "NanaBananaAdapter"),
    "midjourney": ("midjourney", "MidjourneyAdapter"),
    "dalle": ("dalle", "DalleAdapter"),
}


def get_image_generator(name: str, config: dict) -> ImageGenerator:
    """Return an ImageGenerator instance for the given adapter name.

    Args:
        name: Adapter name. One of: pillow_local, canva, nano_banana,
              midjourney, dalle.
        config: The image_generator config block from config.json. Each
                adapter reads its own sub-key (e.g. config["pillow_local"]).

    Raises:
        ValueError: Unknown adapter name.
        ImportError: Adapter dependencies not installed.
    """
    if name not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY))
        raise ValueError(f"Unknown image generator: {name!r}. Known adapters: {known}")

    module_name, class_name = _REGISTRY[name]
    import importlib
    module = importlib.import_module(f".{module_name}", package=__name__)
    cls = getattr(module, class_name)
    return cls(config)


__all__ = ["ImageGenerator", "get_image_generator"]
