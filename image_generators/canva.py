"""Canva MCP adapter for Substack visual card generation.

This adapter does not render images directly. It returns a choreography dict
describing the sequence of Canva MCP tool calls needed to produce the card.
The Claude session executing the playbook follows these steps.

See Appendix A in visual_playbook.md for the full Canva flow with
tool-call details, transaction handling, and failure modes.

Config keys (under image_generator.canva in config.json):
  pillars (dict): Pillar template config keyed by "P1", "P2", "P3".
      Each entry: design_id, label, title, has_figure, figure_rotation,
      edit_url, notes.
  figure_library_path (str): Path to the folder of figure PNGs.
"""

from .base import ImageGenerator


class CanvaAdapter(ImageGenerator):
    """Canva MCP choreography adapter."""

    @property
    def name(self) -> str:
        return "canva"

    def _pillars(self) -> dict:
        canva_cfg = self.config.get("canva", {})
        # Support both image_generator.canva.pillars (new) and
        # image_generator.canva_pillars (legacy transition).
        return canva_cfg.get("pillars") or canva_cfg.get("canva_pillars") or {}

    def _figure_library_path(self) -> str:
        canva_cfg = self.config.get("canva", {})
        return canva_cfg.get("figure_library_path", "")

    def generate(self, spec: dict) -> dict:
        """Return Canva MCP choreography for producing a card.

        Does not call Canva directly. The caller (a Claude session) executes
        each step via the Canva MCP. Steps use {{placeholder}} notation for
        values that are captured from prior step responses.

        Required spec keys:
            pillar (str): "P1", "P2", or "P3".
            quote (str): Quote text to place on the card.

        Optional spec keys:
            handle (str): Handle (baked into template; included for reference).
            figure_id (str): Figure filename from the library (P1 only).
            figure_library_path (str): Override the library path from config.

        Returns:
            dict with status="choreography", adapter="canva", and "steps" list.
            Each step: step, action, tool, args, and optionally "save" (key name
            to capture from the response for use in later steps).
        """
        pillar = spec.get("pillar", "P2")
        quote = spec.get("quote", "")
        figure_id = spec.get("figure_id", "")

        pillars = self._pillars()
        pillar_cfg = pillars.get(pillar)
        if not pillar_cfg:
            return {
                "status": "error",
                "adapter": self.name,
                "error": (
                    f"No Canva config for pillar {pillar!r}. "
                    "Add it under image_generator.canva.pillars in config.json."
                ),
            }

        design_id = pillar_cfg.get("design_id", "")
        has_figure = pillar_cfg.get("has_figure", False)
        figure_rotation = pillar_cfg.get("figure_rotation", False)
        figure_library_path = (
            spec.get("figure_library_path") or self._figure_library_path()
        )

        steps = [
            {
                "step": 1,
                "action": "clone_template",
                "tool": "merge-designs",
                "args": {
                    "type": "create_new_design",
                    "title": f"Substack Note clone {pillar}",
                    "operations": [
                        {"type": "insert_pages", "source": {"type": "design", "design_id": design_id}}
                    ],
                },
                "save": "clone_design_id",
            },
            {
                "step": 2,
                "action": "start_transaction",
                "tool": "start-editing-transaction",
                "args": {"design_id": "{{clone_design_id}}"},
                "save": "transaction_id, pages, element_ids",
            },
            {
                "step": 3,
                "action": "replace_quote_text",
                "tool": "perform-editing-operations",
                "args": {
                    "transaction_id": "{{transaction_id}}",
                    "pages": "{{pages}}",
                    "operations": [
                        {
                            "type": "find_and_replace_text",
                            "element_id": "{{quote_element_id}}",
                            "find_text": "{{placeholder_quote_from_template}}",
                            "replace_text": quote,
                        }
                    ],
                },
            },
        ]

        step_num = 4
        if pillar == "P1" and has_figure and figure_rotation and figure_id:
            steps.append({
                "step": step_num,
                "action": "upload_figure",
                "tool": "upload-asset-from-url",
                "args": {"url": f"file://{figure_library_path}/{figure_id}"},
                "save": "asset_id",
            })
            step_num += 1
            steps.append({
                "step": step_num,
                "action": "replace_figure",
                "tool": "perform-editing-operations",
                "args": {
                    "transaction_id": "{{transaction_id}}",
                    "operations": [{"type": "update_fill", "asset_id": "{{asset_id}}"}],
                },
            })
            step_num += 1

        steps.append({
            "step": step_num,
            "action": "commit_transaction",
            "tool": "commit-editing-transaction",
            "args": {"transaction_id": "{{transaction_id}}"},
        })
        step_num += 1

        steps.append({
            "step": step_num,
            "action": "export_png",
            "tool": "export-design",
            "args": {
                "design_id": "{{clone_design_id}}",
                "format": {"type": "png", "width": 1080, "height": 1080, "export_quality": "pro"},
            },
            "save": "download_url",
        })

        return {
            "status": "choreography",
            "adapter": self.name,
            "pillar": pillar,
            "design_id": design_id,
            "edit_url": pillar_cfg.get("edit_url", ""),
            "steps": steps,
            "note": "Execute each step via the Canva MCP. See Appendix A in visual_playbook.md.",
        }
