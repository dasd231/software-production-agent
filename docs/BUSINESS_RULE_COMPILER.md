# Business Rule Compiler

这个模块对应待办里的“规则翻译大模型 / 业务语义编译层”。

它不是把自然语言直接翻译成 Python，而是把业务规则编译成系统契约：

```text
自然语言规则
  -> 数据库实体 / 字段 / 索引 / 约束
  -> 状态机 / 状态迁移 / 副作用边界
  -> 权限矩阵 / 角色作用域
  -> API 契约 / 幂等键 / 响应结构
  -> 运行时隐藏层 / 渐进增强计划 / 风险提示
```

入口：

```text
agent/rule_compiler/
tests/test_business_rule_compiler.py
```

executor action：

```json
{
  "type": "action",
  "action": "business_rule_compile",
  "args": {
    "rules": "用户签收后 7 天内可以申请退货退款。客服审核，仓库质检，财务退款。",
    "domain_hint": "return_refund",
    "output_path": "plans/rules.json"
  }
}
```

权限要求：

```text
business:compile + workspace:write
```

## 为什么这块重要

通用 LLM 可以写 CRUD，但企业系统真正难的是业务语义落地：

- “退货规则”不是一个 if，而是状态机。
- “客服审核”不是一句注释，而是权限矩阵。
- “财务退款”不是直接改数据库，而是外部支付副作用 + outbox + 对账。
- “上线后可增强”意味着不能推倒重来，要能从人工流程渐进到自动化。

因此这个模块输出的是平台契约，而不是零散代码。

## 当前能力

以退货退款为例，编译器会生成：

- `ReturnRequest`
- `ReturnAuditEvent`
- 可选 `ReturnInspection`
- `submitted -> under_review -> approved -> goods_returning -> inspecting -> refund_pending -> refunded -> closed`
- customer / support_agent / warehouse_operator / finance / admin 权限矩阵
- REST API 契约
- 幂等、审计、租户隔离、金额上限、外部副作用 outbox 等不变量

## 和“小模型”的关系

当前实现是确定性编译器，适合做三件事：

1. 给产品系统先落一个可靠控制面。
2. 生成高质量训练标签，用来蒸馏“规则翻译小模型”。
3. 作为 LLM 输出的 verifier：模型生成规则契约后，由编译器检查缺字段、缺状态、缺权限。

后续可以接：

- rule-to-contract SFT
- rule inconsistency detection
- domain-specific ontology
- migration/codegen
- Spring/FastAPI controller scaffold

## 当前边界

已完成控制面、协议动作和测试。还未生成真实数据库 migration、真实后端 controller、真实前端配置页面。下一步应该把 `BusinessRuleCompilation` 接到代码生成器：先生成 SQLAlchemy/FastAPI 或 Spring Boot skeleton，再接 UI 配置。

