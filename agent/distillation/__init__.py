"""Teacher-model distillation control-plane contracts."""

from .catalog import list_teacher_models, list_teacher_tasks
from .plans import build_distillation_plan, build_teacher_task_suite
from .datasets import build_distillation_dataset_manifest

__all__ = [
    "build_distillation_dataset_manifest",
    "build_distillation_plan",
    "build_teacher_task_suite",
    "list_teacher_models",
    "list_teacher_tasks",
]
