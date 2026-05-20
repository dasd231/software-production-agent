"""Software middle-layer small model interfaces.

This package is intentionally independent from the heavy training/runtime stack.
It provides a deterministic, CPU-only seam where a future small model can learn
to shortcut or prioritize expensive software-engineering rules.
"""

from .accelerator import MiddleModelInput, decide_with_middle_model
from .dataset import MiddleModelDatasetExportInput, export_middle_model_trace_dataset
from .program import build_software_middle_model_plan
from .server_handoff import MiddleModelServerHandoffInput, prepare_middle_model_server_handoff
from .traces import append_middle_model_trace, build_middle_model_trace, load_middle_model_traces

__all__ = [
    "MiddleModelInput",
    "MiddleModelDatasetExportInput",
    "MiddleModelServerHandoffInput",
    "append_middle_model_trace",
    "build_middle_model_trace",
    "build_software_middle_model_plan",
    "decide_with_middle_model",
    "export_middle_model_trace_dataset",
    "load_middle_model_traces",
    "prepare_middle_model_server_handoff",
]
