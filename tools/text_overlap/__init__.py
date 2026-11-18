"""Text-overlap checking for DXF drawings.

Entry points:
    textbox.measure_text(entity)  - a text entity's WCS box, calibrated
    overlap.detect(path)          - run both checks, get a report dict

Run it as a command:
    python -m tools.text_overlap FILE.dxf
"""

from .overlap import Finding, detect
from .textbox import Box, calibrate, measure_text

__all__ = ["Finding", "detect", "Box", "calibrate", "measure_text"]