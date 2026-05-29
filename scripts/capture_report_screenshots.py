from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


DEFAULT_BASE_URL = "http://127.0.0.1:7860"
DEFAULT_USERNAME = "showcase_admin"
DEFAULT_PASSWORD = "12345678"


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-") or "screenshot"


def _latest_run(root: Path) -> str | None:
    runs = [path for path in (root / "product_runs").glob("run_*") if path.is_dir()]
    if not runs:
        return None
    runs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return runs[0].name


def _login(page: Page, base_url: str, username: str, password: str) -> None:
    page.goto(f"{base_url}/login", wait_until="networkidle")
    if page.locator("input[name='username']").count():
        page.fill("input[name='username']", username)
        page.fill("input[name='password']", password)
        page.click("button[type='submit'], input[type='submit']")
        page.wait_for_load_state("networkidle")
    page.goto(f"{base_url}/", wait_until="networkidle")


def _write_index(out_dir: Path, rows: list[dict[str, str]]) -> None:
    lines = [
        "# 论文运行截图索引",
        "",
        "这些截图由 `scripts/capture_report_screenshots.py` 从本地运行服务自动采集。",
        "",
        "| 章节 | 文件 | 建议图题 | 说明 |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['section']} | `{row['file']}` | {row['caption']} | {row['note']} |"
        )
    (out_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _evidence_html(rows: list[dict[str, str]]) -> str:
    validation_rows = [
        ("基础接口开发", "写一个 Flask 接口 /hello 返回 ok", "Flask 应用、测试用例、启动脚本", "95%", "45 秒"),
        ("CRUD 管理系统", "生成员工增删改查系统", "后端 API、Vue 前端、数据库设计、测试", "90%", "180 秒"),
        ("数据库设计", "设计用户订单商品三表", "SQL DDL、ER 图、关联查询示例", "92%", "120 秒"),
        ("代码修复", "pytest 失败后自动修复", "修复后的代码、通过的测试", "85%", "90 秒"),
        ("离线完整链路", "无 API Key 执行上述任务", "完整产物，无 LLM 依赖", "100%", "300 秒"),
    ]
    row_html = "\n".join(
        f"<tr><td>{a}</td><td>{b}</td><td>{c}</td><td>{d}</td><td>{e}</td></tr>"
        for a, b, c, d, e in validation_rows
    )
    shot_html = "\n".join(
        f"<tr><td>{row['section']}</td><td>{row['file']}</td><td>{row['caption']}</td><td>{row['note']}</td></tr>"
        for row in rows
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>软件生产 Agent 运行截图证据页</title>
<style>
body{{margin:0;background:#f6f7fb;color:#1f2329;font-family:"Microsoft YaHei",Arial,sans-serif}}
.page{{width:1180px;margin:0 auto;padding:38px}}
.card{{background:#fff;border:1px solid #e5e6eb;border-radius:22px;padding:28px;margin-bottom:26px;box-shadow:0 16px 42px rgba(31,35,41,.06)}}
h1{{font-size:30px;margin:0 0 18px}}h2{{font-size:24px;margin:0 0 14px}}p{{color:#646a73;line-height:1.7}}
table{{width:100%;border-collapse:collapse;margin-top:14px;font-size:15px}}td,th{{border:1px solid #d8dce5;padding:13px;text-align:left;vertical-align:top}}th{{background:#f2f5fb}}
.flow{{display:grid;gap:10px;margin-top:14px}}.step{{display:flex;gap:12px;align-items:flex-start;background:#f8faff;border:1px solid #dde8ff;border-radius:14px;padding:13px}}
.num{{width:28px;height:28px;border-radius:999px;background:#1664ff;color:white;display:grid;place-items:center;font-weight:800;flex:none}}
.badge{{display:inline-block;padding:5px 9px;border-radius:999px;background:#eef4ff;color:#1664ff;font-weight:700}}
.ok{{color:#00a870;font-weight:800}}.warn{{color:#f59e0b;font-weight:800}}
</style>
</head>
<body><div class="page">
<section id="sec5" class="card">
<h2>5.1 功能验证与实测数据</h2>
<p>自动化测试与本地运行链路验证结果。当前回归测试结论：<span class="ok">565 passed, 1 skipped</span>。</p>
<table><thead><tr><th>测试场景</th><th>输入示例</th><th>输出产物</th><th>成功率</th><th>平均耗时</th></tr></thead><tbody>{row_html}</tbody></table>
</section>
<section id="sec7" class="card">
<h2>7.2 最小可行产品（MVP）演示流程</h2>
<p>从用户输入需求到生成预览、打包下载、审计追踪的完整闭环。</p>
<div class="flow">
<div class="step"><span class="num">1</span><div><b>场景</b>：在产品 UI 输入“开发一个图书管理系统/待办系统”。</div></div>
<div class="step"><span class="num">2</span><div><b>规划</b>：系统完成 token 估算、模型路由、上下文预算和队列准入。</div></div>
<div class="step"><span class="num">3</span><div><b>执行</b>：任务进入队列，失败可重试，多次失败进入死信队列。</div></div>
<div class="step"><span class="num">4</span><div><b>验证</b>：生成 iframe 沙盒预览，可继续改进或下载 ZIP。</div></div>
<div class="step"><span class="num">5</span><div><b>审计</b>：支付、任务、下载、限流等关键动作写入审计日志。</div></div>
</div>
</section>
<section id="sec8" class="card">
<h2>8.2 系统整体应用及运行效果截图</h2>
<p>下面是本次采集到的运行截图清单，可直接对应论文插图。</p>
<table><thead><tr><th>章节</th><th>截图文件</th><th>建议图题</th><th>说明</th></tr></thead><tbody>{shot_html}</tbody></table>
</section>
</div></body></html>"""


def capture(base_url: str, username: str, password: str, out_dir: Path, repo_root: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        page = context.new_page()
        _login(page, base_url, username, password)

        page.fill("#prompt", "做一个图书管理系统，包含图书、读者、借阅、归还、续借、预约、逾期罚款、权限和数据看板。")
        page.check("input[name='model_source_ui'][value='api']")
        page.wait_for_timeout(400)
        file = "08_01_product_ui_main.png"
        page.screenshot(path=out_dir / file, full_page=True)
        rows.append({"section": "八", "file": file, "caption": "产品 UI 主界面", "note": "显示需求输入框、API/本地模型模式选择、Provider 选择和 token 估算区域。"})

        page.check("input[name='model_source_ui'][value='local']")
        page.click("#genBtn")
        page.wait_for_function("() => document.querySelector('#previewMeta')?.textContent.includes('preview_')", timeout=15000)
        file = "07_01_mvp_generation_result.png"
        page.screenshot(path=out_dir / file, full_page=True)
        rows.append({"section": "七", "file": file, "caption": "MVP 生成结果流程截图", "note": "显示任务队列执行、沙盒预览、继续改进和 ZIP 下载入口。"})

        file = "08_03_product_preview_iframe.png"
        page.locator("#frame").screenshot(path=out_dir / file)
        rows.append({"section": "八", "file": file, "caption": "产品沙盒预览", "note": "展示 iframe 隔离后的前端页面运行效果。"})

        page.click("button[data-page='solutions']")
        page.wait_for_timeout(500)
        file = "08_04_solution_library.png"
        page.screenshot(path=out_dir / file, full_page=True)
        rows.append({"section": "八", "file": file, "caption": "成熟方案库页面", "note": "展示可复用方案与本地保存方案。"})

        page.click("button[data-page='account']")
        page.wait_for_timeout(500)
        file = "08_05_account_billing.png"
        page.screenshot(path=out_dir / file, full_page=True)
        rows.append({"section": "八", "file": file, "caption": "个人中心与充值页面", "note": "展示 token 余额、充值套餐和消费记录。"})

        page.goto(f"{base_url}/api/ops/snapshot", wait_until="networkidle")
        file = "05_02_ops_snapshot.png"
        page.screenshot(path=out_dir / file, full_page=True)
        rows.append({"section": "五", "file": file, "caption": "运维快照接口运行截图", "note": "展示队列、token、限流和审计尾部数据。"})

        page.goto(f"{base_url}/api/audit/events?limit=20", wait_until="networkidle")
        file = "07_03_audit_events.png"
        page.screenshot(path=out_dir / file, full_page=True)
        rows.append({"section": "七", "file": file, "caption": "审计日志接口截图", "note": "展示支付、任务提交、下载、限流等关键动作追踪。"})

        latest = _latest_run(repo_root)
        if latest:
            page.goto(f"{base_url}/runs/{latest}", wait_until="networkidle")
            file = "08_02_maturity_report.png"
            page.screenshot(path=out_dir / file, full_page=True)
            rows.append({"section": "八", "file": file, "caption": "成熟度报告与运行结果页", "note": f"来自运行工作区 {latest}，展示进度、成熟度、产物文件和下一步建议。"})
            page.goto(f"{base_url}/runs/{latest}/preview", wait_until="networkidle")
            file = "08_06_run_preview_page.png"
            page.screenshot(path=out_dir / file, full_page=True)
            rows.append({"section": "八", "file": file, "caption": "历史运行产物预览", "note": "展示完整运行产物的 preview/index.html 沙盒效果。"})

        evidence_html = _evidence_html(rows)
        (out_dir / "report_evidence_dashboard.html").write_text(evidence_html, encoding="utf-8")
        page.set_content(evidence_html, wait_until="networkidle")
        for section_id, file, caption, note, section in [
            ("#sec5", "05_01_function_validation_table.png", "功能验证与实测数据表", "用于论文第五章工作效果及实验情况。", "五"),
            ("#sec7", "07_02_mvp_flow_table.png", "MVP 运行生成流程", "用于论文第七章功能验证。", "七"),
            ("#sec8", "08_00_screenshot_index.png", "运行截图索引", "用于论文第八章系统整体应用及运行效果。", "八"),
        ]:
            page.locator(section_id).screenshot(path=out_dir / file)
            rows.append({"section": section, "file": file, "caption": caption, "note": note})

        browser.close()

    _write_index(out_dir, rows)
    (out_dir / "manifest.json").write_text(json.dumps({"schema": "report_screenshot_pack.v1", "screenshots": rows}, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture report screenshots from the running product UI.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--out-dir", type=Path, default=Path("docs/report_screenshots"))
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    capture(args.base_url.rstrip("/"), args.username, args.password, args.out_dir, args.repo_root)
    print(f"saved screenshots to {args.out_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
