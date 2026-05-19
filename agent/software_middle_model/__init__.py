"""Software middle-layer small model interfaces.

This package is intentionally independent from the heavy training/runtime stack.
It provides a deterministic, CPU-only seam where a future small model can learn
to shortcut or prioritize expensive software-engineering rules.
"""

from .accelerator import MiddleModelInput, decide_with_middle_model
from .program import build_software_middle_model_plan
from .traces import append_middle_model_trace, build_middle_model_trace, load_middle_model_traces

__all__ = [
    "MiddleModelInput",
    "append_middle_model_trace",
    "build_middle_model_trace",
    "build_software_middle_model_plan",
    "decide_with_middle_model",
    "load_middle_model_traces",
]
