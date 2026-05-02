"""Centralised numeric / textual constants for backend services.

The goal is to keep tweakable thresholds, retry knobs and protocol limits in
one place so an SRE can change behaviour without grepping every services/
file. Submodules are grouped by domain:

- :mod:`app.constants.nec_limits`   — NEC Jewel POS field-length / format limits
                                      (must match the vendor spec).
- :mod:`app.constants.thresholds`   — Inventory + replenishment defaults
                                      that store overrides may later replace.
- :mod:`app.constants.ai_confidence`— Heuristic confidence scores attached to
                                      copilot recommendations. Tunable.

Each constant has a docstring explaining the source / why-this-number. When
adding a new constant: prefer SCREAMING_SNAKE_CASE, give it a comment, and
re-export it here.
"""
from app.constants import ai_confidence, nec_limits, thresholds

__all__ = ["ai_confidence", "nec_limits", "thresholds"]
