"""Base contract for all image generator adapters."""

from abc import ABC, abstractmethod


class ImageGenerator(ABC):
    """Abstract base class for Substack visual card generators.

    All adapters implement generate(spec) and return a GenerateResult dict.

    CardSpec keys (all adapters should handle these):
        pillar (str): Template pillar ID, e.g. "P1", "P2", "P3".
        quote (str): Quote text for the card.
        handle (str): Handle or attribution shown at bottom of the card.
        figure_path (str | None): Path to a figure PNG (P1 only, optional).
        output_path (str | None): Where to write the result. Adapter chooses
            a default if omitted.

    GenerateResult keys:
        status (str): "ok", "error", or "choreography" (Canva adapter).
        adapter (str): Adapter name.
        image_path (str): Absolute path to the generated PNG. Present on "ok".
        width (int): Image width in pixels. Present on "ok".
        height (int): Image height in pixels. Present on "ok".
        error (str): Error message. Present on "error".
        Adapters may add extra keys (e.g. design_id for Canva, cdn_url for DALL-E).
    """

    def __init__(self, config: dict):
        """
        Args:
            config: The full image_generator config block from config.json.
                    Each adapter reads its own sub-key.
        """
        self.config = config

    @property
    def name(self) -> str:
        """Human-readable adapter name."""
        return self.__class__.__name__

    @abstractmethod
    def generate(self, spec: dict) -> dict:
        """Generate or produce a card image from spec.

        Returns a GenerateResult dict. See class docstring for key contracts.
        """
        ...
