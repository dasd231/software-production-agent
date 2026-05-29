"""Product UI smoke tests.

函数流程图：
    test_product_ui_home_has_two_product_modes()
      -> GET /
      -> 断言用户侧只保留“默认生产”和“LLM 生成”
    test_product_ui_local_production_run_outputs_workspace_files()
      -> POST /run local_production
      -> 断言完整走 Agent loop、内部文件隐藏、文件读取守卫有效
    test_product_ui_local_production_can_scaffold_management_system()
      -> POST /run local_production with management-system goal
      -> 断言高成熟度文档、员工 CRUD、参考数据、测试、方案备份、静态预览、sandbox manifest 和 CSP
    test_product_ui_can_improve_existing_run_as_new_iteration()
      -> POST /runs/<run_id>/improve
      -> 断言复制上一版用户产物、写入改进上下文、保留 lineage 且不复制内部文件
    test_product_ui_downloads_artifact_zip_without_agent_internals()
      -> GET /download
      -> 断言 ZIP 只包含用户产物和方案备份
    test_product_ui_groq_llm_requires_groq_key()
      -> POST /run llm
      -> 断言 API 模式仍要求 provider key

你可以继续练算法/工程化的点：
    1. UI 验收：现在用字符串断言；后续可加 Playwright 截图和可访问性检查。
    2. 成熟度算法：现在只验证关键文字；后续可断言评分区间和缺口项。
    3. 安全测试：可加入恶意 manifest、路径穿越和 CSP 回归用例。
    4. 方案检索：当前只测备份文件存在；后续可测 solution_manifest 索引和召回。
"""

from __future__ import annotations

import zipfile
import time
from io import BytesIO
from pathlib import Path

import pytest

pytest.importorskip("flask")

from agent.ui.app import ProductTaskQueue, create_app


def _login(client, username: str = "admin", password: str = "adminpass123") -> None:
    resp = client.post(
        "/register",
        data={"username": username, "password": password},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_product_ui_home_has_two_product_modes(tmp_path: Path) -> None:
    app = create_app(runs_root=tmp_path)
    client = app.test_client()

    locked = client.get("/")
    assert locked.status_code == 302
    assert "/login" in locked.headers["Location"]
    _login(client)
    resp = client.get("/")
    text = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert text.count('name="goal"') == 1
    assert 'name="mode" value="local_production"' in text
    assert 'name="mode" value="llm"' in text
    assert "默认生产" in text
    assert "LLM 生成" in text
    assert "admin · admin" in text
    assert "资源中心" in text
    assert "创新雷达" in text
    assert "意图编排" in text
    assert "方案备份" in text
    assert "前端沙盒" not in text
    assert "离线闭环" not in text
    assert "Codex 任务包" not in text
    assert "LLM + Planner" not in text
    assert 'name="provider" value="openai"' in text
    assert 'name="provider" value="groq"' in text
    assert 'name="provider" value="deepseek"' in text
    assert 'name="custom_model"' in text

    resources = client.get("/resources")
    assert resources.status_code == 200
    resources_text = resources.get_data(as_text=True)
    assert "资源清单" in resources_text
    assert "系统当前可用能力" in resources_text
    assert "搜索资源" in resources_text
    assert "全部展开" in resources_text
    api_resources = client.get("/api/resources?type=chain")
    assert api_resources.status_code == 200
    assert api_resources.get_json()["summary"]["by_type"]["chain"] >= 1
    api_integrations = client.get("/api/integrations")
    assert api_integrations.status_code == 200
    assert api_integrations.get_json()["schema"] == "integration_catalog.v1"
    api_integration_plan = client.post(
        "/api/integrations/embed-plan",
        json={
            "integration_id": "figma",
            "resource_url": "https://www.figma.com/file/abc123/Product-Design",
            "mode": "embed_panel",
            "requested_capabilities": ["frame_selection"],
        },
    )
    assert api_integration_plan.status_code == 200
    assert api_integration_plan.get_json()["admission"]["embeddable"] is True
    api_model_runtime = client.get("/api/model-runtime?probe=0")
    assert api_model_runtime.status_code == 200
    assert api_model_runtime.get_json()["schema"] == "model_runtime_status.v1"
    api_model_pools = client.get("/api/model-pools")
    assert api_model_pools.status_code == 200
    assert api_model_pools.get_json()["schema"] == "model_pool_catalog.v1"
    api_model_route = client.post(
        "/api/model-route-plan",
        json={"goal": "长上下文RAG请求，要求JSON输出", "require_json": True, "max_output_tokens": 1200},
    )
    assert api_model_route.status_code == 200
    assert api_model_route.get_json()["selected_pool"] == "agent_pool"
    api_admission_status = client.get("/api/model-admission/status")
    assert api_admission_status.status_code == 200
    assert api_admission_status.get_json()["schema"] == "model_admission_status.v1"
    api_admission = client.post(
        "/api/model-admission/acquire",
        json={"goal": "短API请求", "max_output_tokens": 256, "idempotency_key": "ui-test"},
    )
    assert api_admission.status_code == 200
    assert api_admission.get_json()["admitted"] is True
    api_renew = client.post(
        "/api/model-admission/renew",
        json={"lease_id": api_admission.get_json()["lease"]["lease_id"], "lease_ttl_s": 30},
    )
    assert api_renew.status_code == 200
    assert api_renew.get_json()["schema"] == "model_admission_renewal.v1"
    assert api_renew.get_json()["renewed"] is True
    assert api_renew.get_json()["lease_id"] == api_admission.get_json()["lease"]["lease_id"]
    api_release = client.post(
        "/api/model-admission/release",
        json={"lease_id": api_admission.get_json()["lease"]["lease_id"]},
    )
    assert api_release.status_code == 200
    assert api_release.get_json()["released"] is True
    api_enterprise = client.post(
        "/api/enterprise-stack",
        json={"goal": "上市企业私有化 AI 平台，支持 100+ 终端、灰度和 vLLM", "scale": "listed", "regulated": True},
    )
    assert api_enterprise.status_code == 200
    enterprise_json = api_enterprise.get_json()
    assert enterprise_json["schema"] == "enterprise_stack_plan.v1"
    assert enterprise_json["scenario_solutions"]
    api_maturity = client.post(
        "/api/industrial-maturity",
        json={"goal": "军工工业级 AI CTO 审查成熟度", "scale": "listed", "regulated": True},
    )
    assert api_maturity.status_code == 200
    maturity_json = api_maturity.get_json()
    assert maturity_json["schema"] == "industrial_maturity_plan.v1"
    assert maturity_json["cto_interrogation_pack"]
    api_readiness = client.get("/api/enterprise-readiness")
    assert api_readiness.status_code == 200
    assert api_readiness.get_json()["schema"] == "enterprise_readiness_report.v1"
    innovation = client.get("/innovation")
    assert innovation.status_code == 200
    innovation_text = innovation.get_data(as_text=True)
    assert "创新机会卡" in innovation_text
    assert "平台能力评分" in innovation_text
    assert "当前最值得优先推进" in innovation_text
    assert "全部展开" in innovation_text
    api_innovation = client.get("/api/innovation")
    assert api_innovation.status_code == 200
    assert api_innovation.get_json()["schema"] == "innovation_radar.v1"
    intent_page = client.get("/intent")
    assert intent_page.status_code == 200
    assert "意图编排" in intent_page.get_data(as_text=True)
    intent_post = client.post("/intent", data={"goal": "爬取前后端项目并沉淀方案资产"})
    assert intent_post.status_code == 200
    assert "编排结果" in intent_post.get_data(as_text=True)
    api_intent = client.post("/api/intent/compile", json={"goal": "爬取前后端项目并训练微调"})
    assert api_intent.status_code == 200
    assert api_intent.get_json()["schema"] == "intent_compilation.v1"
    api_dry = client.post(
        "/api/workflow/dry-run",
        json={"spec": {"schema": "workflow.v1", "version": "demo", "nodes": ["research"], "edges": []}},
    )
    assert api_dry.status_code == 200
    assert api_dry.get_json()["schema"] == "workflow_dry_run.v1"
    api_ledger = client.post("/api/evidence-ledger", json={"output_path": "evidence_ledger.json"})
    assert api_ledger.status_code == 200
    assert api_ledger.get_json()["schema"] == "evidence_ledger.v1"


def test_product_ui_local_production_run_outputs_workspace_files(tmp_path: Path) -> None:
    app = create_app(runs_root=tmp_path)
    client = app.test_client()
    _login(client)

    resp = client.post(
        "/run",
        data={"goal": "写一个接口 /hello 返回 ok", "mode": "local_production", "events": "1"},
        follow_redirects=True,
    )
    text = resp.get_data(as_text=True)
    run_dirs = [path for path in tmp_path.iterdir() if path.is_dir()]

    assert resp.status_code == 200
    assert "finished:" in text
    assert "项目成熟度" in text
    assert "满意并沉淀到方案库" in text
    assert "result-dashboard" in text
    assert ".agent_state.json" not in text
    assert ".agent_events.jsonl" not in text
    assert len(run_dirs) == 1
    workspace = run_dirs[0]
    assert (workspace / "app.py").exists()
    assert (workspace / "docs" / "SOLUTION_BACKUP.md").exists()
    assert (workspace / "solution_manifest.json").exists()
    assert (workspace / ".agent_state.json").exists()
    assert (workspace / ".agent_events.jsonl").exists()

    file_resp = client.get(f"/runs/{workspace.name}/files/app.py")
    assert file_resp.status_code == 200
    assert "from flask import Flask" in file_resp.get_data(as_text=True)

    internal_resp = client.get(f"/runs/{workspace.name}/files/.agent_state.json")
    assert internal_resp.status_code == 404
    publish_resp = client.post(
        f"/runs/{workspace.name}/publish-solution",
        json={"output_dir": "solution_library", "title": "hello-api"},
    )
    assert publish_resp.status_code == 200
    assert publish_resp.get_json()["schema"] == "solution_publish_result.v1"
    assert publish_resp.get_json()["manifest"]["acceptance_status"] == "accepted"

    accepted_page = client.get(f"/runs/{workspace.name}")
    assert "确认满意，并沉淀到正式方案库" in accepted_page.get_data(as_text=True)


def test_product_ui_local_production_can_scaffold_management_system(tmp_path: Path) -> None:
    app = create_app(runs_root=tmp_path)
    client = app.test_client()
    _login(client)

    resp = client.post(
        "/run",
        data={"goal": "写一个人员管理系统", "mode": "local_production", "events": "1"},
        follow_redirects=True,
    )
    text = resp.get_data(as_text=True)
    run_dirs = [path for path in tmp_path.iterdir() if path.is_dir()]

    assert resp.status_code == 200
    assert "finished:" in text
    assert "项目成熟度" in text
    assert "接近可交付" in text
    assert "方案备份" in text
    assert "沙盒预览" in text
    assert ".agent_state.json" not in text
    assert len(run_dirs) == 1
    workspace = run_dirs[0]
    assert (workspace / "docs" / "PRODUCT_SPEC.md").exists()
    assert (workspace / "docs" / "API_CONTRACT.md").exists()
    assert (workspace / "docs" / "DATABASE_SCHEMA.md").exists()
    assert (workspace / "docs" / "DELIVERY_CHECKLIST.md").exists()
    assert (workspace / "docs" / "SOLUTION_BACKUP.md").exists()
    assert (workspace / "solution_manifest.json").exists()
    assert (workspace / "backend" / "pom.xml").exists()
    assert (workspace / "backend" / "src" / "main" / "java" / "com" / "example" / "software" / "EmployeeController.java").exists()
    assert (workspace / "backend" / "src" / "main" / "java" / "com" / "example" / "software" / "ReferenceDataController.java").exists()
    assert (workspace / "backend" / "src" / "test" / "java" / "com" / "example" / "software" / "EmployeeControllerTest.java").exists()
    assert (workspace / "frontend" / "src" / "api.js").exists()
    assert (workspace / "frontend" / "src" / "App.vue").exists()
    assert (workspace / "preview" / "index.html").exists()
    assert (workspace / "security" / "SANDBOX.md").exists()
    assert (workspace / "sandbox_manifest.json").exists()
    readme = (workspace / "README.md").read_text(encoding="utf-8")
    employee_controller = (
        workspace / "backend" / "src" / "main" / "java" / "com" / "example" / "software" / "EmployeeController.java"
    ).read_text(encoding="utf-8")
    reference_controller = (
        workspace / "backend" / "src" / "main" / "java" / "com" / "example" / "software" / "ReferenceDataController.java"
    ).read_text(encoding="utf-8")
    employee_test = (
        workspace / "backend" / "src" / "test" / "java" / "com" / "example" / "software" / "EmployeeControllerTest.java"
    ).read_text(encoding="utf-8")
    api_js = (workspace / "frontend" / "src" / "api.js").read_text(encoding="utf-8")
    vue_app = (workspace / "frontend" / "src" / "App.vue").read_text(encoding="utf-8")
    solution_backup = (workspace / "docs" / "SOLUTION_BACKUP.md").read_text(encoding="utf-8")
    assert "Spring Boot + Vue Offline Prototype" in readme
    assert "POST /api/employees" in readme
    assert "PUT /api/employees/{id}" in readme
    assert "<built-in function id>" not in readme
    assert "GET /api/reference/departments" in readme
    assert "业务验收" in (workspace / "docs" / "PRODUCT_SPEC.md").read_text(encoding="utf-8")
    assert "audit_logs" in (workspace / "docs" / "DATABASE_SCHEMA.md").read_text(encoding="utf-8")
    assert "@PostMapping" in employee_controller
    assert "@PutMapping" in employee_controller
    assert "@DeleteMapping" in employee_controller
    assert "/payroll-rules" in reference_controller
    assert "employeeCrudFlowWorks" in employee_test
    assert "fetch" in api_js
    assert "新增员工" in vue_app
    assert "deleteEmployee" in vue_app
    assert "apiMode" in vue_app
    assert "personnel-management" in solution_backup

    preview = client.get(f"/runs/{workspace.name}/preview")
    assert preview.status_code == 200
    preview_text = preview.get_data(as_text=True)
    assert "人员管理系统" in preview_text
    assert "employeeForm" in preview_text
    assert "data-delete" in preview_text
    assert "connect-src 'none'" in preview.headers["Content-Security-Policy"]


def test_product_ui_can_improve_existing_run_as_new_iteration(tmp_path: Path) -> None:
    app = create_app(runs_root=tmp_path)
    client = app.test_client()
    _login(client)
    first = client.post(
        "/run",
        data={"goal": "Spring Boot + Vue 管理后台", "mode": "local_production", "events": "1"},
        follow_redirects=True,
    )
    assert first.status_code == 200
    source_workspace = next(path for path in tmp_path.iterdir() if path.is_dir())

    second = client.post(
        f"/runs/{source_workspace.name}/improve",
        data={"improvement_goal": "增加登录页面、角色权限、审批流、导入导出和操作审计", "events": "1"},
        follow_redirects=True,
    )
    text = second.get_data(as_text=True)
    run_dirs = sorted(path for path in tmp_path.iterdir() if path.is_dir())
    target_workspace = next(path for path in run_dirs if path.name != source_workspace.name)

    assert second.status_code == 200
    assert len(run_dirs) == 2
    assert "上一版" in text
    assert source_workspace.name in text
    assert "增加登录页面" in text
    assert ".agent_state.json" not in text
    assert (target_workspace / "README.md").exists()
    assert (target_workspace / "docs" / "PRODUCT_SPEC.md").exists()
    assert (target_workspace / "docs" / "AUTH_FLOW.md").exists()
    assert (target_workspace / "docs" / "WORKFLOW.md").exists()
    assert (target_workspace / "docs" / "IMPORT_EXPORT.md").exists()
    assert (target_workspace / "docs" / "AUDIT_LOG.md").exists()
    assert (target_workspace / "docs" / "SOLUTION_BACKUP.md").exists()
    assert (target_workspace / "solution_manifest.json").exists()
    assert (target_workspace / "docs" / "IMPROVEMENT_REQUEST.md").exists()
    assert (target_workspace / "backend" / "src" / "main" / "java" / "com" / "example" / "software" / "AuthController.java").exists()
    assert (target_workspace / "backend" / "src" / "main" / "java" / "com" / "example" / "software" / "WorkflowController.java").exists()
    assert (target_workspace / "backend" / "src" / "main" / "java" / "com" / "example" / "software" / "ImportExportController.java").exists()
    assert (target_workspace / "backend" / "src" / "main" / "java" / "com" / "example" / "software" / "AuditController.java").exists()
    assert (target_workspace / ".agent_state.json").exists()
    improvement_doc = (target_workspace / "docs" / "IMPROVEMENT_REQUEST.md").read_text(encoding="utf-8")
    assert source_workspace.name in improvement_doc
    assert "增加登录页面、角色权限、审批流、导入导出和操作审计" in improvement_doc
    auth_controller = (
        target_workspace / "backend" / "src" / "main" / "java" / "com" / "example" / "software" / "AuthController.java"
    ).read_text(encoding="utf-8")
    app_vue = (target_workspace / "frontend" / "src" / "App.vue").read_text(encoding="utf-8")
    api_js = (target_workspace / "frontend" / "src" / "api.js").read_text(encoding="utf-8")
    assert "/api/auth/login" not in auth_controller
    assert "@PostMapping(\"/login\")" in auth_controller
    assert "登录页面" in app_vue
    assert "loginUser" in app_vue
    assert "审批流" in app_vue
    assert "导入导出" in app_vue
    assert "操作审计" in app_vue
    assert "approveWorkflow" in api_js
    assert "importEmployees" in api_js
    assert "listAuditLogs" in api_js

    preview = client.get(f"/runs/{target_workspace.name}/preview")
    preview_text = preview.get_data(as_text=True)
    assert preview.status_code == 200
    assert "登录页面" in preview_text
    assert "登录进入系统" in preview_text
    assert "权限中心" in preview_text
    assert "审批流" in preview_text
    assert "导入导出" in preview_text
    assert "操作审计" in preview_text

    zip_resp = client.get(f"/runs/{target_workspace.name}/download")
    with zipfile.ZipFile(BytesIO(zip_resp.data)) as zf:
        names = set(zf.namelist())
    assert "docs/IMPROVEMENT_REQUEST.md" in names
    assert "docs/AUTH_FLOW.md" in names
    assert "docs/WORKFLOW.md" in names
    assert "docs/IMPORT_EXPORT.md" in names
    assert "docs/AUDIT_LOG.md" in names
    assert "docs/SOLUTION_BACKUP.md" in names
    assert "solution_manifest.json" in names
    assert "backend/src/main/java/com/example/software/AuthController.java" in names
    assert "backend/src/main/java/com/example/software/WorkflowController.java" in names
    assert "backend/src/main/java/com/example/software/ImportExportController.java" in names
    assert "backend/src/main/java/com/example/software/AuditController.java" in names
    assert ".agent_state.json" not in names


def test_product_ui_downloads_artifact_zip_without_agent_internals(tmp_path: Path) -> None:
    app = create_app(runs_root=tmp_path)
    client = app.test_client()
    _login(client)
    resp = client.post(
        "/run",
        data={"goal": "Spring Boot + Vue 管理后台", "mode": "local_production", "events": "1"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    workspace = next(path for path in tmp_path.iterdir() if path.is_dir())

    zip_resp = client.get(f"/runs/{workspace.name}/download")
    assert zip_resp.status_code == 200
    assert zip_resp.mimetype == "application/zip"

    with zipfile.ZipFile(BytesIO(zip_resp.data)) as zf:
        names = set(zf.namelist())
    assert "backend/pom.xml" in names
    assert "docs/PRODUCT_SPEC.md" in names
    assert "docs/API_CONTRACT.md" in names
    assert "docs/DATABASE_SCHEMA.md" in names
    assert "docs/SOLUTION_BACKUP.md" in names
    assert "solution_manifest.json" in names
    assert "backend/src/main/java/com/example/software/EmployeeController.java" in names
    assert "backend/src/main/java/com/example/software/ReferenceDataController.java" in names
    assert "backend/src/test/java/com/example/software/EmployeeControllerTest.java" in names
    assert "frontend/src/api.js" in names
    assert "frontend/src/App.vue" in names
    assert "preview/index.html" in names
    assert "security/SANDBOX.md" in names
    assert "sandbox_manifest.json" in names
    assert "README.md" in names
    assert ".agent_state.json" not in names
    assert ".agent_events.jsonl" not in names


def test_simple_frontend_catalog_preview_and_package_download(tmp_path: Path) -> None:
    app = create_app(runs_root=tmp_path)
    client = app.test_client()
    _login(client)

    home = client.get("/")
    assert home.status_code == 200
    home_text = home.get_data(as_text=True)
    assert "Software Studio" in home_text
    assert "Download ZIP" in home_text
    assert "Reusable solutions" in home_text

    catalog = client.get("/api/simple-solutions")
    assert catalog.status_code == 200
    catalog_json = catalog.get_json()
    assert catalog_json["schema"] == "simple_solution_catalog.v1"
    assert any(row["title"] == "Library Management System" for row in catalog_json["solutions"])

    prompt = "Build a clean library management system with books, readers, borrowing and returns."
    preview = client.post("/api/simple-preview", json={"prompt": prompt})
    assert preview.status_code == 200
    preview_json = preview.get_json()
    assert preview_json["preview_id"].startswith("preview_")
    assert "Books &amp; readers" in preview_json["html"]

    package = client.post(
        "/api/simple-package",
        json={
            "title": preview_json["title"],
            "prompt": prompt,
            "html": preview_json["html"],
        },
    )
    assert package.status_code == 200
    assert package.mimetype == "application/zip"
    with zipfile.ZipFile(BytesIO(package.data)) as zf:
        names = set(zf.namelist())
        readme = zf.read("README.md").decode("utf-8")
    assert "frontend/index.html" in names
    assert "docs/PRODUCT_SPEC.md" in names
    assert "docs/API_CONTRACT.yaml" in names
    assert "docs/DELIVERY_CHECKLIST.md" in names
    assert "solution_manifest.json" in names
    assert ".agent_state.json" not in names
    assert "Software Studio" in readme


def test_product_ui_billing_token_plan_payment_and_job_queue(tmp_path: Path) -> None:
    app = create_app(runs_root=tmp_path)
    client = app.test_client()
    _login(client)

    prompt = "做一个图书管理系统，包含图书、读者、借阅、归还和数据看板。"
    local_plan = client.post("/api/token-plan", json={"prompt": prompt, "model_source": "local"})
    assert local_plan.status_code == 200
    local_json = local_plan.get_json()
    assert local_json["schema"] == "product_token_plan.v1"
    assert local_json["billing_policy"]["billable"] is False
    assert local_json["admission"]["required_tokens"] == 0
    assert local_json["route_plan"]["context_budget"]["schema"] == "token_context_budget.v1"

    billing_before = client.get("/api/billing").get_json()
    order = client.post("/api/payment/orders", json={"amount_yuan": 19, "idempotency_key": "pay-once"})
    assert order.status_code == 200
    order_json = order.get_json()
    assert order_json["schema"] == "payment_order.v1"
    replay = client.post("/api/payment/orders", json={"amount_yuan": 19, "idempotency_key": "pay-once"})
    assert replay.status_code == 200
    assert replay.get_json()["replayed"] is True
    assert replay.get_json()["order"]["order_id"] == order_json["order"]["order_id"]
    status = client.get(f"/api/payment/orders/{order_json['order']['order_id']}")
    assert status.status_code == 200
    assert status.get_json()["order"]["status"] == "pending"
    confirm = client.post(
        f"/api/payment/orders/{order_json['order']['order_id']}/reconcile",
        json={"provider_status": "paid"},
    )
    assert confirm.status_code == 200
    assert confirm.get_json()["ok"] is True
    second_confirm = client.post(f"/api/payment/orders/{order_json['order']['order_id']}/confirm")
    assert second_confirm.status_code == 200
    assert second_confirm.get_json()["order"]["status"] == "paid"
    billing_after = client.get("/api/billing").get_json()
    assert billing_after["remaining_tokens"] > billing_before["remaining_tokens"]
    assert billing_after["purchased_tokens"] == billing_before["purchased_tokens"] + 19 * 2_000

    job = client.post(
        "/api/simple-jobs",
        json={"prompt": prompt, "model_source": "api", "provider": "deepseek"},
    )
    assert job.status_code == 202
    job_json = job.get_json()
    assert job_json["schema"] == "product_job_submission.v1"
    assert job_json["token_plan"]["billing_policy"]["billable"] is True
    queue = client.get("/api/simple-jobs")
    assert queue.status_code == 200
    assert queue.get_json()["schema"] == "product_job_queue.v1"
    assert queue.get_json()["jobs"]
    job_id = job_json["job"]["job_id"]

    finished = None
    for _ in range(20):
        status = client.get(f"/api/simple-jobs/{job_id}")
        assert status.status_code == 200
        body = status.get_json()
        if body["status"] == "finished":
            finished = body
            break
        time.sleep(0.05)

    assert finished is not None
    assert finished["owner_key"]
    assert finished["duration_ms"] >= 0
    assert finished["result"]["preview"]["preview_id"].startswith("preview_")
    billing_done = client.get("/api/billing").get_json()
    assert billing_done["used_tokens"] >= job_json["token_plan"]["estimate"]["estimated_total_tokens"]
    assert billing_done["token_events"]


def test_product_ui_rate_limits_preview_endpoint(tmp_path: Path) -> None:
    app = create_app(runs_root=tmp_path)
    client = app.test_client()
    _login(client)

    last = None
    for idx in range(41):
        last = client.post("/api/simple-preview", json={"prompt": f"做一个轻量页面 {idx}"})

    assert last is not None
    assert last.status_code == 429
    assert last.get_json()["error"] == "rate_limited"
    assert "Retry-After" in last.headers


def test_product_task_queue_retries_then_finishes() -> None:
    attempts = {"count": 0}

    def flaky(job: dict) -> dict:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary failure")
        return {"ok": True, "attempt": attempts["count"], "job_id": job["job_id"]}

    queue = ProductTaskQueue(flaky, max_attempts=3, retry_delay_s=0.01)
    job = queue.submit({"demo": True}, owner_key="u1")

    finished = None
    for _ in range(50):
        row = queue.get(job["job_id"])
        if row and row["status"] == "finished":
            finished = row
            break
        time.sleep(0.02)

    assert finished is not None
    assert finished["attempts"] == 2
    assert finished["errors"][0]["attempt"] == 1
    assert finished["result"]["ok"] is True
    assert queue.snapshot(owner_key="u1")["counts"]["finished"] == 1


def test_product_task_queue_dead_letters_after_retries() -> None:
    def broken(_: dict) -> dict:
        raise RuntimeError("always broken")

    queue = ProductTaskQueue(broken, max_attempts=2, retry_delay_s=0.01)
    job = queue.submit({"demo": True}, owner_key="u2")

    dead = None
    for _ in range(50):
        row = queue.get(job["job_id"])
        if row and row["status"] == "dead_letter":
            dead = row
            break
        time.sleep(0.02)

    snapshot = queue.snapshot(owner_key="u2")
    assert dead is not None
    assert dead["dead_letter"] is True
    assert dead["attempts"] == 2
    assert len(dead["errors"]) == 2
    assert snapshot["counts"]["dead_letter"] == 1
    assert snapshot["dead_letters"][0]["job_id"] == job["job_id"]


def test_product_ui_audit_and_ops_snapshot(tmp_path: Path) -> None:
    app = create_app(runs_root=tmp_path)
    client = app.test_client()
    _login(client)

    order = client.post("/api/payment/orders", json={"amount_yuan": 19, "idempotency_key": "audit-pay"})
    assert order.status_code == 200
    order_id = order.get_json()["order"]["order_id"]
    confirm = client.post(f"/api/payment/orders/{order_id}/confirm")
    assert confirm.status_code == 200

    job = client.post("/api/simple-jobs", json={"prompt": "做一个审计演示页面", "model_source": "local"})
    assert job.status_code == 202

    audit = client.get("/api/audit/events?limit=20")
    ops = client.get("/api/ops/snapshot")

    assert audit.status_code == 200
    events = audit.get_json()["events"]
    types = {event["event_type"] for event in events}
    assert {"payment_order_created", "payment_order_confirmed", "simple_job_submitted"} <= types
    assert ops.status_code == 200
    ops_json = ops.get_json()
    assert ops_json["schema"] == "product_ops_snapshot.v1"
    assert ops_json["queue"]["schema"] == "product_job_queue.v1"
    assert ops_json["rate_limiter"]["schema"] == "api_rate_limiter_snapshot.v1"
    assert ops_json["audit_tail"]


def test_product_ui_groq_llm_requires_groq_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    app = create_app(runs_root=tmp_path)
    client = app.test_client()
    _login(client)

    resp = client.post(
        "/run",
        data={
            "goal": "写一个最小接口",
            "mode": "llm",
            "provider": "groq",
            "model": "openai/gpt-oss-20b",
        },
        follow_redirects=True,
    )
    text = resp.get_data(as_text=True)

    assert resp.status_code == 400
    assert "GROQ_API_KEY is required" in text


def test_product_ui_deepseek_llm_requires_deepseek_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    app = create_app(runs_root=tmp_path)
    client = app.test_client()
    _login(client)

    resp = client.post(
        "/run",
        data={
            "goal": "写一个最小接口",
            "mode": "llm",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
        },
        follow_redirects=True,
    )
    text = resp.get_data(as_text=True)

    assert resp.status_code == 400
    assert "DEEPSEEK_API_KEY is required" in text


def test_product_ui_healthz(tmp_path: Path) -> None:
    app = create_app(runs_root=tmp_path)
    client = app.test_client()

    resp = client.get("/healthz")

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
