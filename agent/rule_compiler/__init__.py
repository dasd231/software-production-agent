"""Business semantic compiler.

The compiler turns business rules into product-system contracts: database
schemas, state machines, permission matrices, API contracts and validation
findings. It is intentionally deterministic today so it can become the
teacher/label surface for a future small rule-translation model.
"""

from agent.rule_compiler.compiler import compile_business_rules
from agent.rule_compiler.schema import BusinessRuleCompilation

__all__ = ["BusinessRuleCompilation", "compile_business_rules"]

