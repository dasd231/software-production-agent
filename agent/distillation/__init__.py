"""Teacher-model distillation control-plane contracts."""

from .catalog import list_teacher_models, list_teacher_tasks
from .datasets import build_distillation_dataset_manifest
from .execution import build_teacher_execution_plan
from .export import export_distillation_training_examples
from .plans import build_distillation_plan, build_teacher_task_suite
from .prompts import build_teacher_prompt_batch
from .review import review_teacher_outputs
from .runtime import run_teacher_execution

__all__ = [
    "build_distillation_dataset_manifest",
    "build_distillation_plan",
    "build_teacher_execution_plan",
    "build_teacher_prompt_batch",
    "build_teacher_task_suite",
    "export_distillation_training_examples",
    "list_teacher_models",
    "list_teacher_tasks",
    "review_teacher_outputs",
    "run_teacher_execution",
]
