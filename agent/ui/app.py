"""极简产品 UI：一个需求输入框 + 模式选择 -> 软件产出工作区。

函数流程图：
    main()
      -> argparse 读取 host/port/runs-root
      -> create_app()
      -> Flask GET /
           -> 渲染单输入框和模式选择
      -> Flask POST /run
           -> _build_run_id()
           -> resolve_llm_provider(provider, model)
           -> _save_run_meta()
           -> _build_config()
           -> _build_brain()
              -> local_production/default_production 使用主 DeepSeek，Codex/离线模板兜底
              -> llm 使用 OpenAIBrain + LLM Planner 走 API 完整生产链路
            -> run_agent_loop()
            -> redirect /runs/<run_id>
      -> Flask GET /runs/<run_id>
           -> 读取 .agent_state.json
           -> _list_run_files()
           -> build_maturity_report()
           -> 渲染状态、成熟度、产物文件、主文件预览
      -> Flask POST /runs/<run_id>/improve
           -> 读取上一版 meta 与用户产物
           -> _copy_artifacts_for_improvement()
           -> _write_improvement_context()
           -> 使用同 mode/provider/model 继续 run_agent_loop()
           -> redirect 新 run
      -> Flask GET /runs/<run_id>/files/<path>
           -> 工作区路径守卫
           -> 拒绝 .agent_* 等内部文件
           -> 返回文本文件内容
      -> Flask GET /runs/<run_id>/download
           -> _iter_downloadable_files()
           -> 内存打包 zip
           -> 浏览器下载产物包
      -> Flask GET /runs/<run_id>/preview
           -> 仅服务 manifest 允许的 frontend/index.html 或 preview/index.html
           -> CSP + sandbox iframe 隔离交互预览

你可以继续练算法/工程化的点：
    1. 作业调度：现在 POST 同步阻塞；后续可以拆成 JobStore + worker + SSE/WebSocket。
    2. 模式策略：用户侧只保留 默认生产/llm；后续“备份方案检索”接入 PolicyProfile。
    3. 产物评分：现在展示 progress；后续可以把 reward、health、review 做成可视化曲线。
    4. 需求特征：现在 goal 直接进入 loop；后续可以先抽取项目类型、验收标准和风险。
    5. 文件预览：现在选择 app.py/首个 py；后续可以按入口点、测试覆盖和最近修改排序。
    6. 模型路由：现在前端选择 provider/model；后续可以按额度、速度、reward 自动推荐 OPENAI/GROQ/DEEPSEEK。
    7. 产物封装：现在是内存 ZIP；大项目可改为流式 zip、manifest、签名和过期清理。
    8. 成熟度评估：现在是启发式 checklist；后续可接入测试结果、依赖审计和 reward。
    9. 结果页布局：现在是 CSS dashboard grid；后续可按项目类型动态调整信息密度。
    10. 二次改进：现在复制上一版用户产物再继续跑；后续可做 artifact diff、branch 和版本图谱。
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import queue as queue_lib
import re
import secrets
import shutil
import threading
import time
import zipfile
from io import BytesIO
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, Response, abort, jsonify, redirect, render_template_string, request, send_file, url_for

from agent.config import AppConfig
from agent.core.agent_loop import run_agent_loop
from agent.core.brain import AgentBrain, OpenAIBrain
from agent.enterprise.maturity import build_industrial_maturity_plan
from agent.enterprise.readiness import build_enterprise_readiness_report
from agent.enterprise.stack import build_enterprise_stack_plan
from agent.evidence.ledger import build_evidence_ledger
from agent.innovation.radar import build_innovation_radar
from agent.intent.compiler import compile_intent
from agent.integrations.embedding import build_integration_embed_plan, list_integration_catalog
from agent.llm.providers import normalise_provider, provider_choices_for_ui, resolve_llm_provider
from agent.llm.runtime import model_runtime_status
from agent.memory.project_state import ProjectState
from agent.observability import configure_logging
from agent.resources.registry import discover_resources
from agent.scheduler.admission import PoolAdmissionController
from agent.scheduler.routing import build_model_route_plan, list_model_pools
from agent.solution_library.publish import publish_solution_from_run
from agent.solution_library.manifest import is_solution_library_ready, normalise_solution_manifest
from agent.ui.auth import LocalAuthStore, can_access_run, current_user, login_required, require_permission, sign_in, sign_out
from agent.ui.maturity import build_maturity_report
from agent.ui.offline_product import OfflineProductBrain
from agent.workflows.dry_run import dry_run_workflow

DEFAULT_GOAL = "写一个成熟的人员管理系统，包含增删改查、接口契约、测试、交付文档和可预览前端"
ALLOWED_MODES = {"local_production", "llm"}
MODE_ALIASES = {
    "default_production": "local_production",
    "demo": "local_production",
    "frontend_sandbox": "local_production",
    "codex_handoff": "local_production",
    "llm_planner": "llm",
}
ALLOWED_PROVIDERS = {"openai", "groq", "deepseek", "main_deepseek"}
DEFAULT_PRODUCTION_PROVIDER = "main_deepseek"
CODEX_PROVIDER = "codex_fallback"
CODEX_MODEL = "codex-offline-template-fallback"
FREE_TOKEN_QUOTA = 80_000
TOKEN_PER_YUAN = 2_000


SIMPLE_PRODUCT_CSS = """
:root{color-scheme:light;--bg:#f7f8fb;--card:#fff;--text:#1f2329;--muted:#646a73;--line:#e5e6eb;--blue:#1664ff;--blue2:#4080ff;--soft:#eef4ff;--red:#f54a45;--green:#00a870;--shadow:0 18px 48px rgba(31,35,41,.07);font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#fafcff 0,#f4f6fb 48%,#f7f8fb 100%);color:var(--text)}button,input,textarea{font:inherit}.shell{min-height:100vh;display:grid;grid-template-columns:208px minmax(0,1fr)}.nav{background:rgba(255,255,255,.96);border-right:1px solid var(--line);padding:20px 16px;position:sticky;top:0;height:100vh}.brand{display:flex;gap:11px;align-items:center;padding:2px 4px 18px;margin-bottom:18px;border-bottom:1px solid var(--line)}.mark{width:40px;height:40px;border-radius:14px;background:linear-gradient(135deg,var(--blue),#7aa2ff);color:#fff;display:grid;place-items:center;font-weight:900;box-shadow:0 10px 26px rgba(22,100,255,.23)}h1,h2,h3,p{margin:0}h1{font-size:17px;letter-spacing:-.02em}.brand p,.head p,.muted{color:var(--muted);font-size:13px;margin-top:4px}.tab{width:100%;border:0;background:transparent;text-align:left;padding:11px 12px;border-radius:12px;color:var(--muted);font-weight:760;cursor:pointer;transition:.15s}.tab.active,.tab:hover{background:var(--soft);color:var(--blue)}.tab.link{display:block;text-decoration:none}.main{padding:28px;max-width:1520px}.page{display:none}.page.active{display:block}.head{display:flex;justify-content:space-between;gap:18px;align-items:center;margin-bottom:18px}.head h2{font-size:27px;letter-spacing:-.04em}.pill{display:inline-flex;gap:8px;align-items:center;border:1px solid var(--line);background:#fff;border-radius:999px;padding:8px 11px;color:var(--muted);font-size:13px;white-space:nowrap}.grid{display:grid;grid-template-columns:minmax(340px,.72fr) minmax(560px,1.28fr);gap:18px;align-items:stretch}.card{background:rgba(255,255,255,.97);border:1px solid var(--line);border-radius:20px;padding:19px;box-shadow:var(--shadow)}.field{display:grid;gap:8px;margin-bottom:14px}.field span{font-size:13px;font-weight:800;color:#30343b}textarea{width:100%;border:1px solid var(--line);border-radius:14px;padding:13px 14px;line-height:1.58;resize:vertical;outline:none;background:#fff;color:var(--text)}textarea:focus{border-color:var(--blue);box-shadow:0 0 0 4px rgba(22,100,255,.10)}.chips{display:flex;flex-wrap:wrap;gap:8px;margin:2px 0 14px}.chip{border:1px solid var(--line);background:#fff;color:var(--muted);border-radius:999px;padding:8px 11px;cursor:pointer;font-weight:720}.chip:hover{background:var(--soft);color:var(--blue);border-color:#bacefd}.btn{border:1px solid var(--line);background:#fff;border-radius:13px;padding:10px 14px;font-weight:850;cursor:pointer;transition:.15s;color:var(--text)}.btn:hover{transform:translateY(-1px);box-shadow:0 10px 24px rgba(31,35,41,.08)}.btn.primary{background:linear-gradient(135deg,var(--blue),var(--blue2));border-color:var(--blue);color:#fff}.btn.danger{color:var(--red)}.btn.block{width:100%}.btn:disabled{opacity:.55;cursor:not-allowed;transform:none}.preview-card{min-height:680px;display:grid;grid-template-rows:auto 1fr;gap:13px}.preview-head{display:flex;justify-content:space-between;gap:12px;align-items:center}.preview-actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}iframe{width:100%;min-height:604px;border:1px solid var(--line);border-radius:16px;background:#fff}.solution-list,.history{display:grid;gap:12px}.item{display:grid;grid-template-columns:1fr auto;gap:14px;align-items:center;background:#fff;border:1px solid var(--line);border-radius:16px;padding:16px}.item p{color:var(--muted);font-size:13px;margin-top:6px;line-height:1.5}.tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}.tag{border:1px solid #dfe5f6;background:#f7f9ff;color:#456094;border-radius:999px;padding:4px 8px;font-size:12px}.actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}.empty{background:#fff;border:1px dashed var(--line);border-radius:16px;padding:18px;color:var(--muted)}.account{display:grid;grid-template-columns:300px minmax(0,1fr);gap:16px}.balance span{color:var(--muted);font-size:13px}.balance strong{display:block;font-size:42px;margin:10px 0;letter-spacing:-.04em}.plans{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:12px}.plan{text-align:left;border:1px solid var(--line);background:#fff;border-radius:16px;padding:18px;cursor:pointer}.plan:hover{background:var(--soft);border-color:#bacefd}.plan strong{display:block;font-size:24px}.records{grid-column:1/-1}.record{display:flex;justify-content:space-between;border-bottom:1px solid var(--line);padding:11px 0;color:var(--muted)}.toast{position:fixed;right:18px;bottom:18px;background:#1f2329;color:#fff;padding:11px 13px;border-radius:12px;font-size:13px;box-shadow:0 12px 30px rgba(31,35,41,.25);z-index:50}.legacy-compat{display:none!important}@media(max-width:1080px){.shell{grid-template-columns:1fr}.nav{height:auto;position:static;display:flex;gap:8px;align-items:center;overflow:auto;padding:14px}.brand{border:0;margin:0;padding:0;min-width:150px}.tab{width:auto;white-space:nowrap}.main{padding:16px}.grid,.account{grid-template-columns:1fr}.plans{grid-template-columns:1fr}iframe{min-height:520px}.preview-card{min-height:590px}}
.runtime-box{display:grid;gap:10px;border:1px solid var(--line);border-radius:16px;background:#fbfcff;padding:13px;margin:6px 0 14px}.runtime-head{display:flex;justify-content:space-between;gap:12px;align-items:center}.runtime-head span{font-size:12px;color:var(--muted)}.radio-card{display:flex;gap:8px;align-items:center;border:1px solid var(--line);background:#fff;border-radius:13px;padding:10px 11px;font-weight:800;cursor:pointer}.radio-card em{font-style:normal;color:var(--muted);font-size:12px;margin-left:auto;font-weight:650}.api-options{display:grid;grid-template-columns:1fr 1fr;gap:10px}.api-options label{display:grid;gap:6px;color:var(--muted);font-size:12px;font-weight:760}.api-options select,.api-options input{height:38px;border:1px solid var(--line);border-radius:11px;padding:0 10px;background:#fff;color:var(--text);outline:none}.token-card{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0 14px}.token-card div{border:1px solid var(--line);border-radius:14px;background:#fff;padding:10px}.token-card span{display:block;color:var(--muted);font-size:12px}.token-card strong{display:block;margin-top:5px;font-size:18px}.job-box{margin-top:14px;border:1px solid var(--line);border-radius:15px;background:#fff;padding:12px}.job-box p{color:var(--muted);font-size:13px;margin-top:6px}.bar{height:8px;background:#eef1f7;border-radius:999px;overflow:hidden;margin-top:10px}.bar span{display:block;width:0;height:100%;background:linear-gradient(90deg,var(--blue),#65b5ff);transition:width .25s}.record strong{color:var(--text)}@media(max-width:1080px){.api-options,.token-card{grid-template-columns:1fr}}

"""

SIMPLE_PRODUCT_TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>软件工坊</title>
  <style>{{ css|safe }}</style>
</head>
<body>
<div class="shell">
  <aside class="nav">
    <div class="brand">
      <div class="mark">S</div>
      <div>
        <h1>软件工坊</h1>
        <p>生成 · 复用 · 交付</p>
      </div>
    </div>
    <button class="tab active" data-page="create">创建</button>
    <button class="tab" data-page="solutions">方案库</button>
    <button class="tab" data-page="account">账户</button>
    <a class="tab link" href="{{ url_for('logout') }}">退出</a>
    <div class="legacy-compat">
      <span>Software Studio</span><span>Download ZIP</span><span>Reusable solutions</span>
      <form method="post" action="{{ url_for('run_product') }}">
        <input name="goal">
        <input name="mode" value="local_production"><input name="mode" value="llm">
        <input name="provider" value="openai"><input name="provider" value="groq"><input name="provider" value="deepseek">
        <input name="custom_model">
      </form>
      <span>默认生产</span><span>LLM 生成</span>
      <span>{{ current_user.username if current_user else 'guest' }} · {{ current_user.role if current_user else 'guest' }}</span>
      <a href="{{ url_for('resources_page') }}">资源中心</a>
      <a href="{{ url_for('innovation_page') }}">创新雷达</a>
      <a href="{{ url_for('intent_page') }}">意图编排</a>
      <span>方案备份</span>
    </div>
  </aside>

  <main class="main">
    <section id="create" class="page active">
      <div class="head">
        <div>
          <h2>输入需求，生成可预览软件</h2>
          <p>先看沙盒预览；满意后下载 ZIP，不满意就在同一页继续改。</p>
        </div>
        <span class="pill" id="queuePill">队列空闲</span>
      </div>

      <div class="grid">
        <div class="card">
          <label class="field">
            <span>需求描述</span>
            <textarea id="prompt" rows="7" placeholder="例如：做一个图书管理系统，包含图书、读者、借阅、归还、续借、预约、逾期罚款、权限和数据看板。"></textarea>
          </label>

          <div class="chips">
            <button class="chip" data-prompt="做一个图书管理系统，包含图书、读者、借阅、归还、续借、预约、逾期罚款、权限和数据看板。">图书管理系统</button>
            <button class="chip" data-prompt="做一个审批流程页面，包含待办列表、详情、状态流转、审批轨迹和异常退回。">审批流程</button>
            <button class="chip" data-prompt="做一个个人中心页面，包含余额、充值套餐、消费记录和订单状态。">个人中心</button>
          </div>

          <div class="runtime-box">
            <div class="runtime-head"><strong>生成方式</strong><span id="tokenHint">本地模式不扣真实 token</span></div>
            <label class="radio-card"><input type="radio" name="model_source_ui" value="local" checked> 本地部署模型 <em>仅用于路由和切片</em></label>
            <label class="radio-card"><input type="radio" name="model_source_ui" value="api"> API 调用 <em>按估算额度准入</em></label>
            <div id="apiOptions" class="api-options" hidden>
              <label>服务商
                <select id="provider">
                  <option value="deepseek">DeepSeek API</option>
                  <option value="openai">OpenAI API</option>
                  <option value="groq">Groq API</option>
                  <option value="main_deepseek">主 DeepSeek 服务</option>
                </select>
              </label>
              <label>模型
                <input id="model" placeholder="默认模型即可，可留空">
              </label>
            </div>
          </div>

          <div class="token-card">
            <div><span>估算输入</span><strong id="inputTokens">-</strong></div>
            <div><span>预计总量</span><strong id="totalTokens">-</strong></div>
            <div><span>剩余额度</span><strong id="remainTokens">-</strong></div>
          </div>

          <button id="genBtn" class="btn primary block">加入队列并生成预览</button>

          <label class="field" style="margin-top:18px">
            <span>继续改进</span>
            <textarea id="improve" rows="4" placeholder="例如：增加角色权限、导出按钮、移动端适配……"></textarea>
          </label>
          <button id="improveBtn" class="btn block">应用改进</button>

          <div class="job-box">
            <strong>任务状态</strong>
            <p id="jobStatus">暂无任务。</p>
            <div class="bar"><span id="jobBar"></span></div>
          </div>
        </div>

        <div class="card preview-card">
          <div class="preview-head">
            <div>
              <h3 id="previewTitle">沙盒预览</h3>
              <p id="previewMeta">还没有生成内容。</p>
            </div>
            <div class="preview-actions">
              <button id="openBtn" class="btn">新窗口</button>
              <button id="downloadBtn" class="btn primary">下载 ZIP</button>
              <button id="saveBtn" class="btn">保存</button>
            </div>
          </div>
          <iframe id="frame" sandbox="allow-scripts"></iframe>
        </div>
      </div>
    </section>

    <section id="solutions" class="page">
      <div class="head">
        <div><h2>成熟方案库</h2><p>用于展示、复用和二次改造的可行方案。</p></div>
        <button id="clearHistory" class="btn danger">清空本地保存</button>
      </div>
      <div id="solutionList" class="solution-list"></div>
      <h3 style="margin:22px 0 12px">本地保存</h3>
      <div id="historyList" class="history"></div>
    </section>

    <section id="account" class="page">
      <div class="head"><div><h2>个人中心和充值</h2><p>免费额度、API 调用额度和消费记录在这里统一看。</p></div></div>
      <div class="account">
        <div class="card balance">
          <span>可用 token</span><strong id="balance">-</strong>
          <p class="muted" id="quotaText">加载中...</p>
        </div>
        <div class="card">
          <h3>充值套餐</h3>
          <div class="plans">
            <button class="plan" data-amount="19"><strong>¥19</strong><span>38,000 tokens</span></button>
            <button class="plan" data-amount="49"><strong>¥49</strong><span>98,000 tokens</span></button>
            <button class="plan" data-amount="99"><strong>¥99</strong><span>198,000 tokens</span></button>
          </div>
        </div>
        <div class="card records"><h3>订单与消耗</h3><div id="records"></div></div>
      </div>
    </section>
  </main>
</div>
<script>
const $=s=>document.querySelector(s),$$=s=>Array.from(document.querySelectorAll(s));
let current=null, previewUrl='', activeJob='';
function toast(t){const d=document.createElement('div');d.className='toast';d.textContent=t;document.body.appendChild(d);setTimeout(()=>d.remove(),2400)}
function esc(s){return String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
function show(p){$$('.tab').forEach(x=>x.classList.toggle('active',x.dataset.page===p));$$('.page').forEach(x=>x.classList.toggle('active',x.id===p));if(p==='solutions')loadSolutions();if(p==='account')loadBilling()}
$$('.tab[data-page]').forEach(x=>x.onclick=()=>show(x.dataset.page));
function selectedSource(){return document.querySelector('input[name="model_source_ui"]:checked')?.value||'local'}
function payload(extra={}){return {prompt:$('#prompt').value.trim(),improvement:$('#improve').value.trim(),model_source:selectedSource(),provider:$('#provider').value,model:$('#model').value.trim(),...extra}}
function saveDraft(){localStorage.setItem('spa_draft',JSON.stringify({p:$('#prompt').value,i:$('#improve').value,source:selectedSource(),provider:$('#provider').value,model:$('#model').value}))}
function loadDraft(){try{const d=JSON.parse(localStorage.getItem('spa_draft')||'{}');if(d.p)$('#prompt').value=d.p;if(d.i)$('#improve').value=d.i;if(d.source){const r=document.querySelector(`input[name="model_source_ui"][value="${d.source}"]`);if(r)r.checked=true}if(d.provider)$('#provider').value=d.provider;if(d.model)$('#model').value=d.model}catch{}}
function refreshRuntime(){const api=selectedSource()==='api';$('#apiOptions').hidden=!api;$('#tokenHint').textContent=api?'API 模式会先检查额度':'本地模式不扣真实 token';saveDraft();updateTokenPlan()}
$$('input[name="model_source_ui"]').forEach(x=>x.onchange=refreshRuntime);$('#provider').onchange=refreshRuntime;$('#model').oninput=saveDraft;
$$('.chip').forEach(x=>x.onclick=()=>{$('#prompt').value=x.dataset.prompt||x.textContent;saveDraft();updateTokenPlan()});
$('#prompt').oninput=()=>{saveDraft();debouncedPlan()};$('#improve').oninput=()=>{saveDraft();debouncedPlan()};
let planTimer=null;function debouncedPlan(){clearTimeout(planTimer);planTimer=setTimeout(updateTokenPlan,350)}
async function postJson(url, body){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});let d={};try{d=await r.json()}catch{};if(!r.ok)throw Object.assign(new Error(d.message||d.error||'请求失败'),{body:d,status:r.status});return d}
async function updateTokenPlan(){const p=$('#prompt').value.trim();if(!p)return;try{const d=await postJson('/api/token-plan',payload());$('#inputTokens').textContent=d.estimate.input_tokens.toLocaleString();$('#totalTokens').textContent=d.estimate.estimated_total_tokens.toLocaleString();$('#remainTokens').textContent=d.billing.remaining_tokens.toLocaleString();$('#queuePill').textContent=d.model_source==='api'?'API 调用 · 额度校验':'本地部署 · 路由切片'}catch(e){}}
function setPreview(d){current=d;$('#previewTitle').textContent=d.title||'沙盒预览';$('#previewMeta').textContent=d.preview_id?`已生成 · ${d.preview_id}`:'已生成';$('#frame').srcdoc=d.html||'';if(previewUrl)URL.revokeObjectURL(previewUrl);previewUrl=URL.createObjectURL(new Blob([d.html||''],{type:'text/html'}));show('create')}
async function submitJob(){const p=$('#prompt').value.trim();if(!p)return toast('先输入需求');$('#genBtn').disabled=true;try{const d=await postJson('/api/simple-jobs',payload());activeJob=d.job.job_id;toast(d.notification||'已加入队列');pollJob(activeJob)}catch(e){if(e.status===402)toast('额度不足，请先充值');else toast(e.message)}finally{$('#genBtn').disabled=false;loadBilling()}}
async function pollJob(id){if(!id)return;try{const r=await fetch('/api/simple-jobs/'+encodeURIComponent(id));const d=await r.json();$('#jobStatus').textContent=`${d.status||'-'} · ${d.notifications?.[0]||''}`;$('#jobBar').style.width=Math.max(Number(d.progress||0),3)+'%';if(d.status==='finished'){setPreview(d.result.preview);toast('预览已生成');loadBilling();return}if(d.status==='failed'){toast(d.error||'任务失败');return}setTimeout(()=>pollJob(id),650)}catch(e){toast('任务状态获取失败')}};
$('#genBtn').onclick=submitJob;$('#improveBtn').onclick=submitJob;
$('#openBtn').onclick=()=>previewUrl?window.open(previewUrl,'_blank','noopener,noreferrer'):toast('先生成预览');
$('#downloadBtn').onclick=async()=>{if(!current)return toast('先生成预览');$('#downloadBtn').disabled=true;try{const r=await fetch('/api/simple-package',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:current.title,prompt:$('#prompt').value,improvement:$('#improve').value,html:current.html})});if(!r.ok)throw new Error('下载失败');const blob=await r.blob(),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=(current.title||'software').toLowerCase().replace(/[^a-z0-9\u4e00-\u9fa5]+/g,'-').replace(/^-|-$/g,'')+'.zip';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);toast('ZIP 已下载')}catch(e){toast(e.message)}finally{$('#downloadBtn').disabled=false}};
function rows(){try{return JSON.parse(localStorage.getItem('spa_solutions')||'[]')}catch{return[]}}
function renderHistory(){const r=rows();$('#historyList').innerHTML=r.length?r.map(x=>`<div class="item"><div><strong>${esc(x.title)}</strong><p>${esc(x.time)} · ${esc(x.prompt)}</p></div><div class="actions"><button class="btn" onclick="loadSol('${x.id}')">使用</button><button class="btn danger" onclick="delSol('${x.id}')">删除</button></div></div>`).join(''):'<div class="empty">保存后的预览会出现在这里。</div>'}
$('#saveBtn').onclick=()=>{if(!current)return toast('先生成预览');const r=rows();r.unshift({id:current.preview_id||Date.now().toString(),title:current.title||'沙盒预览',prompt:$('#prompt').value,improve:$('#improve').value,html:current.html,time:new Date().toLocaleString('zh-CN')});localStorage.setItem('spa_solutions',JSON.stringify(r.slice(0,24)));renderHistory();toast('已保存')};
window.loadSol=id=>{const x=rows().find(v=>v.id===id);if(!x)return;$('#prompt').value=x.prompt||'';$('#improve').value=x.improve||'';setPreview({preview_id:x.id,title:x.title,html:x.html});saveDraft();updateTokenPlan()};
window.delSol=id=>{localStorage.setItem('spa_solutions',JSON.stringify(rows().filter(x=>x.id!==id)));renderHistory()};$('#clearHistory').onclick=()=>{localStorage.removeItem('spa_solutions');renderHistory();toast('已清空')};
async function loadSolutions(){try{const r=await fetch('/api/simple-solutions');const d=await r.json();const list=d.solutions||[];$('#solutionList').innerHTML=list.length?list.map(x=>`<div class="item"><div><strong>${esc(x.title)}</strong><p>${esc(x.summary)}</p><div class="tags">${(x.tags||[]).slice(0,6).map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div></div><div class="actions"><button class="btn" onclick='useCurated(${JSON.stringify(x).replace(/'/g,"&#39;")})'>使用</button></div></div>`).join(''):'<div class="empty">还没有成熟方案。</div>'}catch(e){$('#solutionList').innerHTML='<div class="empty">方案加载失败。</div>'}}
window.useCurated=x=>{$('#prompt').value=x.prompt||x.summary||x.title;$('#improve').value='';saveDraft();updateTokenPlan();submitJob()};
async function loadBilling(){try{const r=await fetch('/api/billing');const d=await r.json();$('#balance').textContent=(d.remaining_tokens||0).toLocaleString();$('#quotaText').textContent=`免费 ${Number(d.free_quota||0).toLocaleString()} · 已购 ${Number(d.purchased_tokens||0).toLocaleString()} · 已用 ${Number(d.used_tokens||0).toLocaleString()}`;const orders=(d.orders||[]).slice().reverse(),events=(d.token_events||[]).slice().reverse();const orderHtml=orders.map(x=>`<div class="record"><span>${esc(x.created_at)} · ${esc(x.status)}</span><strong>¥${esc(x.amount_yuan)} / ${Number(x.tokens||0).toLocaleString()} tokens</strong></div>`).join('');const eventHtml=events.map(x=>`<div class="record"><span>${esc(x.created_at)} · ${esc(x.reason)}</span><strong>-${Number(x.amount||0).toLocaleString()}</strong></div>`).join('');$('#records').innerHTML=orderHtml+eventHtml||'<div class="empty">暂无订单和消耗记录。</div>'}catch(e){}}
$$('.plan').forEach(x=>x.onclick=async()=>{const amount=Number(x.dataset.amount||0);try{const order=await postJson('/api/payment/orders',{amount_yuan:amount});const paid=await postJson('/api/payment/orders/'+order.order.order_id+'/confirm',{});toast(paid.notification||'充值成功');loadBilling();updateTokenPlan()}catch(e){toast(e.message)}});
loadDraft();refreshRuntime();if(!$('#prompt').value)$('#prompt').value='做一个图书管理系统，包含图书、读者、借阅、归还、续借、预约、逾期罚款、权限和数据看板。';renderHistory();loadBilling();loadSolutions();updateTokenPlan();
</script>
</body>
</html>
"""

RESOURCE_TYPE_META: dict[str, tuple[str, str]] = {
    "chain": ("分链能力", "主链可以调用的专项任务能力"),
    "model_provider": ("模型提供方", "可选的大模型服务来源"),
    "model_runtime": ("模型运行时", "当前接入的本地或远程模型服务"),
    "model_pool": ("模型池", "按业务类型隔离的模型服务池"),
    "model_admission": ("准入控制", "模型池租约、限流与回压能力"),
    "integration": ("外部集成", "可规划接入的第三方系统"),
    "solution": ("方案资产", "可复用的历史方案与模板"),
    "knowledge_store": ("知识库", "可供 RAG 检索的学习库"),
    "training_dataset": ("训练数据集", "可用于微调的数据资产"),
    "run_manifest": ("运行清单", "某次任务运行的摘要记录"),
    "evidence_ledger": ("证据账本", "可追溯的证据与来源汇总"),
}
RESOURCE_TYPE_ORDER = (
    "chain",
    "model_provider",
    "model_runtime",
    "model_pool",
    "model_admission",
    "integration",
    "solution",
    "knowledge_store",
    "training_dataset",
    "run_manifest",
    "evidence_ledger",
)
RESOURCE_TAG_LABELS = {
    "low": "低成本",
    "medium": "中等成本",
    "local": "本地",
    "remote": "远程",
    "lease": "租约",
    "backpressure": "回压",
    "high_concurrency": "高并发",
    "model_gateway": "模型网关",
    "rag": "RAG",
    "learning_run": "学习任务",
    "sft": "SFT",
    "dataset": "数据集",
}
WORKFLOW_CHAIN_LABELS = {
    "context": "上下文增强",
    "intent_compile": "意图编译",
    "workflow_dry_run": "工作流预演",
    "research": "研究综合",
    "training": "训练数据准备",
    "github_crawler": "项目爬取",
    "solution_publish": "方案发布",
    "evidence_ledger": "证据账本",
}
HORIZON_LABELS = {
    "immediate": "立即处理",
    "near": "近期推进",
}


class DefaultProductionBrain(AgentBrain):
    """主 DeepSeek 优先的默认生产 Brain；不可用时切到 Codex/离线高成熟度模板。"""

    def __init__(self, primary: AgentBrain, fallback: AgentBrain) -> None:
        self.primary = primary
        self.fallback = fallback
        self._using_fallback = False
        self.last_fallback_reason = ""

    def decide(
        self,
        goal: str,
        plan: dict[str, Any],
        state: ProjectState,
        last_result: dict[str, Any] | None,
        session: Any | None = None,
    ) -> str:
        if self._using_fallback:
            return self.fallback.decide(goal, plan, state, last_result, session=session)
        try:
            return self.primary.decide(goal, plan, state, last_result, session=session)
        except Exception as exc:
            self._using_fallback = True
            self.last_fallback_reason = f"{type(exc).__name__}: {exc}"
            state.structure["default_production_fallback"] = {
                "primary": "main_deepseek",
                "fallback": CODEX_PROVIDER,
                "reason": self.last_fallback_reason[:500],
            }
            return self.fallback.decide(goal, plan, state, last_result, session=session)

    def fix(
        self,
        error_text: str,
        goal: str,
        plan: dict[str, Any],
        state: ProjectState,
        session: Any | None = None,
    ) -> str:
        if self._using_fallback:
            return self.fallback.fix(error_text, goal, plan, state, session=session)
        try:
            return self.primary.fix(error_text, goal, plan, state, session=session)
        except Exception as exc:
            self._using_fallback = True
            self.last_fallback_reason = f"{type(exc).__name__}: {exc}"
            state.structure["default_production_fallback"] = {
                "primary": "main_deepseek",
                "fallback": CODEX_PROVIDER,
                "reason": self.last_fallback_reason[:500],
            }
            return self.fallback.fix(error_text, goal, plan, state, session=session)


_BILLING_LOCK = threading.RLock()


class ProductTaskQueue:
    """Small in-process queue for UI jobs.

    It keeps the frontend responsive and gives the project a real queue
    boundary without forcing every preview click to block on a full agent run.
    Production can swap the backend for Redis/Celery/RQ while keeping the API
    shape stable.
    """

    def __init__(self, processor) -> None:
        self._processor = processor
        self._jobs: dict[str, dict[str, Any]] = {}
        self._queue: queue_lib.Queue[str] = queue_lib.Queue()
        self._lock = threading.RLock()
        self._worker = threading.Thread(target=self._run, name="product-ui-job-worker", daemon=True)
        self._worker.start()

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        job_id = f"job_{secrets.token_hex(8)}"
        now = _now_iso()
        job = {
            "schema": "product_job.v1",
            "job_id": job_id,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "progress": 0,
            "payload": dict(payload),
            "result": {},
            "error": "",
            "notifications": ["任务已进入队列"],
        }
        with self._lock:
            self._jobs[job_id] = job
        self._queue.put(job_id)
        return dict(job)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(str(job_id or ""))
            return json.loads(json.dumps(job, ensure_ascii=False)) if job else None

    def list(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = sorted(self._jobs.values(), key=lambda row: str(row.get("created_at", "")), reverse=True)
            return json.loads(json.dumps(rows[: max(int(limit), 1)], ensure_ascii=False))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counts: dict[str, int] = {}
            for job in self._jobs.values():
                status = str(job.get("status", "unknown"))
                counts[status] = counts.get(status, 0) + 1
            return {
                "schema": "product_job_queue.v1",
                "queued_size": self._queue.qsize(),
                "counts": counts,
                "jobs": self.list(limit=20),
            }

    def _patch(self, job_id: str, **updates: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.update(updates)
            job["updated_at"] = _now_iso()

    def _run(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                self._patch(job_id, status="running", progress=25, notifications=["任务开始执行"])
                job = self.get(job_id) or {}
                result = self._processor(job)
                self._patch(job_id, status="finished", progress=100, result=result, notifications=["任务已完成"])
            except Exception as exc:  # pragma: no cover - defensive worker boundary
                self._patch(
                    job_id,
                    status="failed",
                    progress=100,
                    error=f"{type(exc).__name__}: {exc}",
                    notifications=["任务失败，请调整需求后重试"],
                )
            finally:
                self._queue.task_done()


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _estimate_tokens(*texts: str, output_tokens: int = 0) -> int:
    joined = "\n".join(str(text or "") for text in texts)
    cjk = sum(1 for ch in joined if "\u4e00" <= ch <= "\u9fff")
    ascii_chars = max(len(joined) - cjk, 0)
    estimated = int(ascii_chars / 4 + cjk * 1.15 + max(int(output_tokens), 0))
    return max(1, estimated)


def _billing_path(root: Path) -> Path:
    return root / ".agent_billing.json"


def _load_billing(root: Path) -> dict[str, Any]:
    try:
        raw = json.loads(_billing_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    raw.setdefault("schema", "billing.v1")
    raw.setdefault("accounts", {})
    return raw


def _save_billing(root: Path, data: dict[str, Any]) -> None:
    path = _billing_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _account_key(user: Any | None) -> str:
    return str(getattr(user, "id", "") or getattr(user, "username", "") or "anonymous")


def _ensure_billing_account(data: dict[str, Any], user: Any | None) -> dict[str, Any]:
    accounts = data.setdefault("accounts", {})
    key = _account_key(user)
    account = accounts.setdefault(
        key,
        {
            "user_id": key,
            "username": str(getattr(user, "username", "") or "anonymous"),
            "free_quota": FREE_TOKEN_QUOTA,
            "purchased_tokens": 0,
            "used_tokens": 0,
            "orders": [],
            "token_events": [],
            "created_at": _now_iso(),
        },
    )
    account.setdefault("free_quota", FREE_TOKEN_QUOTA)
    account.setdefault("purchased_tokens", 0)
    account.setdefault("used_tokens", 0)
    account.setdefault("orders", [])
    account.setdefault("token_events", [])
    return account


def _billing_snapshot(root: Path, user: Any | None) -> dict[str, Any]:
    with _BILLING_LOCK:
        data = _load_billing(root)
        account = _ensure_billing_account(data, user)
        _save_billing(root, data)
        total = int(account.get("free_quota", 0)) + int(account.get("purchased_tokens", 0))
        used = int(account.get("used_tokens", 0))
        remaining = max(total - used, 0)
        return {
            "schema": "billing_snapshot.v1",
            "username": str(account.get("username", "")),
            "free_quota": int(account.get("free_quota", 0)),
            "purchased_tokens": int(account.get("purchased_tokens", 0)),
            "used_tokens": used,
            "remaining_tokens": remaining,
            "total_tokens": total,
            "low_quota": remaining < max(int(total * 0.15), 3_000),
            "orders": list(account.get("orders", []))[-20:],
            "token_events": list(account.get("token_events", []))[-20:],
        }


def _consume_tokens(
    root: Path,
    user: Any | None,
    amount: int,
    *,
    reason: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    amount = max(int(amount), 1)
    with _BILLING_LOCK:
        data = _load_billing(root)
        account = _ensure_billing_account(data, user)
        total = int(account.get("free_quota", 0)) + int(account.get("purchased_tokens", 0))
        used = int(account.get("used_tokens", 0))
        remaining = max(total - used, 0)
        if amount > remaining:
            _save_billing(root, data)
            return {
                "ok": False,
                "reason": "insufficient_tokens",
                "required_tokens": amount,
                "remaining_tokens": remaining,
                "billing": _billing_snapshot(root, user),
            }
        account["used_tokens"] = used + amount
        event = {
            "event_id": f"tok_{secrets.token_hex(6)}",
            "created_at": _now_iso(),
            "amount": amount,
            "reason": reason,
            "metadata": dict(metadata or {}),
        }
        account.setdefault("token_events", []).append(event)
        _save_billing(root, data)
    snapshot = _billing_snapshot(root, user)
    return {
        "ok": True,
        "event": event,
        "used_tokens": amount,
        "billing": snapshot,
        "notification": f"本次消耗约 {amount} tokens，剩余 {snapshot['remaining_tokens']} tokens",
    }


def _create_payment_order(root: Path, user: Any | None, amount_yuan: int) -> dict[str, Any]:
    amount_yuan = max(int(amount_yuan), 1)
    order = {
        "order_id": f"pay_{secrets.token_hex(8)}",
        "created_at": _now_iso(),
        "amount_yuan": amount_yuan,
        "tokens": amount_yuan * TOKEN_PER_YUAN,
        "status": "pending",
        "channel": "demo_wallet",
        "idempotency_key": f"{_account_key(user)}:{amount_yuan}:{int(time.time())}",
    }
    with _BILLING_LOCK:
        data = _load_billing(root)
        account = _ensure_billing_account(data, user)
        account.setdefault("orders", []).append(order)
        _save_billing(root, data)
    return {"schema": "payment_order.v1", "order": order, "billing": _billing_snapshot(root, user)}


def _confirm_payment_order(root: Path, user: Any | None, order_id: str) -> dict[str, Any]:
    with _BILLING_LOCK:
        data = _load_billing(root)
        account = _ensure_billing_account(data, user)
        target = None
        for order in account.setdefault("orders", []):
            if str(order.get("order_id", "")) == str(order_id):
                target = order
                break
        if not target:
            return {"schema": "payment_confirm.v1", "ok": False, "reason": "order_not_found"}
        if target.get("status") != "paid":
            target["status"] = "paid"
            target["paid_at"] = _now_iso()
            account["purchased_tokens"] = int(account.get("purchased_tokens", 0)) + int(target.get("tokens", 0))
        _save_billing(root, data)
    return {
        "schema": "payment_confirm.v1",
        "ok": True,
        "order": target,
        "billing": _billing_snapshot(root, user),
        "notification": f"支付成功，到账 {target.get('tokens', 0)} tokens",
    }


def _model_source(value: Any) -> str:
    raw = str(value or "local").strip().lower()
    return "api" if raw in {"api", "llm", "cloud", "remote"} else "local"


def _build_product_token_plan(
    root: Path,
    user: Any | None,
    *,
    prompt: str,
    improvement: str = "",
    model_source: str = "local",
    provider: str = DEFAULT_PRODUCTION_PROVIDER,
    model: str = "",
    max_output_tokens: int = 1400,
) -> dict[str, Any]:
    source = _model_source(model_source)
    provider_name = normalise_provider(provider or DEFAULT_PRODUCTION_PROVIDER)
    prompt_text = "\n".join(part for part in (prompt, improvement) if part)
    estimated_input = _estimate_tokens(prompt, improvement)
    estimated_total = _estimate_tokens(prompt, improvement, output_tokens=max_output_tokens)
    route_plan = build_model_route_plan(
        prompt[:280] or DEFAULT_GOAL,
        prompt=prompt_text,
        max_output_tokens=max_output_tokens,
        business_type="product_ui",
        require_json=False,
    )
    billing = _billing_snapshot(root, user)
    billable = source == "api"
    can_run = (not billable) or int(billing.get("remaining_tokens", 0)) >= estimated_total
    return {
        "schema": "product_token_plan.v1",
        "model_source": source,
        "provider": provider_name,
        "model": str(model or ""),
        "estimate": {
            "input_tokens": estimated_input,
            "max_output_tokens": int(max_output_tokens),
            "estimated_total_tokens": estimated_total,
        },
        "billing_policy": {
            "billable": billable,
            "local_policy": "本地部署模型只用于路由选择和上下文切片，不扣真实 token",
            "api_policy": "API 调用先按估算做准入，真实 usage 可在模型返回后回填校准",
        },
        "admission": {
            "can_run": can_run,
            "reason": "ok" if can_run else "insufficient_tokens",
            "required_tokens": estimated_total if billable else 0,
            "remaining_tokens": int(billing.get("remaining_tokens", 0)),
        },
        "route_plan": {
            "selected_pool": route_plan.get("selected_pool"),
            "pool": route_plan.get("pool"),
            "context_budget": route_plan.get("context_budget"),
            "token_accounting": route_plan.get("token_accounting"),
        },
        "billing": billing,
    }


def _process_simple_job(job: dict[str, Any]) -> dict[str, Any]:
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    prompt = str(payload.get("prompt", "") or "")
    improvement = str(payload.get("improvement", "") or "")
    preview = _build_simple_preview(prompt, improvement)
    return {
        "schema": "product_job_result.v1",
        "preview": preview,
        "model_source": str(payload.get("model_source", "local")),
        "provider": str(payload.get("provider", DEFAULT_PRODUCTION_PROVIDER)),
        "model": str(payload.get("model", "")),
        "token_estimate": payload.get("token_estimate", {}),
        "package_api": "/api/simple-package",
    }


CSS = """
:root {
  color-scheme: light;
  --paper: #f7f5ef;
  --panel: #ffffff;
  --ink: #171a1d;
  --muted: #69706a;
  --line: #d9ded4;
  --accent: #1d7a57;
  --accent-soft: #e8f5ee;
  --warn: #b8642b;
  --danger: #a6422a;
  --ok: #137a4f;
  --code: #111418;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  background: var(--paper);
  color: var(--ink);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI",
    sans-serif;
}
.topbar {
  border-bottom: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(10px);
}
.topbar-inner, .main {
  width: min(1240px, calc(100vw - 32px));
  margin: 0 auto;
}
.topbar-inner {
  min-height: 58px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.brand {
  font-size: 16px;
  font-weight: 720;
  letter-spacing: 0;
}
.status-pill {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 6px 10px;
  color: var(--muted);
  font-size: 12px;
  white-space: nowrap;
}
.topbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.main { padding: 28px 0 48px; }
.composer, .surface {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  box-shadow: 0 14px 36px rgba(26, 30, 27, 0.08);
}
.composer { padding: 18px; }
label.heading {
  display: block;
  font-size: 13px;
  font-weight: 700;
  color: var(--muted);
  margin: 0 0 8px;
}
textarea {
  width: 100%;
  min-height: 172px;
  resize: vertical;
  border: 1px solid #cbd1c7;
  border-radius: 8px;
  padding: 14px;
  font: 15px/1.55 ui-sans-serif, system-ui, sans-serif;
  color: var(--ink);
  background: #fffefa;
  outline: none;
}
textarea:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(29, 122, 87, 0.14);
}
.controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  margin-top: 14px;
}
.mode-note {
  width: 100%;
  margin: 0;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.5;
}
.mode-note strong { color: var(--ink); }
.api-setting[hidden] { display: none; }
.modes {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.mode {
  position: relative;
  display: inline-flex;
}
.mode input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}
.mode span, .check span {
  display: inline-flex;
  align-items: center;
  min-height: 38px;
  border: 1px solid #cbd1c7;
  border-radius: 8px;
  padding: 8px 11px;
  background: #fff;
  color: var(--ink);
  font-size: 13px;
  font-weight: 680;
  cursor: pointer;
}
.mode input:checked + span {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: #10533a;
}
.check {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--muted);
  font-size: 13px;
}
.check input {
  width: 16px;
  height: 16px;
  accent-color: var(--accent);
}
.actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
select, input[type="text"], input[type="search"] {
  min-height: 38px;
  border: 1px solid #cbd1c7;
  border-radius: 8px;
  background: #fff;
  color: var(--ink);
  padding: 8px 10px;
  font: 13px/1.3 ui-sans-serif, system-ui, sans-serif;
}
.model-row {
  display: grid;
  grid-template-columns: minmax(180px, 0.8fr) minmax(220px, 1fr);
  gap: 10px;
  margin-top: 12px;
}
.provider-label {
  display: block;
  margin: 14px 0 8px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 760;
}
button, .button {
  border: 0;
  border-radius: 8px;
  min-height: 40px;
  padding: 0 15px;
  background: var(--code);
  color: white;
  font-weight: 760;
  font-size: 14px;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.button.secondary {
  background: #fff;
  color: var(--ink);
  border: 1px solid var(--line);
}
.auth-card {
  width: min(420px, 100%);
  margin: 54px auto 0;
}
.auth-card input {
  width: 100%;
  min-height: 42px;
  margin-bottom: 10px;
}
.auth-card .button, .auth-card button {
  width: 100%;
}
.auth-error {
  border: 1px solid rgba(166, 66, 42, 0.28);
  border-radius: 8px;
  padding: 9px 10px;
  background: #fff4ef;
  color: var(--danger);
  font-size: 13px;
  margin-bottom: 10px;
}
.auth-links {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-top: 12px;
  font-size: 13px;
}
.auth-links a {
  color: var(--accent);
  text-decoration: none;
  font-weight: 720;
}
.result-grid {
  display: grid;
  grid-template-columns: minmax(220px, 260px) minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}
.resource-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 12px;
}
.page-hero {
  display: grid;
  gap: 14px;
}
.page-hero h1 {
  margin: 4px 0 8px;
  font-size: 24px;
  line-height: 1.2;
}
.eyebrow {
  margin: 0;
  color: var(--accent);
  font-size: 12px;
  font-weight: 780;
  letter-spacing: 0.02em;
}
.helper-copy {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.65;
}
.metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
}
.metric-card {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 12px;
  background: #fbfcf8;
}
.metric-card span {
  display: block;
  color: var(--muted);
  font-size: 12px;
}
.metric-card strong {
  display: block;
  margin-top: 4px;
  font-size: 24px;
  line-height: 1;
}
.section-heading {
  display: flex;
  justify-content: space-between;
  align-items: end;
  gap: 14px;
  margin-bottom: 14px;
}
.section-heading h2 {
  margin-bottom: 4px;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.search-box {
  display: grid;
  gap: 5px;
  color: var(--muted);
  font-size: 12px;
}
.search-box input {
  min-width: min(320px, 70vw);
}
.filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.filter-chip {
  min-height: 34px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: #fff;
  color: var(--muted);
  padding: 0 12px;
  font-size: 13px;
  font-weight: 720;
}
.filter-chip[aria-pressed="true"] {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: #10533a;
}
.resource-toolbar-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
  color: var(--muted);
  font-size: 13px;
}
.mini-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.mini-actions button {
  min-height: 32px;
  padding: 0 11px;
  background: #fff;
  color: var(--ink);
  border: 1px solid var(--line);
  font-size: 12px;
}
.interactive-card {
  transition: border-color 0.18s ease, transform 0.18s ease, box-shadow 0.18s ease;
}
.interactive-card:hover {
  transform: translateY(-1px);
  border-color: rgba(29, 122, 87, 0.35);
  box-shadow: 0 10px 24px rgba(26, 30, 27, 0.08);
}
.interactive-card summary {
  cursor: pointer;
  list-style: none;
}
.interactive-card summary::-webkit-details-marker {
  display: none;
}
.interactive-card summary::after {
  content: "展开";
  display: inline-flex;
  margin-top: 10px;
  border-radius: 999px;
  border: 1px solid var(--line);
  padding: 3px 8px;
  color: var(--muted);
  font-size: 11px;
  background: #fff;
}
.interactive-card[open] summary::after {
  content: "收起";
}
.detail-body {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--line);
}
.detail-lead {
  margin: 0 0 10px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.6;
}
.detail-list {
  display: grid;
  gap: 8px;
  margin: 0;
}
.detail-list div {
  display: grid;
  gap: 3px;
}
.detail-list dt {
  color: var(--muted);
  font-size: 12px;
}
.detail-list dd {
  margin: 0;
  color: var(--ink);
  font-size: 13px;
  line-height: 1.55;
  overflow-wrap: anywhere;
}
.empty-state {
  margin: 10px 0 0;
  border: 1px dashed var(--line);
  border-radius: 8px;
  padding: 16px;
  color: var(--muted);
  text-align: center;
  background: #fbfcf8;
}
.resource-card {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
  background: #fffefa;
}
.resource-card h3 {
  margin: 0 0 6px;
  font-size: 14px;
}
.resource-card p {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.resource-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 9px;
}
.resource-tags span {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 4px 7px;
  color: var(--muted);
  font-size: 11px;
  background: #fff;
}
.json-block {
  margin: 10px 0 0;
  max-height: 420px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
  background: #111418;
  color: #f3f7ef;
  font: 12px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  white-space: pre-wrap;
}
.radar-hero {
  display: grid;
  grid-template-columns: minmax(220px, 0.8fr) minmax(0, 1.2fr);
  gap: 14px;
  align-items: stretch;
}
.radar-score {
  display: grid;
  place-items: center;
  min-height: 190px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fbfcf8;
}
.radar-score strong {
  font-size: 48px;
  line-height: 1;
}
.score-caption {
  margin: 8px 0 0;
  color: var(--muted);
  font-size: 13px;
}
.recommendation-card {
  margin-top: 12px;
  border-left: 4px solid var(--accent);
  border-radius: 0 8px 8px 0;
  background: #f4fbf7;
  padding: 12px;
}
.recommendation-card strong {
  display: block;
  margin-bottom: 4px;
}
.recommendation-card p {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.55;
}
.radar-card {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 13px;
  background: #fffefa;
}
.radar-card h3 {
  margin: 0 0 7px;
  font-size: 15px;
}
.radar-card p {
  margin: 0 0 8px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.55;
}
.radar-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px;
}
.workflow-steps {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}
.workflow-steps span {
  border: 1px solid #cce3d7;
  border-radius: 999px;
  padding: 5px 8px;
  background: #f4fbf7;
  color: #10533a;
  font-size: 12px;
  font-weight: 720;
}
.workflow-list,
.plain-list {
  margin: 0;
  padding-left: 18px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.6;
}
.workflow-list li + li,
.plain-list li + li {
  margin-top: 5px;
}
.muted-inline {
  color: var(--muted);
  font-size: 12px;
}
.status-panel {
  position: sticky;
  top: 74px;
}
.surface { padding: 16px; }
.surface h2 {
  margin: 0 0 10px;
  font-size: 14px;
}
.kv {
  display: grid;
  gap: 9px;
  color: var(--muted);
  font-size: 13px;
}
.kv strong {
  display: block;
  color: var(--ink);
  font-size: 14px;
  margin-top: 2px;
  word-break: break-word;
}
.error {
  border-color: rgba(184, 100, 43, 0.45);
  background: #fff8f0;
  color: var(--warn);
}
.files {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(155px, 1fr));
  gap: 8px;
  max-height: 360px;
  overflow: auto;
  margin: 0;
  padding: 0;
  list-style: none;
}
.files a {
  display: block;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 9px 10px;
  color: var(--ink);
  text-decoration: none;
  background: #fffefa;
  overflow-wrap: anywhere;
  font-size: 13px;
}
.improve-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: end;
}
.improve-form textarea {
  min-height: 84px;
  resize: vertical;
}
.improve-form .form-actions {
  display: grid;
  gap: 8px;
  justify-items: stretch;
}
.lineage {
  margin-top: 10px;
  color: var(--muted);
  font-size: 12px;
  overflow-wrap: anywhere;
}
.lineage strong {
  color: var(--ink);
}
.lineage a {
  color: var(--accent);
  text-decoration: none;
  font-weight: 720;
}
.handoff-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  border: 1px solid #cce3d7;
  border-radius: 8px;
  padding: 12px;
  background: #f4fbf7;
}
.handoff-card p {
  margin: 0;
  color: var(--muted);
  line-height: 1.5;
  font-size: 13px;
}
.handoff-card code {
  color: #10533a;
  font-weight: 760;
}
.maturity {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: 14px;
  align-items: start;
}
.score-card {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px;
  background: #fbfcf8;
}
.score-value {
  display: block;
  font-size: 38px;
  line-height: 1;
  font-weight: 820;
  letter-spacing: 0;
}
.score-value small {
  font-size: 16px;
  color: var(--muted);
}
.score-level {
  margin-top: 8px;
  color: var(--accent);
  font-weight: 780;
}
.score-bar {
  height: 9px;
  margin-top: 12px;
  overflow: hidden;
  border-radius: 999px;
  background: #e8ece5;
}
.score-bar span {
  display: block;
  height: 100%;
  width: var(--score);
  border-radius: inherit;
  background: var(--accent);
}
.maturity-body {
  display: grid;
  gap: 13px;
}
.checks {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(128px, 1fr));
  gap: 8px;
}
.check-item {
  display: flex;
  gap: 8px;
  align-items: center;
  min-height: 36px;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 7px 9px;
  background: #fffefa;
  color: var(--muted);
  font-size: 12px;
  font-weight: 680;
}
.check-mark {
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  display: inline-grid;
  place-items: center;
  border-radius: 999px;
  background: #edf1ea;
  color: var(--muted);
  font-size: 12px;
  font-weight: 900;
}
.check-item.ok {
  color: #143f31;
  border-color: #cce3d7;
  background: #f4fbf7;
}
.check-item.ok .check-mark {
  background: var(--accent);
  color: white;
}
.insights {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.insights h3 {
  margin: 0 0 8px;
  font-size: 13px;
}
.insights ul {
  margin: 0;
  padding-left: 18px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.55;
}
.insights li + li {
  margin-top: 5px;
}
.artifact-count {
  color: var(--muted);
  font-size: 12px;
  font-weight: 680;
}
pre {
  margin: 0;
  max-height: 360px;
  overflow: auto;
  padding: 14px;
  border-radius: 8px;
  background: var(--code);
  color: #f2f4f0;
  font: 12px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.result-dashboard {
  display: grid;
  grid-template-columns: minmax(0, 1.08fr) minmax(360px, 0.92fr);
  grid-template-areas:
    "maturity maturity"
    "improve improve"
    "files source"
    "sandbox sandbox";
  gap: 14px;
}
.maturity-panel { grid-area: maturity; }
.improve-panel { grid-area: improve; }
.files-panel { grid-area: files; }
.source-panel { grid-area: source; }
.sandbox-panel { grid-area: sandbox; }
.preview-frame {
  width: 100%;
  min-height: 620px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: white;
}
@media (max-width: 760px) {
  .topbar-inner, .main { width: min(100vw - 22px, 1240px); }
  .result-grid { grid-template-columns: 1fr; }
  .status-panel { position: static; }
  .result-dashboard {
    grid-template-columns: 1fr;
    grid-template-areas:
      "maturity"
      "improve"
      "files"
      "source"
      "sandbox";
  }
  .handoff-card { grid-template-columns: 1fr; }
  .files { max-height: none; }
  .controls { align-items: stretch; }
  .actions, .modes { width: 100%; }
  .mode span, button, .button { flex: 1; }
  .model-row { grid-template-columns: 1fr; }
  .maturity, .insights { grid-template-columns: 1fr; }
  .radar-hero { grid-template-columns: 1fr; }
  .section-heading { align-items: stretch; flex-direction: column; }
  .search-box input { min-width: 0; width: 100%; }
  .preview-frame { min-height: 520px; }
}
"""


AUTH_TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }} · Software Production Agent</title>
  <style>{{ css|safe }}</style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand">Software Production Agent</div>
      <div class="status-pill">workspace auth</div>
    </div>
  </header>
  <main class="main">
    <form class="composer auth-card" method="post" action="{{ action }}">
      <label class="heading">{{ title }}</label>
      {% if error %}<div class="auth-error">{{ error }}</div>{% endif %}
      <input type="text" name="username" autocomplete="username" placeholder="用户名" autofocus required>
      <input type="password" name="password" autocomplete="{{ autocomplete }}" placeholder="密码（至少 8 位）" required>
      {% if next_url %}<input type="hidden" name="next" value="{{ next_url }}">{% endif %}
      <button type="submit">{{ submit }}</button>
      <div class="auth-links">
        {% if mode == "login" %}
          <a href="{{ url_for('register') }}">注册账号</a>
        {% else %}
          <a href="{{ url_for('login') }}">已有账号登录</a>
        {% endif %}
        <a href="{{ url_for('healthz') }}">健康检查</a>
      </div>
    </form>
  </main>
</body>
</html>
"""


RESOURCES_TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>资源中心 · Software Production Agent</title>
  <style>{{ css|safe }}</style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand">Software Production Agent</div>
      <div class="topbar-actions">
        <div class="status-pill">{{ current_user.username }} · {{ current_user.role }}</div>
        <a class="button secondary" href="{{ url_for('intent_page') }}">意图编排</a>
        <a class="button secondary" href="{{ url_for('index') }}">新需求</a>
        <a class="button secondary" href="{{ url_for('logout') }}">退出</a>
      </div>
    </div>
  </header>
  <main class="main">
    <section class="surface page-hero">
      <div>
        <p class="eyebrow">资源中心</p>
        <h1>系统当前可用能力</h1>
        <p class="helper-copy">
          这里汇总了主链可以调用的分链、模型服务、方案资产、知识库和训练数据。
          你可以按类型筛选，也可以搜索某个能力名称、模块路径或标签。
        </p>
      </div>
      <div class="metric-grid">
        {% for item in resource_overview %}
          <article class="metric-card">
            <span>{{ item.label }}</span>
            <strong>{{ item.count }}</strong>
          </article>
        {% endfor %}
        <article class="metric-card">
          <span>资源总数</span>
          <strong>{{ registry.summary.total }}</strong>
        </article>
      </div>
    </section>
    <section class="surface" style="margin-top:14px;">
      <div class="section-heading">
        <div>
          <h2>资源清单</h2>
          <p class="helper-copy">默认先看中文说明，展开卡片后再看技术细节。</p>
        </div>
        <label class="search-box">
          <span>搜索资源</span>
          <input id="resource-search" type="search" placeholder="例如：研究、模型池、solution、RAG">
        </label>
      </div>
      <div class="filter-row" role="toolbar" aria-label="资源类型筛选">
        {% for tab in resource_tabs %}
          <button class="filter-chip" type="button" data-resource-filter="{{ tab.value }}" aria-pressed="{% if loop.first %}true{% else %}false{% endif %}">
            {{ tab.label }} · {{ tab.count }}
          </button>
        {% endfor %}
      </div>
      <div class="resource-toolbar-meta">
        <span id="resource-visible-count">共显示 {{ resource_cards|length }} 项</span>
        <div class="mini-actions">
          <button type="button" data-resource-open="all">全部展开</button>
          <button type="button" data-resource-open="none">全部收起</button>
        </div>
      </div>
      <div class="resource-grid">
        {% for item in resource_cards %}
          <details class="resource-card interactive-card" data-resource-card data-type="{{ item.type }}" data-search="{{ item.search_text }}">
            <summary>
              <p class="eyebrow">{{ item.type_label }}</p>
              <h3>{{ item.name }}</h3>
              <p>{{ item.type_hint }}</p>
              {% if item.display_tags %}
                <div class="resource-tags">
                  {% for tag in item.display_tags %}
                    <span>{{ tag }}</span>
                  {% endfor %}
                </div>
              {% endif %}
            </summary>
            <div class="detail-body">
              {% if item.summary %}<p class="detail-lead">{{ item.summary }}</p>{% endif %}
              {% if item.detail_rows %}
                <dl class="detail-list">
                  {% for row in item.detail_rows %}
                    <div>
                      <dt>{{ row.label }}</dt>
                      <dd>{{ row.value }}</dd>
                    </div>
                  {% endfor %}
                </dl>
              {% endif %}
            </div>
          </details>
        {% endfor %}
      </div>
      <p class="empty-state" id="resource-empty" hidden>没有找到匹配的资源，可以换个关键词或切回“全部”。</p>
    </section>
  </main>
  <script>
    (() => {
      const cards = [...document.querySelectorAll("[data-resource-card]")];
      const buttons = [...document.querySelectorAll("[data-resource-filter]")];
      const search = document.getElementById("resource-search");
      const visibleCount = document.getElementById("resource-visible-count");
      const emptyState = document.getElementById("resource-empty");
      let activeType = "all";
      function refresh() {
        const keyword = (search.value || "").trim().toLowerCase();
        let visible = 0;
        cards.forEach((card) => {
          const typeOk = activeType === "all" || card.dataset.type === activeType;
          const textOk = !keyword || (card.dataset.search || "").includes(keyword);
          const show = typeOk && textOk;
          card.hidden = !show;
          if (show) visible += 1;
        });
        visibleCount.textContent = `共显示 ${visible} 项`;
        emptyState.hidden = visible !== 0;
      }
      buttons.forEach((button) => {
        button.addEventListener("click", () => {
          activeType = button.dataset.resourceFilter || "all";
          buttons.forEach((item) => item.setAttribute("aria-pressed", item === button ? "true" : "false"));
          refresh();
        });
      });
      search.addEventListener("input", refresh);
      document.querySelector('[data-resource-open="all"]').addEventListener("click", () => {
        cards.filter((card) => !card.hidden).forEach((card) => card.open = true);
      });
      document.querySelector('[data-resource-open="none"]').addEventListener("click", () => {
        cards.forEach((card) => card.open = false);
      });
      refresh();
    })();
  </script>
</body>
</html>
"""


INNOVATION_TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>创新雷达 · Software Production Agent</title>
  <style>{{ css|safe }}</style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand">Software Production Agent</div>
      <div class="topbar-actions">
        <div class="status-pill">{{ current_user.username }} · {{ current_user.role }}</div>
        <a class="button secondary" href="{{ url_for('intent_page') }}">意图编排</a>
        <a class="button secondary" href="{{ url_for('resources_page') }}">资源中心</a>
        <a class="button secondary" href="{{ url_for('index') }}">新需求</a>
        <a class="button secondary" href="{{ url_for('logout') }}">退出</a>
      </div>
    </div>
  </header>
  <main class="main">
    <section class="surface radar-hero">
      <div class="radar-score">
        <div>
          <strong>{{ radar.platform_score }}</strong>
          <p class="score-caption">平台能力评分</p>
        </div>
      </div>
      <div>
        <h2>{{ radar.north_star }}</h2>
        <p class="mode-note">{{ radar.positioning }}</p>
        <div class="resource-tags">
          {% for bet in radar.signature_bets %}
            <span>{{ bet }}</span>
          {% endfor %}
        </div>
        {% if radar.recommended_next_build %}
          <aside class="recommendation-card">
            <strong>当前最值得优先推进</strong>
            <p>{{ radar.recommended_next_build.title }}：{{ radar.recommended_next_build.thesis }}</p>
          </aside>
        {% endif %}
      </div>
    </section>
    <section class="surface" style="margin-top:14px;">
      <div class="section-heading">
        <div>
          <h2>创新机会卡</h2>
          <p class="helper-copy">点击卡片可以查看“为什么做、依据是什么、下一步怎么走”。</p>
        </div>
      </div>
      <div class="filter-row" role="toolbar" aria-label="创新机会筛选">
        <button class="filter-chip" type="button" data-horizon-filter="all" aria-pressed="true">全部</button>
        <button class="filter-chip" type="button" data-horizon-filter="immediate" aria-pressed="false">立即处理</button>
        <button class="filter-chip" type="button" data-horizon-filter="near" aria-pressed="false">近期推进</button>
      </div>
      <div class="resource-toolbar-meta">
        <span id="innovation-visible-count">共显示 {{ radar.innovation_cards|length }} 项</span>
        <div class="mini-actions">
          <button type="button" data-radar-open="all">全部展开</button>
          <button type="button" data-radar-open="none">全部收起</button>
        </div>
      </div>
      <div class="radar-grid">
        {% for card in radar.innovation_cards %}
          <details class="radar-card interactive-card" data-innovation-card data-horizon="{{ card.horizon }}">
            <summary>
              <h3>{{ card.title }}</h3>
              <p>{{ card.thesis }}</p>
              <div class="resource-tags">
                <span>综合评分 {{ card.score }}</span>
                <span>影响力 {{ card.impact }}</span>
                <span>{{ card.horizon_label }}</span>
              </div>
            </summary>
            <div class="detail-body">
              <p class="detail-lead"><strong>为什么现在值得做：</strong>{{ card.why_now }}</p>
              <h3>已有依据</h3>
              <ul class="plain-list">
                {% for item in card.evidence %}
                  <li>{{ item }}</li>
                {% endfor %}
              </ul>
              <h3 style="margin-top:12px;">下一步建议</h3>
              <ul class="plain-list">
                {% for item in card.next_steps %}
                  <li>{{ item }}</li>
                {% endfor %}
              </ul>
            </div>
          </details>
        {% endfor %}
      </div>
      <p class="empty-state" id="innovation-empty" hidden>当前筛选下没有机会卡。</p>
    </section>
    <section class="surface" style="margin-top:14px;">
      <div class="section-heading">
        <div>
          <h2>推荐工作流</h2>
          <p class="helper-copy">展开后可以看到任务会经过哪些节点，以及是否联网、是否写文件。</p>
        </div>
      </div>
      <div class="radar-grid">
        {% for template in radar.workflow_templates %}
          <details class="radar-card interactive-card">
            <summary>
              <h3>{{ template.title }}</h3>
              <div class="workflow-steps">
                {% for step in template.steps %}
                  <span>{{ step.label }}</span>
                {% endfor %}
              </div>
              <div class="resource-tags">
                <span>{% if template.validation.ok %}已通过校验{% else %}需要修正{% endif %}</span>
                {% if template.validation.network_required %}<span>需要联网</span>{% endif %}
                {% if template.validation.writes_files %}<span>会写入文件</span>{% endif %}
              </div>
            </summary>
            <div class="detail-body">
              <ol class="workflow-list">
                {% for step in template.steps %}
                  <li>{{ step.label }} <span class="muted-inline">（{{ step.chain }}）</span></li>
                {% endfor %}
              </ol>
            </div>
          </details>
        {% endfor %}
      </div>
    </section>
  </main>
  <script>
    (() => {
      const cards = [...document.querySelectorAll("[data-innovation-card]")];
      const filters = [...document.querySelectorAll("[data-horizon-filter]")];
      const visibleCount = document.getElementById("innovation-visible-count");
      const emptyState = document.getElementById("innovation-empty");
      let activeHorizon = "all";
      function refresh() {
        let visible = 0;
        cards.forEach((card) => {
          const show = activeHorizon === "all" || card.dataset.horizon === activeHorizon;
          card.hidden = !show;
          if (show) visible += 1;
        });
        visibleCount.textContent = `共显示 ${visible} 项`;
        emptyState.hidden = visible !== 0;
      }
      filters.forEach((button) => {
        button.addEventListener("click", () => {
          activeHorizon = button.dataset.horizonFilter || "all";
          filters.forEach((item) => item.setAttribute("aria-pressed", item === button ? "true" : "false"));
          refresh();
        });
      });
      document.querySelector('[data-radar-open="all"]').addEventListener("click", () => {
        cards.filter((card) => !card.hidden).forEach((card) => card.open = true);
      });
      document.querySelector('[data-radar-open="none"]').addEventListener("click", () => {
        cards.forEach((card) => card.open = false);
      });
      refresh();
    })();
  </script>
</body>
</html>
"""


INTENT_TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>意图编排 · Software Production Agent</title>
  <style>{{ css|safe }}</style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand">Software Production Agent</div>
      <div class="topbar-actions">
        <div class="status-pill">{{ current_user.username }} · {{ current_user.role }}</div>
        <a class="button secondary" href="{{ url_for('resources_page') }}">资源中心</a>
        <a class="button secondary" href="{{ url_for('innovation_page') }}">创新雷达</a>
        <a class="button secondary" href="{{ url_for('index') }}">新需求</a>
        <a class="button secondary" href="{{ url_for('logout') }}">退出</a>
      </div>
    </div>
  </header>
  <main class="main">
    <form class="composer" method="post" action="{{ url_for('intent_page') }}">
      <label class="heading" for="intent_goal">意图</label>
      <textarea id="intent_goal" name="goal" autofocus>{{ goal }}</textarea>
      <div class="controls">
        <div class="actions">
          <button type="submit">编译意图</button>
        </div>
      </div>
    </form>
    {% if compilation %}
      <section class="surface" style="margin-top:14px;">
        <h2>编排结果</h2>
        <div class="resource-tags">
          {% for tag in compilation.intent_tags %}
            <span>{{ tag }}</span>
          {% endfor %}
          <span>{% if compilation.validation.ok %}valid{% else %}needs fix{% endif %}</span>
          {% if compilation.validation.network_required %}<span>network</span>{% endif %}
          {% if compilation.validation.writes_files %}<span>writes files</span>{% endif %}
        </div>
      </section>
      <section class="surface" style="margin-top:14px;">
        <h2>节点</h2>
        <div class="resource-grid">
          {% for node in compilation.dry_run.nodes %}
            <article class="resource-card">
              <h3>{{ node.id }}</h3>
              <p>{{ node.chain }} · {{ node.action }}</p>
              <div class="resource-tags">
                {% for permission in node.permissions %}
                  <span>{{ permission }}</span>
                {% endfor %}
              </div>
            </article>
          {% endfor %}
        </div>
      </section>
      <section class="surface" style="margin-top:14px;">
        <h2>风险与资源</h2>
        <div class="radar-grid">
          <article class="radar-card">
            <h3>Risk Notes</h3>
            {% for note in compilation.risk_notes %}
              <p>{{ note }}</p>
            {% endfor %}
          </article>
          <article class="radar-card">
            <h3>Resource Suggestions</h3>
            {% for item in compilation.resource_suggestions[:8] %}
              <p>{{ item.type }} · {{ item.name }}</p>
            {% endfor %}
          </article>
        </div>
        <pre class="json-block">{{ workflow_json }}</pre>
      </section>
    {% endif %}
  </main>
</body>
</html>
"""


INDEX_TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Software Production Agent</title>
  <style>{{ css|safe }}</style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand">Software Production Agent</div>
      <div class="topbar-actions">
        <div class="status-pill">{{ current_user.username }} · {{ current_user.role }}</div>
        <a class="button secondary" href="{{ url_for('intent_page') }}">意图编排</a>
        <a class="button secondary" href="{{ url_for('resources_page') }}">资源中心</a>
        <a class="button secondary" href="{{ url_for('innovation_page') }}">创新雷达</a>
        <a class="button secondary" href="{{ url_for('logout') }}">退出</a>
      </div>
    </div>
  </header>
  <main class="main">
    <form class="composer" method="post" action="{{ url_for('run_product') }}">
      <label class="heading" for="goal">需求</label>
      <textarea id="goal" name="goal" autofocus placeholder="{{ default_goal }}"></textarea>
      <div class="controls">
        <div class="modes" role="radiogroup" aria-label="mode">
          <label class="mode">
            <input type="radio" name="mode" value="local_production" checked>
            <span>默认生产</span>
          </label>
          <label class="mode">
            <input type="radio" name="mode" value="llm">
            <span>LLM 生成</span>
          </label>
        </div>
        <span class="provider-label api-setting">API 大模型</span>
        <div class="modes api-setting" role="radiogroup" aria-label="provider">
          {% for provider in providers %}
            <label class="mode">
              <input type="radio" name="provider" value="{{ provider.name }}" {% if loop.first %}checked{% endif %}>
              <span>{{ provider.label }}</span>
            </label>
          {% endfor %}
        </div>
        <div class="model-row api-setting">
          <select id="model-select" name="model"></select>
          <input id="custom-model" name="custom_model" type="text" placeholder="自定义 model id（可选）">
        </div>
        <div class="actions">
          <label class="check">
            <input type="checkbox" name="events" value="1" checked>
            <span>事件日志</span>
          </label>
          <button type="submit">生成软件</button>
        </div>
        <p class="mode-note">
          <strong>默认生产</strong> 优先使用主 DeepSeek 生产并写入方案备份，主模型不可用时自动使用 Codex/离线高成熟度模板兜底；
          <strong>LLM 生成</strong> 使用 OPENAI/GROQ/DEEPSEEK API，Planner 和 Brain 都走大模型链路。
        </p>
      </div>
    </form>
  </main>
  <script>
    const providers = {{ providers|tojson }};
    const modeInputs = document.querySelectorAll('input[name="mode"]');
    const providerInputs = document.querySelectorAll('input[name="provider"]');
    const modelSelect = document.getElementById('model-select');
    const customModel = document.getElementById('custom-model');
    const apiSettings = document.querySelectorAll('.api-setting');

    function selectedMode() {
      return document.querySelector('input[name="mode"]:checked')?.value || 'local_production';
    }

    function selectedProvider() {
      return document.querySelector('input[name="provider"]:checked')?.value || providers[0].name;
    }

    function refreshModels() {
      const provider = providers.find((item) => item.name === selectedProvider()) || providers[0];
      const current = modelSelect.value;
      modelSelect.innerHTML = '';
      provider.models.forEach((model) => {
        const option = document.createElement('option');
        option.value = model;
        option.textContent = model;
        modelSelect.appendChild(option);
      });
      modelSelect.value = provider.models.includes(current) ? current : provider.default_model;
      customModel.placeholder = `自定义 model id（默认 ${provider.default_model}）`;
    }

    function refreshVisibility() {
      const needsApi = selectedMode() === 'llm';
      apiSettings.forEach((node) => {
        node.hidden = !needsApi;
      });
    }

    providerInputs.forEach((input) => input.addEventListener('change', refreshModels));
    modeInputs.forEach((input) => input.addEventListener('change', refreshVisibility));
    refreshModels();
    refreshVisibility();
  </script>
</body>
</html>
"""


RESULT_TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ run_id }} · Software Production Agent</title>
  <style>{{ css|safe }}</style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand">Software Production Agent</div>
      <div class="actions">
        <span class="status-pill">{{ current_user.username }} · {{ current_user.role }}</span>
        {% if preview_url %}
          <a class="button secondary" href="{{ preview_url }}" target="_blank" rel="noreferrer">沙盒预览</a>
        {% endif %}
        {% if solution_backup_url %}
          <a class="button secondary" href="{{ solution_backup_url }}">方案备份</a>
        {% endif %}
        <a class="button secondary" href="{{ url_for('download_run', run_id=run_id) }}">下载 ZIP</a>
        <a class="button secondary" href="{{ url_for('index') }}">新需求</a>
        <a class="button secondary" href="{{ url_for('intent_page') }}">意图编排</a>
        <a class="button secondary" href="{{ url_for('resources_page') }}">资源中心</a>
        <a class="button secondary" href="{{ url_for('innovation_page') }}">创新雷达</a>
        <a class="button secondary" href="{{ url_for('logout') }}">退出</a>
      </div>
    </div>
  </header>
  <main class="main">
    <div class="result-grid">
      <aside class="surface status-panel {% if error %}error{% endif %}">
        <h2>运行状态</h2>
        <div class="kv">
          <div>模式<strong>{{ mode }}</strong></div>
          <div>Provider<strong>{{ provider }}</strong></div>
          <div>Model<strong>{{ model }}</strong></div>
          <div>进度<strong>{{ progress }}</strong></div>
          <div>阶段<strong>{{ stage }}</strong></div>
          <div>工作区<strong>{{ workspace }}</strong></div>
          {% if error %}<div>错误<strong>{{ error }}</strong></div>{% endif %}
        </div>
      </aside>
      <section class="result-dashboard">
        <div class="surface maturity-panel">
          <h2>项目成熟度</h2>
          <div class="maturity">
            <div class="score-card">
              <span class="score-value">{{ maturity.score }}<small>/100</small></span>
              <div class="score-level">{{ maturity.level }}</div>
              <div class="score-bar" style="--score: {{ maturity.score }}%;"><span></span></div>
              <div class="artifact-count">{{ maturity.artifact_count }} 个用户产物文件</div>
            </div>
            <div class="maturity-body">
              <div class="checks">
                {% for item in maturity.checks %}
                  <div class="check-item {% if item.ok %}ok{% endif %}">
                    <span class="check-mark">{% if item.ok %}✓{% else %}!{% endif %}</span>
                    <span>{{ item.label }}</span>
                  </div>
                {% endfor %}
              </div>
              <div class="insights">
                <div>
                  <h3>主要缺口</h3>
                  <ul>
                    {% for gap in maturity.gaps %}
                      <li>{{ gap }}</li>
                    {% else %}
                      <li>暂无明显结构缺口</li>
                    {% endfor %}
                  </ul>
                </div>
                <div>
                  <h3>下一步建议</h3>
                  <ul>
                    {% for step in maturity.next_steps %}
                      <li>{{ step }}</li>
                    {% endfor %}
                  </ul>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="surface acceptance-panel">
          <h2>方案验收</h2>
          {% if accepted_solution %}
            <p>
              已由 <strong>{{ accepted_solution.accepted_by or "用户" }}</strong>
              在 <strong>{{ accepted_solution.accepted_at or "未知时间" }}</strong>
              确认满意，并沉淀到正式方案库。
            </p>
          {% else %}
            <p>只有你确认满意后，这次交付才会进入正式方案库，后续才会被检索和复用。</p>
            <form method="post" action="{{ url_for('publish_run_solution', run_id=run_id) }}">
              <input type="hidden" name="title" value="{{ run_id }}">
              <button type="submit">满意并沉淀到方案库</button>
            </form>
          {% endif %}
        </div>
        <div class="surface improve-panel">
          <h2>基于此方案继续改进</h2>
          <form class="improve-form" method="post" action="{{ url_for('improve_run', run_id=run_id) }}">
            <textarea
              name="improvement_goal"
              placeholder="输入二次改进要求，例如：增加导入导出、审批流、审计日志、登录权限、真实数据库落库"
              required
            ></textarea>
            <div class="form-actions">
              <input type="hidden" name="mode" value="{{ mode_value }}">
              <input type="hidden" name="provider" value="{{ provider }}">
              <input type="hidden" name="model" value="{{ model }}">
              <label class="check">
                <input type="checkbox" name="events" value="1" checked>
                <span>事件日志</span>
              </label>
              <button type="submit">继续改进</button>
            </div>
          </form>
          {% if source_run %}
            <div class="lineage">
              <strong>版本来源</strong>：
              <a href="{{ url_for('show_run', run_id=source_run) }}">{{ source_run }}</a>
              {% if display_improvement_goal %}
                · <strong>本次改进</strong>：{{ display_improvement_goal }}
              {% endif %}
            </div>
          {% endif %}
        </div>
        <div class="surface files-panel">
          <h2>产物文件</h2>
          <ul class="files">
            {% for file in files %}
              <li><a href="{{ file.url }}">{{ file.path }}</a></li>
            {% else %}
              <li><a href="#">暂无文件</a></li>
            {% endfor %}
          </ul>
        </div>
        <div class="surface source-panel">
          <h2>{{ preview_title }}</h2>
          <pre>{{ preview }}</pre>
        </div>
        {% if preview_url %}
        <div class="surface sandbox-panel">
          <h2>隔离交互预览</h2>
          <iframe
            class="preview-frame"
            src="{{ preview_url }}"
            sandbox="allow-scripts"
            referrerpolicy="no-referrer"
            loading="lazy"
          ></iframe>
        </div>
        {% endif %}
      </section>
    </div>
  </main>
</body>
</html>
"""




def _build_simple_preview(prompt: str, improvement: str = "") -> dict[str, Any]:
    preview_id = f"preview_{secrets.token_hex(4)}"
    title = _simple_title(prompt)
    theme = _simple_theme(prompt + " " + improvement)
    sections = _simple_sections(prompt + " " + improvement)
    escaped_prompt = html_lib.escape(prompt)
    escaped_improvement = html_lib.escape(improvement)
    section_html = "".join(
        f"<article class='card'><strong>{html_lib.escape(name)}</strong><p>{html_lib.escape(desc)}</p></article>"
        for name, desc in sections
    )
    improve_html = (
        f"<div class='note'><strong>改进要求</strong><br>{escaped_improvement}</div>"
        if improvement
        else ""
    )
    html = f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html_lib.escape(title)}</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:{theme['bg']};font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;color:#1f2329}}.page{{min-height:100vh;padding:32px}}.hero{{background:#fff;border:1px solid #e5e6eb;border-radius:26px;padding:34px;box-shadow:0 18px 50px rgba(31,35,41,.08)}}.tag{{display:inline-flex;padding:7px 11px;border-radius:999px;background:{theme['soft']};color:{theme['main']};font-weight:850;font-size:13px}}h1{{margin:18px 0 10px;font-size:34px;letter-spacing:-.045em}}p{{color:#646a73;line-height:1.72}}.actions{{display:flex;gap:12px;margin-top:22px}}button{{border:0;border-radius:13px;padding:12px 16px;font-weight:850;cursor:pointer}}.primary{{background:{theme['main']};color:#fff}}.ghost{{background:#f6f7fb;color:#1f2329}}.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:18px}}.card,.note{{background:#fff;border:1px solid #e5e6eb;border-radius:18px;padding:18px}}.card strong{{display:block;margin-bottom:8px}}.note{{margin-top:18px;background:#fafbfc;font-size:13px;color:#646a73}}@media(max-width:760px){{.page{{padding:16px}}.grid{{grid-template-columns:1fr}}h1{{font-size:27px}}}}
</style></head><body><main class='page'><section class='hero'><span class='tag'>可运行预览</span><h1>{html_lib.escape(title)}</h1><p>这是根据需求生成的产品壳。满意后可以导出 ZIP，里面会带上预览页、产品说明和接口契约。</p><div class='actions'><button class='primary'>主要操作</button><button class='ghost'>查看详情</button></div></section><section class='grid'>{section_html}</section><div class='note'><strong>原始需求</strong><br>{escaped_prompt}</div>{improve_html}</main></body></html>"""
    return {
        "preview_id": preview_id,
        "title": title,
        "prompt": prompt,
        "improvement": improvement,
        "html": html,
    }


def _simple_title(prompt: str) -> str:
    text = re.sub(r"\s+", " ", prompt.strip())
    if not text:
        return "软件预览"
    cleaned = re.sub(r"^(build|create|make|generate|write)\s+(a|an|the)?\s*", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(做一个|创建一个|生成一个|帮我做一个|我要一个)", "", cleaned).strip(" 。.") or text
    return cleaned if len(cleaned) <= 36 else cleaned[:36].rstrip(" ，,.;；。") + "..."


def _simple_theme(text: str) -> dict[str, str]:
    lower = text.lower()
    if any(key in lower for key in ("library", "book", "reader", "borrow", "return", "图书", "读者", "借阅", "归还")):
        return {"main": "#1664ff", "soft": "#eef4ff", "bg": "#f7f9ff"}
    if any(key in lower for key in ("pay", "recharge", "account", "balance", "wallet", "充值", "账户", "余额", "个人中心")):
        return {"main": "#00a870", "soft": "#e8f8f2", "bg": "#f5fbf8"}
    if any(key in lower for key in ("approval", "workflow", "audit", "risk", "审批", "流程", "审计")):
        return {"main": "#f59a23", "soft": "#fff7e8", "bg": "#fffaf2"}
    return {"main": "#1664ff", "soft": "#eef4ff", "bg": "#f6f7fb"}


def _simple_sections(text: str) -> list[tuple[str, str]]:
    lower = text.lower()
    sections = [
        ("核心数据", "实体、状态字段和可检索列表布局。"),
        ("业务操作", "新增、编辑、删除、导出和详情流程。"),
        ("交付内容", "离线预览、README、接口契约和打包清单。"),
    ]
    if any(key in lower for key in ("library", "book", "reader", "borrow", "图书", "读者", "借阅")):
        return [
            ("Books & readers / 图书与读者", "图书目录、读者档案、借阅证和借阅上限。"),
            ("流通流程", "借阅、归还、续借、预约、逾期和罚款。"),
            ("管理看板", "库存预警、审计日志、统计报表和角色权限。"),
        ]
    if any(key in lower for key in ("account", "recharge", "balance", "wallet", "账户", "充值", "余额", "个人中心")):
        return [
            ("余额", "当前余额、套餐卡片和支付状态反馈。"),
            ("充值", "订单创建、待支付状态、幂等校验和对账。"),
            ("记录", "消费记录、发票提示和失败支付恢复。"),
        ]
    if any(key in lower for key in ("approval", "workflow", "audit", "审批", "流程", "审计")):
        return [
            ("待办队列", "待办列表、优先级、负责人和 SLA 字段。"),
            ("状态机", "草稿、待审、通过、驳回和撤销流转。"),
            ("审批轨迹", "审批意见、操作日志和可回滚历史。"),
        ]
    return sections


def _safe_package_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip().lower()).strip("-._")
    return name[:64] or "software-package"


def _simple_package_manifest(title: str, prompt: str, improvement: str) -> dict[str, Any]:
    return {
        "schema": "simple_software_package.v1",
        "title": title,
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "prompt": prompt,
        "improvement": improvement,
        "stack": "Static HTML + OpenAPI contract",
        "entrypoint": "frontend/index.html",
        "files": [
            "README.md",
            "frontend/index.html",
            "docs/PRODUCT_SPEC.md",
            "docs/API_CONTRACT.yaml",
            "docs/DELIVERY_CHECKLIST.md",
            "solution_manifest.json",
        ],
    }


def _build_simple_package_response(prompt: str, improvement: str, html: str, title: str = ""):
    preview = _build_simple_preview(prompt, improvement)
    package_title = title.strip() or str(preview["title"])
    app_html = html.strip() or str(preview["html"])
    slug = _safe_package_name(package_title)
    manifest = _simple_package_manifest(package_title, prompt, improvement)
    readme = f"""# {package_title}

这个软件包由软件工坊导出。

> Software Studio compatibility note: this ZIP can be opened without后端服务。

## 怎么运行

直接用浏览器打开 `frontend/index.html`，或者用任意静态服务器托管该目录。

## 包含内容

- 离线前端预览
- 产品说明
- OpenAPI 风格接口契约
- 交付检查清单
- 可复用方案 manifest

## 原始需求

{prompt}

## 改进要求

{improvement or '无'}
"""
    product_spec = f"""# 产品说明：{package_title}

## 目标
{prompt}

## 核心模块
- 数据看板
- 列表与详情管理
- 新增/编辑流程
- 搜索与筛选
- 导出/下载交付
- 角色感知的操作提示

## 验收标准
- 预览页无需外部服务即可打开。
- 主要实体和流程在页面中可见。
- 后续后端接口可以沿用 `docs/API_CONTRACT.yaml`。
- 软件包不包含本地账号密钥或 `.agent_*` 内部文件。
"""
    api_contract = f"""openapi: 3.0.3
info:
  title: {package_title} API
  version: 0.1.0
paths:
  /api/items:
    get:
      summary: List records
      responses:
        '200':
          description: OK
    post:
      summary: Create record
      responses:
        '201':
          description: Created
  /api/items/{{id}}:
    get:
      summary: Get detail
      responses:
        '200':
          description: OK
    put:
      summary: Update record
      responses:
        '200':
          description: OK
    delete:
      summary: Delete record
      responses:
        '204':
          description: Deleted
"""
    checklist = """# 交付检查清单

- [ ] 已检查预览页
- [ ] 已检查接口契约
- [ ] 已检查数据模型
- [ ] 后端实现时补齐登录、权限和安全校验
- [ ] 涉及支付/外部系统时加入幂等键
- [ ] 已下载 ZIP 并本地打开验证
"""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.md", readme)
        zf.writestr("frontend/index.html", app_html)
        zf.writestr("docs/PRODUCT_SPEC.md", product_spec)
        zf.writestr("docs/API_CONTRACT.yaml", api_contract)
        zf.writestr("docs/DELIVERY_CHECKLIST.md", checklist)
        zf.writestr("solution_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{slug}.zip",
    )


def _curated_solution_catalog() -> list[dict[str, Any]]:
    project = Path(__file__).resolve().parents[2]
    candidates = [project / "examples" / "library_management_solution" / "solution_manifest.json"]
    out: list[dict[str, Any]] = []
    for path in candidates:
        raw = _safe_json(path)
        if not raw:
            continue
        title = str(raw.get("template") or raw.get("title") or path.parent.name)
        tags = raw.get("retrieval_tags") if isinstance(raw.get("retrieval_tags"), list) else []
        out.append(
            {
                "id": path.parent.name,
                "title": title,
                "summary": str(raw.get("goal") or "Reusable curated software solution."),
                "prompt": str(raw.get("demo_prompt") or raw.get("goal") or title),
                "tags": [str(tag) for tag in tags[:10]],
                "quality_score": raw.get("quality_score", 0),
                "path": str(path),
            }
        )
    if not out:
        out.append(
            {
                "id": "library_management_system",
                "title": "Library Management System",
                "summary": "Books, readers, borrowing, returns, overdue fines, reports and audit-ready admin dashboard.",
                "prompt": "做一个图书管理系统，包含图书、读者、借阅、归还、逾期罚款、权限和数据看板。",
                "tags": ["library", "crud", "rbac", "circulation", "dashboard"],
                "quality_score": 9.0,
                "path": "",
            }
        )
    return out

def _default_runs_root() -> Path:
    return Path.cwd() / "product_runs"


def _prompts_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "prompts"


def _slugify_goal(goal: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", goal.strip().lower()).strip("-")
    return slug[:28] or "software"


def _build_run_id(goal: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"run_{stamp}_{_slugify_goal(goal)}_{secrets.token_hex(3)}"


def _normalise_mode(value: str) -> str:
    mode = (value or "local_production").strip()
    mode = MODE_ALIASES.get(mode, mode)
    return mode if mode in ALLOWED_MODES else "local_production"


def _normalise_provider(value: str) -> str:
    provider = normalise_provider(value or "openai")
    return provider if provider in ALLOWED_PROVIDERS else "openai"


def _display_mode(mode: str) -> str:
    return "默认生产" if _normalise_mode(mode) == "local_production" else "LLM 生成"


def _resource_type_label(resource_type: str) -> str:
    return RESOURCE_TYPE_META.get(resource_type, (resource_type or "未知资源", "系统资源"))[0]


def _resource_type_hint(resource_type: str) -> str:
    return RESOURCE_TYPE_META.get(resource_type, (resource_type or "未知资源", "系统资源"))[1]


def _localise_resource_tag(tag: Any) -> str:
    raw = str(tag or "")
    return RESOURCE_TAG_LABELS.get(raw, raw)


def _yes_no(value: Any) -> str:
    return "是" if bool(value) else "否"


def _append_detail(rows: list[dict[str, str]], label: str, value: Any) -> None:
    if value in (None, "", [], (), {}):
        return
    if isinstance(value, (list, tuple, set)):
        text = "、".join(str(item) for item in value if str(item))
    else:
        text = str(value)
    if text:
        rows.append({"label": label, "value": text})


def _resource_detail_rows(item: dict[str, Any]) -> list[dict[str, str]]:
    resource_type = str(item.get("type", "") or "")
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    rows: list[dict[str, str]] = []
    _append_detail(rows, "内部标识", item.get("id"))
    if resource_type == "chain":
        _append_detail(rows, "动作名称", metadata.get("action"))
        _append_detail(rows, "所属模块", metadata.get("module"))
        _append_detail(rows, "所需权限", metadata.get("permissions"))
        _append_detail(rows, "是否联网", _yes_no(metadata.get("network_allowed")))
        _append_detail(rows, "是否写文件", _yes_no(metadata.get("writes_files")))
        _append_detail(rows, "成本等级", _localise_resource_tag(metadata.get("cost_level")))
    elif resource_type == "model_provider":
        _append_detail(rows, "默认模型", metadata.get("default_model"))
        _append_detail(rows, "密钥环境变量", metadata.get("api_key_env"))
        _append_detail(rows, "服务地址", metadata.get("base_url"))
        _append_detail(rows, "是否需要密钥", _yes_no(metadata.get("api_key_required")))
    elif resource_type == "model_runtime":
        _append_detail(rows, "运行状态", metadata.get("serving_hint"))
        _append_detail(rows, "服务地址", metadata.get("base_url"))
        _append_detail(rows, "是否本地端点", _yes_no(metadata.get("local_endpoint")))
    elif resource_type == "model_pool":
        _append_detail(rows, "运行时", metadata.get("runtime"))
        _append_detail(rows, "最大上下文", metadata.get("max_model_len"))
        _append_detail(rows, "并发上限", metadata.get("max_concurrency"))
        _append_detail(rows, "能力标签", metadata.get("features"))
    elif resource_type == "model_admission":
        _append_detail(rows, "默认后端", metadata.get("default_backend"))
        _append_detail(rows, "后端配置项", metadata.get("backend_env"))
        _append_detail(rows, "覆盖模型池", metadata.get("pools"))
    elif resource_type == "integration":
        manifest = metadata.get("manifest") if isinstance(metadata.get("manifest"), dict) else {}
        _append_detail(rows, "接入类别", manifest.get("category"))
        _append_detail(rows, "风险等级", manifest.get("risk_level"))
        _append_detail(rows, "支持界面", manifest.get("surfaces"))
        _append_detail(rows, "支持能力", manifest.get("capabilities"))
    elif resource_type == "solution":
        _append_detail(rows, "技术栈", metadata.get("stack"))
        _append_detail(rows, "质量分", metadata.get("quality_score"))
        _append_detail(rows, "可进入训练", _yes_no(metadata.get("training_eligible")))
    elif resource_type == "knowledge_store":
        _append_detail(rows, "知识卡数量", metadata.get("cards"))
        _append_detail(rows, "是否就绪", _yes_no(metadata.get("ready")))
        _append_detail(rows, "向量索引", metadata.get("vector_index"))
    elif resource_type == "training_dataset":
        _append_detail(rows, "样本数量", metadata.get("examples"))
        _append_detail(rows, "运行目录", metadata.get("run_dir"))
    elif resource_type == "run_manifest":
        _append_detail(rows, "任务类型", metadata.get("kind"))
        _append_detail(rows, "清单 ID", metadata.get("manifest_id"))
        _append_detail(rows, "评价分", metadata.get("evaluation_score"))
    elif resource_type == "evidence_ledger":
        _append_detail(rows, "证据条数", metadata.get("entries"))
        _append_detail(rows, "创建时间", metadata.get("created_at"))
    _append_detail(rows, "路径 / 地址", item.get("path"))
    return rows


def _resource_ui_context(registry: dict[str, Any]) -> dict[str, Any]:
    raw_counts = registry.get("summary", {}).get("by_type", {}) if isinstance(registry.get("summary"), dict) else {}
    counts = {str(key): int(value) for key, value in raw_counts.items()}
    cards: list[dict[str, Any]] = []
    for row in registry.get("resources", []):
        if not isinstance(row, dict):
            continue
        item = dict(row)
        detail_rows = _resource_detail_rows(item)
        tags = [_localise_resource_tag(tag) for tag in item.get("tags", []) if str(tag)]
        search_parts = [
            item.get("id", ""),
            item.get("name", ""),
            item.get("summary", ""),
            item.get("path", ""),
            _resource_type_label(str(item.get("type", "") or "")),
            *tags,
            *(entry["value"] for entry in detail_rows),
        ]
        item.update(
            {
                "type_label": _resource_type_label(str(item.get("type", "") or "")),
                "type_hint": _resource_type_hint(str(item.get("type", "") or "")),
                "display_tags": tags[:8],
                "detail_rows": detail_rows,
                "search_text": " ".join(str(part) for part in search_parts if str(part)).lower(),
            }
        )
        cards.append(item)
    ordered_types = [item for item in RESOURCE_TYPE_ORDER if counts.get(item)]
    ordered_types.extend(sorted(item for item in counts if item not in RESOURCE_TYPE_ORDER))
    tabs = [{"value": "all", "label": "全部", "count": int(registry.get("summary", {}).get("total", 0) or 0)}]
    tabs.extend(
        {
            "value": resource_type,
            "label": _resource_type_label(resource_type),
            "count": counts.get(resource_type, 0),
        }
        for resource_type in ordered_types
    )
    overview = [
        {"label": "分链能力", "count": counts.get("chain", 0)},
        {
            "label": "模型相关",
            "count": sum(counts.get(key, 0) for key in ("model_provider", "model_runtime", "model_pool", "model_admission")),
        },
        {"label": "方案资产", "count": counts.get("solution", 0)},
        {"label": "知识与训练", "count": counts.get("knowledge_store", 0) + counts.get("training_dataset", 0)},
    ]
    return {"cards": cards, "tabs": tabs, "overview": overview}


def _workflow_chain_label(chain_name: str) -> str:
    return WORKFLOW_CHAIN_LABELS.get(chain_name, chain_name or "未知节点")


def _innovation_ui_context(radar: dict[str, Any]) -> dict[str, Any]:
    prepared = dict(radar)
    cards: list[dict[str, Any]] = []
    for row in radar.get("innovation_cards", []):
        if not isinstance(row, dict):
            continue
        card = dict(row)
        card["horizon_label"] = HORIZON_LABELS.get(str(card.get("horizon", "") or ""), str(card.get("horizon", "") or ""))
        cards.append(card)
    workflows: list[dict[str, Any]] = []
    for row in radar.get("workflow_templates", []):
        if not isinstance(row, dict):
            continue
        template = dict(row)
        spec = template.get("spec") if isinstance(template.get("spec"), dict) else {}
        nodes = spec.get("nodes") if isinstance(spec.get("nodes"), list) else []
        template["steps"] = [
            {
                "id": str(node.get("id", "") or ""),
                "chain": str(node.get("chain", "") or ""),
                "label": _workflow_chain_label(str(node.get("chain", "") or "")),
            }
            for node in nodes
            if isinstance(node, dict)
        ]
        workflows.append(template)
    prepared["innovation_cards"] = cards
    prepared["workflow_templates"] = workflows
    return prepared


def _default_production_runtime() -> tuple[str, str]:
    provider_name = normalise_provider(os.environ.get("DEFAULT_PRODUCTION_PROVIDER", DEFAULT_PRODUCTION_PROVIDER))
    provider = resolve_llm_provider(provider_name, os.environ.get("DEFAULT_PRODUCTION_MODEL", ""))
    return provider.name, provider.model


def _default_production_timeout() -> float:
    raw = os.environ.get("DEFAULT_PRODUCTION_DEEPSEEK_TIMEOUT", "1.5").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 1.5
    return max(0.2, min(value, 60.0))


def _selected_model(provider: str, model: str, custom_model: str) -> str:
    selected = custom_model.strip() or model.strip()
    return resolve_llm_provider(provider, selected).model


def _selected_runtime(mode: str, provider: str, model: str, custom_model: str) -> tuple[str, str]:
    if mode == "local_production":
        provider_name = normalise_provider(provider)
        if str(provider or "").strip() and provider_name in ALLOWED_PROVIDERS:
            return provider_name, _selected_model(provider_name, model, custom_model)
        return _default_production_runtime()
    provider_name = _normalise_provider(provider)
    return provider_name, _selected_model(provider_name, model, custom_model)


def _checkbox_enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _safe_next(value: str | None) -> str:
    nxt = str(value or "").strip()
    if not nxt.startswith("/") or nxt.startswith("//"):
        return url_for("index")
    return nxt


def _build_config(mode: str, *, events: bool, provider: str, model: str) -> AppConfig:
    cfg = AppConfig.from_env()
    llm_provider = normalise_provider(provider or cfg.llm_provider)
    planner_model = model if mode == "llm" else cfg.planner_model
    return replace(
        cfg,
        event_log=events,
        llm_provider=llm_provider,
        brain_model=model,
        planner_model=planner_model,
        planner_use_llm=(mode == "llm"),
        max_agent_iterations=min(max(int(cfg.max_agent_iterations), 8), 48),
    )


def _build_brain(mode: str, workspace: Path, prompts_dir: Path, cfg: AppConfig) -> AgentBrain:
    if mode == "local_production":
        provider = resolve_llm_provider(cfg.llm_provider, cfg.brain_model)
        primary = OpenAIBrain(
            prompts_dir,
            model=provider.model,
            provider=provider.name,
            client_timeout=_default_production_timeout(),
        )
        return DefaultProductionBrain(primary, OfflineProductBrain(workspace))
    provider = resolve_llm_provider(cfg.llm_provider, cfg.brain_model)
    if not provider.has_api_key:
        raise RuntimeError(f"{provider.api_key_env} is required for {provider.label} modes")
    return OpenAIBrain(prompts_dir, model=provider.model, provider=provider.name)


def _safe_goal(raw: str) -> str:
    goal = raw.strip()
    return goal or DEFAULT_GOAL


def _safe_improvement_goal(raw: str) -> str:
    goal = raw.strip()
    if not goal:
        abort(400)
    return goal[:2000]


def _resolve_run_workspace(runs_root: Path, run_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", run_id):
        abort(404)
    root = runs_root.resolve()
    workspace = (root / run_id).resolve()
    if not workspace.is_relative_to(root) or not workspace.exists():
        abort(404)
    return workspace


def _resolve_run_file(workspace: Path, file_path: str) -> Path:
    if _is_internal_file(file_path):
        abort(404)
    target = (workspace / file_path).resolve()
    if not target.is_relative_to(workspace) or not target.is_file():
        abort(404)
    return target


def _load_state(workspace: Path) -> ProjectState | None:
    state_path = workspace / ".agent_state.json"
    if not state_path.exists():
        return None
    try:
        return ProjectState.load(state_path)
    except (OSError, ValueError):
        return None


def _save_run_meta(
    workspace: Path,
    *,
    goal: str,
    mode: str,
    provider: str,
    model: str,
    source_run: str = "",
    improvement_goal: str = "",
    base_goal: str = "",
    owner_user_id: str = "",
) -> None:
    meta = {
        "goal": goal,
        "mode": mode,
        "provider": provider,
        "model": model,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if owner_user_id:
        meta["owner_user_id"] = owner_user_id
    if source_run:
        meta["source_run"] = source_run
    if improvement_goal:
        meta["improvement_goal"] = improvement_goal
    if base_goal:
        meta["base_goal"] = base_goal
    try:
        (workspace / ".agent_ui.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return


def _load_run_meta(workspace: Path) -> dict[str, str]:
    try:
        raw = json.loads((workspace / ".agent_ui.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def _find_sandbox_preview(workspace: Path) -> str | None:
    try:
        manifest = json.loads((workspace / "sandbox_manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(manifest, dict) or manifest.get("type") not in {"frontend_sandbox", "static_preview"}:
        return None
    entrypoint = str(manifest.get("entrypoint", "frontend/index.html"))
    if entrypoint not in ("frontend/index.html", "index.html", "preview/index.html"):
        return None
    target = (workspace / entrypoint).resolve()
    if target.is_file() and target.is_relative_to(workspace):
        return entrypoint
    return None


def _find_solution_backup(workspace: Path) -> str | None:
    for rel in ("docs/SOLUTION_BACKUP.md", "solution_manifest.json"):
        target = (workspace / rel).resolve()
        if target.is_file() and target.is_relative_to(workspace):
            return rel
    return None


def _is_internal_file(rel: str) -> bool:
    parts = rel.split("/")
    if not parts:
        return True
    return (
        parts[0].startswith(".agent_")
        or rel.startswith(".git/")
        or "__pycache__" in parts
        or ".pytest_cache" in parts
    )


def _list_run_files(workspace: Path) -> list[str]:
    out: list[str] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(workspace).as_posix()
        if _is_internal_file(rel):
            continue
        out.append(rel)
    return out


def _is_downloadable_artifact(rel: str) -> bool:
    return not _is_internal_file(rel)


def _iter_downloadable_files(workspace: Path) -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for rel in _list_run_files(workspace):
        if not _is_downloadable_artifact(rel):
            continue
        path = _resolve_run_file(workspace, rel)
        out.append((path, rel))
    return out


def _copy_artifacts_for_improvement(source: Path, target: Path) -> int:
    copied = 0
    target_root = target.resolve()
    for path, rel in _iter_downloadable_files(source):
        dest = (target_root / rel).resolve()
        if not dest.is_relative_to(target_root):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        copied += 1
    return copied


def _build_improvement_goal(*, base_goal: str, source_run: str, improvement_goal: str) -> str:
    return f"""基于上一版软件方案继续改进，不要从零开始。

上一版 run:
{source_run}

上一版原始需求:
{base_goal}

本次改进要求:
{improvement_goal}

生产要求:
- 保留上一版已有业务场景、数据模型、CRUD、文档、测试和预览。
- 优先做增量改进，能复用就复用，不能覆盖掉与改进无关的成熟产物。
- 如果是管理系统，继续保持产品规格、API 契约、数据库设计、测试和交付清单。
- 产出必须仍然能通过结果页成熟度、ZIP 下载和沙盒预览验收。
"""


def _write_improvement_context(
    workspace: Path,
    *,
    source_run: str,
    base_goal: str,
    improvement_goal: str,
    copied_count: int,
) -> None:
    docs = workspace / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    text = f"""# Improvement Request

## Source Run

`{source_run}`

## Base Goal

```text
{base_goal}
```

## Improvement Goal

```text
{improvement_goal}
```

## Iteration Notes

- Copied user artifact files from source run: `{copied_count}`.
- Internal `.agent_*` state/event/session files were not copied.
- This run should be treated as a second production iteration over the previous solution.
"""
    (docs / "IMPROVEMENT_REQUEST.md").write_text(text, encoding="utf-8")


def _build_zip_response(workspace: Path, run_id: str):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, rel in _iter_downloadable_files(workspace):
            zf.write(path, arcname=rel)
        if not zf.namelist():
            zf.writestr("README.txt", "No downloadable artifacts were generated.\n")
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{run_id}.zip",
    )


def _sandbox_csp() -> str:
    return "; ".join(
        [
            "default-src 'none'",
            "script-src 'unsafe-inline'",
            "style-src 'unsafe-inline'",
            "img-src data: blob:",
            "font-src data:",
            "media-src data: blob:",
            "connect-src 'none'",
            "form-action 'none'",
            "object-src 'none'",
            "base-uri 'none'",
            "frame-ancestors 'self'",
        ]
    )


def _build_preview_response(workspace: Path) -> Response:
    rel = _find_sandbox_preview(workspace)
    if not rel:
        abort(404)
    target = _resolve_run_file(workspace, rel)
    html = target.read_text(encoding="utf-8", errors="replace")
    resp = Response(html, mimetype="text/html; charset=utf-8")
    resp.headers["Content-Security-Policy"] = _sandbox_csp()
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _choose_preview_file(files: list[str]) -> str | None:
    for preferred in ("README.md", "preview/index.html", "frontend/index.html", "app.py", "main.py"):
        if preferred in files:
            return preferred
    for file in files:
        if file.endswith((".py", ".md", ".txt", ".json", ".jsonl")):
            return file
    return files[0] if files else None


def _read_preview(workspace: Path, file_path: str | None) -> tuple[str, str]:
    if not file_path:
        return "预览", ""
    target = _resolve_run_file(workspace, file_path)
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return file_path, f"Could not read preview: {exc}"
    if len(text) > 12000:
        text = text[:12000] + "\n...[truncated]"
    return file_path, text


def _display_text(value: str) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    question_count = text.count("?")
    if question_count >= 8 and question_count / max(len(text), 1) > 0.55:
        return "改进说明已记录，但旧运行的文本编码不可读"
    return text[:220]


def _safe_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _accepted_solution_for_run(runs_root: Path, workspace: Path) -> dict[str, Any]:
    library_root = runs_root / "solution_library"
    if not library_root.exists():
        return {}
    target = str(workspace.resolve())
    for manifest_path in sorted(library_root.glob("*/solution_manifest.json")):
        raw = _safe_json(manifest_path)
        if not raw or not is_solution_library_ready(raw):
            continue
        manifest = normalise_solution_manifest(raw)
        source_run = str(manifest.get("source_run", "") or "")
        try:
            same_run = bool(source_run) and str(Path(source_run).resolve()) == target
        except OSError:
            same_run = False
        if same_run:
            return {
                "manifest_path": str(manifest_path),
                "accepted_at": str(manifest.get("accepted_at", "")),
                "accepted_by": str(manifest.get("accepted_by", "")),
            }
    return {}


def _render_run_page(
    *,
    runs_root: Path,
    run_id: str,
    workspace: Path,
    mode: str,
    user: Any,
    provider: str = "openai",
    model: str = "",
    error: str = "",
    status_code: int = 200,
) -> tuple[str, int]:
    mode = _normalise_mode(mode)
    state = _load_state(workspace)
    meta = _load_run_meta(workspace)
    files = _list_run_files(workspace)
    progress = state.progress if state else ("failed" if error else "created")
    stage = state.current_stage if state else ""
    maturity = build_maturity_report(files, progress, mode)
    preview_file = _choose_preview_file(files)
    preview_title, preview = _read_preview(workspace, preview_file)
    preview_rel = _find_sandbox_preview(workspace)
    preview_url = url_for("preview_run", run_id=run_id) if preview_rel else ""
    solution_backup_rel = _find_solution_backup(workspace)
    solution_backup_url = (
        url_for("run_file", run_id=run_id, file_path=solution_backup_rel)
        if solution_backup_rel
        else ""
    )
    file_links = [
        {"path": path, "url": url_for("run_file", run_id=run_id, file_path=path)}
        for path in files
    ]
    accepted_solution = _accepted_solution_for_run(runs_root, workspace)
    html = render_template_string(
        RESULT_TEMPLATE,
        css=CSS,
        run_id=run_id,
        mode=_display_mode(mode),
        mode_value=mode,
        provider=provider,
        model=model,
        progress=progress,
        stage=stage,
        workspace=str(workspace),
        error=error,
        files=file_links,
        maturity=maturity,
        preview_title=preview_title,
        preview=preview,
        preview_url=preview_url,
        solution_backup_url=solution_backup_url,
        runs_root=str(runs_root),
        source_run=meta.get("source_run", ""),
        improvement_goal=meta.get("improvement_goal", ""),
        display_improvement_goal=_display_text(meta.get("improvement_goal", "")),
        accepted_solution=accepted_solution,
        current_user=user,
    )
    return html, status_code


def create_app(
    runs_root: Path | None = None,
    prompts_dir: Path | None = None,
) -> Flask:
    root = (runs_root or _default_runs_root()).resolve()
    prompts = (prompts_dir or _prompts_dir()).resolve()
    app = Flask(__name__)
    app.config["RUNS_ROOT"] = root
    app.config["PROMPTS_DIR"] = prompts
    app.secret_key = os.environ.get("AGENT_UI_SECRET_KEY", "").strip() or secrets.token_hex(32)
    auth_store = LocalAuthStore(root / ".agent_users.json")
    admission_controller = PoolAdmissionController()
    job_queue = ProductTaskQueue(_process_simple_job)
    root.mkdir(parents=True, exist_ok=True)

    def _auth_store() -> LocalAuthStore:
        return auth_store

    def _current_user():
        return current_user(auth_store)

    def _require_run_access(workspace: Path):
        user = _current_user()
        if not can_access_run(_load_run_meta(workspace), user):
            abort(404)
        return user

    def _request_payload() -> dict[str, Any]:
        data = request.get_json(silent=True)
        if isinstance(data, dict):
            return data
        return dict(request.form.items())

    def _payload_roots(payload: dict[str, Any]) -> tuple[Path, ...]:
        roots = payload.get("roots", ())
        if isinstance(roots, str):
            roots = [roots]
        if not isinstance(roots, list):
            return ()
        return tuple(Path(str(x)) for x in roots if str(x).strip())

    def _payload_path(payload: dict[str, Any], key: str, *, base: Path) -> Path | None:
        raw = str(payload.get(key, "") or "").strip()
        if not raw:
            return None
        path = Path(raw)
        return path.resolve() if path.is_absolute() else (base / path).resolve()

    @app.get("/healthz")
    def healthz() -> Response:
        return jsonify({"ok": True, "runs_root": str(root), "has_users": auth_store.has_users()})

    @app.get("/login")
    def login() -> str | Response:
        if _current_user():
            return redirect(url_for("index"))
        return render_template_string(
            AUTH_TEMPLATE,
            css=CSS,
            title="登录",
            mode="login",
            action=url_for("login"),
            submit="登录",
            autocomplete="current-password",
            next_url=_safe_next(request.args.get("next")),
            error="",
        )

    @app.post("/login")
    def login_submit() -> str | Response:
        user = auth_store.verify(request.form.get("username", ""), request.form.get("password", ""))
        if user:
            sign_in(user)
            return redirect(_safe_next(request.form.get("next")))
        return render_template_string(
            AUTH_TEMPLATE,
            css=CSS,
            title="登录",
            mode="login",
            action=url_for("login"),
            submit="登录",
            autocomplete="current-password",
            next_url=_safe_next(request.form.get("next")),
            error="用户名或密码错误",
        ), 401

    @app.get("/register")
    def register() -> str | Response:
        if _current_user():
            return redirect(url_for("index"))
        return render_template_string(
            AUTH_TEMPLATE,
            css=CSS,
            title="注册",
            mode="register",
            action=url_for("register"),
            submit="创建账号",
            autocomplete="new-password",
            next_url="",
            error="",
        )

    @app.post("/register")
    def register_submit() -> str | Response:
        try:
            user = auth_store.register(request.form.get("username", ""), request.form.get("password", ""))
        except ValueError as exc:
            return render_template_string(
                AUTH_TEMPLATE,
                css=CSS,
                title="注册",
                mode="register",
                action=url_for("register"),
                submit="创建账号",
                autocomplete="new-password",
                next_url="",
                error=str(exc),
            ), 400
        sign_in(user)
        return redirect(url_for("index"))

    @app.get("/logout")
    def logout() -> Response:
        sign_out()
        return redirect(url_for("login"))

    @app.get("/")
    @login_required(_auth_store)
    def index() -> str:
        return render_template_string(
            SIMPLE_PRODUCT_TEMPLATE,
            css=SIMPLE_PRODUCT_CSS,
            current_user=_current_user(),
        )

    @app.get("/api/billing")
    @login_required(_auth_store)
    def api_billing() -> Response:
        return jsonify(_billing_snapshot(root, _current_user()))

    @app.post("/api/token-plan")
    @login_required(_auth_store)
    def api_token_plan() -> Response:
        payload = _request_payload()
        prompt = str(payload.get("prompt", "") or "").strip()
        improvement = str(payload.get("improvement", "") or "").strip()
        if not prompt:
            return jsonify({"error": "bad_request", "message": "prompt is required"}), 400
        return jsonify(
            _build_product_token_plan(
                root,
                _current_user(),
                prompt=prompt,
                improvement=improvement,
                model_source=str(payload.get("model_source", "local") or "local"),
                provider=str(payload.get("provider", DEFAULT_PRODUCTION_PROVIDER) or DEFAULT_PRODUCTION_PROVIDER),
                model=str(payload.get("model", "") or ""),
            )
        )

    @app.post("/api/payment/orders")
    @login_required(_auth_store)
    def api_payment_order() -> Response:
        payload = _request_payload()
        amount = payload.get("amount_yuan", payload.get("amount", 0))
        try:
            amount_yuan = int(amount)
        except (TypeError, ValueError):
            amount_yuan = 0
        if amount_yuan <= 0:
            return jsonify({"error": "bad_request", "message": "amount_yuan must be positive"}), 400
        return jsonify(_create_payment_order(root, _current_user(), amount_yuan))

    @app.post("/api/payment/orders/<order_id>/confirm")
    @login_required(_auth_store)
    def api_payment_confirm(order_id: str) -> Response:
        result = _confirm_payment_order(root, _current_user(), order_id)
        return jsonify(result), 200 if bool(result.get("ok")) else 404

    @app.get("/api/simple-jobs")
    @login_required(_auth_store)
    def api_simple_jobs() -> Response:
        return jsonify(job_queue.snapshot())

    @app.post("/api/simple-jobs")
    @login_required(_auth_store)
    def api_simple_job_submit() -> Response:
        user = _current_user()
        require_permission(user, "run:create")
        payload = _request_payload()
        prompt = str(payload.get("prompt", "") or "").strip()
        improvement = str(payload.get("improvement", "") or "").strip()
        if not prompt:
            return jsonify({"error": "bad_request", "message": "prompt is required"}), 400
        token_plan = _build_product_token_plan(
            root,
            user,
            prompt=prompt,
            improvement=improvement,
            model_source=str(payload.get("model_source", "local") or "local"),
            provider=str(payload.get("provider", DEFAULT_PRODUCTION_PROVIDER) or DEFAULT_PRODUCTION_PROVIDER),
            model=str(payload.get("model", "") or ""),
        )
        if not bool(token_plan["admission"]["can_run"]):
            return jsonify(token_plan), 402
        if token_plan["billing_policy"]["billable"]:
            consumed = _consume_tokens(
                root,
                user,
                int(token_plan["estimate"]["estimated_total_tokens"]),
                reason="product_preview_job_estimate",
                metadata={
                    "provider": token_plan["provider"],
                    "model": token_plan["model"],
                    "mode": "api",
                },
            )
            if not bool(consumed.get("ok")):
                return jsonify(consumed), 402
            token_plan["billing"] = consumed["billing"]
            token_plan["billing_event"] = consumed.get("event")
        job = job_queue.submit(
            {
                **payload,
                "prompt": prompt,
                "improvement": improvement,
                "model_source": token_plan["model_source"],
                "provider": token_plan["provider"],
                "model": token_plan["model"],
                "token_estimate": token_plan["estimate"],
                "token_plan": token_plan,
            }
        )
        return jsonify(
            {
                "schema": "product_job_submission.v1",
                "job": job,
                "token_plan": token_plan,
                "notification": "已加入任务队列",
            }
        ), 202

    @app.get("/api/simple-jobs/<job_id>")
    @login_required(_auth_store)
    def api_simple_job_status(job_id: str) -> Response:
        job = job_queue.get(job_id)
        if not job:
            return jsonify({"error": "not_found", "message": "job not found"}), 404
        return jsonify(job)

    @app.post("/api/simple-preview")
    @login_required(_auth_store)
    def api_simple_preview() -> Response:
        payload = _request_payload()
        prompt = str(payload.get("prompt", "") or "").strip()
        improvement = str(payload.get("improvement", "") or "").strip()
        if not prompt:
            return jsonify({"error": "bad_request", "message": "prompt is required"}), 400
        preview = _build_simple_preview(prompt, improvement)
        preview["token_plan"] = _build_product_token_plan(
            root,
            _current_user(),
            prompt=prompt,
            improvement=improvement,
            model_source=str(payload.get("model_source", "local") or "local"),
            provider=str(payload.get("provider", DEFAULT_PRODUCTION_PROVIDER) or DEFAULT_PRODUCTION_PROVIDER),
            model=str(payload.get("model", "") or ""),
        )
        return jsonify(preview)

    @app.get("/api/simple-solutions")
    @login_required(_auth_store)
    def api_simple_solutions() -> Response:
        return jsonify({"schema": "simple_solution_catalog.v1", "solutions": _curated_solution_catalog()})

    @app.post("/api/simple-package")
    @login_required(_auth_store)
    def api_simple_package():
        user = _current_user()
        require_permission(user, "run:download")
        payload = _request_payload()
        prompt = str(payload.get("prompt", "") or "").strip()
        improvement = str(payload.get("improvement", "") or "").strip()
        title = str(payload.get("title", "") or "").strip()
        html = str(payload.get("html", "") or "")
        if not prompt:
            return jsonify({"error": "bad_request", "message": "prompt is required"}), 400
        return _build_simple_package_response(prompt, improvement, html, title)

    @app.get("/resources")
    @login_required(_auth_store)
    def resources_page() -> str:
        registry = discover_resources(root)
        resource_ui = _resource_ui_context(registry)
        return render_template_string(
            RESOURCES_TEMPLATE,
            css=CSS,
            registry=registry,
            resource_cards=resource_ui["cards"],
            resource_tabs=resource_ui["tabs"],
            resource_overview=resource_ui["overview"],
            current_user=_current_user(),
        )

    @app.get("/api/resources")
    @login_required(_auth_store)
    def api_resources() -> Response:
        return jsonify(discover_resources(root, type_filter=str(request.args.get("type", "") or "")))

    @app.get("/api/integrations")
    @login_required(_auth_store)
    def api_integrations() -> Response:
        return jsonify(list_integration_catalog(str(request.args.get("category", "") or "")))

    @app.post("/api/integrations/embed-plan")
    @login_required(_auth_store)
    def api_integration_embed_plan() -> Response:
        payload = _request_payload()
        requested = payload.get("requested_capabilities", [])
        if isinstance(requested, str):
            requested_capabilities = tuple(x.strip() for x in requested.split(",") if x.strip())
        elif isinstance(requested, list):
            requested_capabilities = tuple(str(x) for x in requested if str(x).strip())
        else:
            requested_capabilities = ()
        plan = build_integration_embed_plan(
            str(payload.get("integration_id", "") or ""),
            resource_url=str(payload.get("resource_url", "") or ""),
            mode=str(payload.get("mode", "embed_panel") or "embed_panel"),
            workspace_context=str(payload.get("workspace_context", "") or ""),
            requested_capabilities=requested_capabilities,
        )
        return jsonify(plan), 200 if bool(plan.get("admission", {}).get("embeddable")) else 400

    @app.get("/api/model-runtime")
    @login_required(_auth_store)
    def api_model_runtime() -> Response:
        provider = str(request.args.get("provider", "main_deepseek") or "main_deepseek")
        model = str(request.args.get("model", "") or "") or None
        probe = str(request.args.get("probe", "1") or "1").lower() not in {"0", "false", "no"}
        try:
            timeout = float(request.args.get("timeout", "2") or 2)
        except ValueError:
            timeout = 2.0
        return jsonify(model_runtime_status(provider, model, probe=probe, timeout=max(timeout, 0.1)))

    @app.get("/api/model-pools")
    @login_required(_auth_store)
    def api_model_pools() -> Response:
        return jsonify(list_model_pools())

    @app.post("/api/model-route-plan")
    @login_required(_auth_store)
    def api_model_route_plan() -> Response:
        payload = _request_payload()
        raw_max_output = payload.get("max_output_tokens")
        max_output_tokens = raw_max_output if isinstance(raw_max_output, int) and raw_max_output > 0 else None
        return jsonify(
            build_model_route_plan(
                _safe_goal(str(payload.get("goal", "") or "")),
                prompt=str(payload.get("prompt", "") or ""),
                max_output_tokens=max_output_tokens,
                business_type=str(payload.get("business_type", "") or ""),
                require_json=bool(payload.get("require_json", False)),
            )
        )

    @app.get("/api/model-admission/status")
    @login_required(_auth_store)
    def api_model_admission_status() -> Response:
        return jsonify(admission_controller.snapshot())

    @app.post("/api/model-admission/acquire")
    @login_required(_auth_store)
    def api_model_admission_acquire() -> Response:
        payload = _request_payload()
        raw_max_output = payload.get("max_output_tokens")
        max_output_tokens = raw_max_output if isinstance(raw_max_output, int) and raw_max_output > 0 else None
        raw_ttl = payload.get("lease_ttl_s")
        lease_ttl_s = raw_ttl if isinstance(raw_ttl, (int, float)) and raw_ttl > 0 else None
        admission = admission_controller.acquire(
            _safe_goal(str(payload.get("goal", "") or "")),
            prompt=str(payload.get("prompt", "") or ""),
            max_output_tokens=max_output_tokens,
            business_type=str(payload.get("business_type", "") or ""),
            require_json=bool(payload.get("require_json", False)),
            idempotency_key=str(payload.get("idempotency_key", "") or ""),
            lease_ttl_s=lease_ttl_s,
            metadata={"source": "product_ui"},
        )
        return jsonify(admission), int(admission.get("backpressure", {}).get("http_status", 200))

    @app.post("/api/model-admission/release")
    @login_required(_auth_store)
    def api_model_admission_release() -> Response:
        payload = _request_payload()
        return jsonify(admission_controller.release(str(payload.get("lease_id", "") or "")))

    @app.post("/api/model-admission/renew")
    @login_required(_auth_store)
    def api_model_admission_renew() -> Response:
        payload = _request_payload()
        raw_ttl = payload.get("lease_ttl_s")
        lease_ttl_s = raw_ttl if isinstance(raw_ttl, (int, float)) and raw_ttl > 0 else None
        return jsonify(
            admission_controller.renew(
                str(payload.get("lease_id", "") or ""),
                lease_ttl_s=lease_ttl_s,
            )
        )

    @app.post("/api/enterprise-stack")
    @login_required(_auth_store)
    def api_enterprise_stack() -> Response:
        payload = _request_payload()
        return jsonify(
            build_enterprise_stack_plan(
                _safe_goal(str(payload.get("goal", "") or "")),
                root,
                scale=str(payload.get("scale", "") or ""),
                regulated=bool(payload.get("regulated", False)),
                provider=str(payload.get("provider", "main_deepseek") or "main_deepseek"),
            )
        )

    @app.post("/api/industrial-maturity")
    @login_required(_auth_store)
    def api_industrial_maturity() -> Response:
        payload = _request_payload()
        return jsonify(
            build_industrial_maturity_plan(
                _safe_goal(str(payload.get("goal", "") or "")),
                root,
                scale=str(payload.get("scale", "listed") or "listed"),
                regulated=bool(payload.get("regulated", True)),
                provider=str(payload.get("provider", "main_deepseek") or "main_deepseek"),
            )
        )

    @app.get("/api/enterprise-readiness")
    @login_required(_auth_store)
    def api_enterprise_readiness() -> Response:
        return jsonify(build_enterprise_readiness_report(root))

    @app.get("/innovation")
    @login_required(_auth_store)
    def innovation_page() -> str:
        radar = _innovation_ui_context(build_innovation_radar(root))
        return render_template_string(
            INNOVATION_TEMPLATE,
            css=CSS,
            radar=radar,
            current_user=_current_user(),
        )

    @app.get("/api/innovation")
    @login_required(_auth_store)
    def api_innovation() -> Response:
        return jsonify(build_innovation_radar(root))

    @app.route("/intent", methods=["GET", "POST"])
    @login_required(_auth_store)
    def intent_page() -> str:
        goal = DEFAULT_GOAL
        compilation = None
        workflow_json = ""
        if request.method == "POST":
            goal = _safe_goal(request.form.get("goal", ""))
            compilation = compile_intent(goal, root, roots=(root,))
            workflow_json = json.dumps(compilation["workflow"], ensure_ascii=False, indent=2)
        return render_template_string(
            INTENT_TEMPLATE,
            css=CSS,
            goal=goal,
            compilation=compilation,
            workflow_json=workflow_json,
            current_user=_current_user(),
        )

    @app.post("/api/intent/compile")
    @login_required(_auth_store)
    def api_intent_compile() -> Response:
        payload = _request_payload()
        goal = _safe_goal(str(payload.get("goal", "") or ""))
        return jsonify(compile_intent(goal, root, roots=_payload_roots(payload)))

    @app.post("/api/workflow/dry-run")
    @login_required(_auth_store)
    def api_workflow_dry_run() -> Response:
        payload = _request_payload()
        spec = payload.get("spec") if isinstance(payload.get("spec"), dict) else {}
        return jsonify(dry_run_workflow(spec, root))

    @app.post("/api/evidence-ledger")
    @login_required(_auth_store)
    def api_evidence_ledger() -> Response:
        payload = _request_payload()
        ledger = build_evidence_ledger(
            root,
            roots=_payload_roots(payload),
            write_path=_payload_path(payload, "output_path", base=root),
        )
        return jsonify(ledger)

    @app.post("/runs/<run_id>/publish-solution")
    @login_required(_auth_store)
    def publish_run_solution(run_id: str) -> Response:
        workspace = _resolve_run_workspace(root, run_id)
        user = _require_run_access(workspace)
        require_permission(user, "run:improve")
        payload = _request_payload()
        result = publish_solution_from_run(
            workspace,
            output_dir=_payload_path(payload, "output_dir", base=root) or (root / "solution_library"),
            title=str(payload.get("title", "") or ""),
            source_type=str(payload.get("source_type", "product_run") or "product_run"),
            accepted_by=user.username if user else "",
            acceptance_note=str(payload.get("acceptance_note", "") or ""),
        )
        if request.is_json:
            return jsonify(result)
        return redirect(url_for("show_run", run_id=run_id))

    @app.post("/run")
    @login_required(_auth_store)
    def run_product() -> Response | tuple[str, int]:
        user = _current_user()
        require_permission(user, "run:create")
        goal = _safe_goal(request.form.get("goal", ""))
        mode = _normalise_mode(request.form.get("mode", "local_production"))
        provider_name, model = _selected_runtime(
            mode,
            request.form.get("provider", "openai"),
            request.form.get("model", ""),
            request.form.get("custom_model", ""),
        )
        events = _checkbox_enabled(request.form.get("events"))
        run_id = _build_run_id(goal)
        workspace = (root / run_id).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        _save_run_meta(workspace, goal=goal, mode=mode, provider=provider_name, model=model, owner_user_id=user.id if user else "")
        cfg = _build_config(mode, events=events, provider=provider_name, model=model)
        try:
            brain = _build_brain(mode, workspace, prompts, cfg)
            run_agent_loop(goal, workspace, prompts, brain, config=cfg, resume=False)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            return _render_run_page(
                runs_root=root,
                run_id=run_id,
                workspace=workspace,
                mode=mode,
                user=user,
                provider=provider_name,
                model=model,
                error=error,
                status_code=400,
            )
        return redirect(url_for("show_run", run_id=run_id))

    @app.post("/runs/<run_id>/improve")
    @login_required(_auth_store)
    def improve_run(run_id: str) -> Response | tuple[str, int]:
        source_workspace = _resolve_run_workspace(root, run_id)
        user = _require_run_access(source_workspace)
        require_permission(user, "run:improve")
        source_meta = _load_run_meta(source_workspace)
        improvement_goal = _safe_improvement_goal(request.form.get("improvement_goal", ""))
        base_goal = source_meta.get("base_goal") or source_meta.get("goal") or DEFAULT_GOAL
        mode = _normalise_mode(source_meta.get("mode") or request.form.get("mode", "local_production"))
        if mode == "local_production":
            provider_name, model = _selected_runtime(mode, "", "", "")
        else:
            provider_name, model = _selected_runtime(
                mode,
                source_meta.get("provider") or request.form.get("provider", "openai"),
                source_meta.get("model") or request.form.get("model", ""),
                "",
            )
        events = _checkbox_enabled(request.form.get("events"))
        goal = _build_improvement_goal(
            base_goal=base_goal,
            source_run=run_id,
            improvement_goal=improvement_goal,
        )
        new_run_id = _build_run_id(f"{base_goal} improve {improvement_goal}")
        workspace = (root / new_run_id).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        copied_count = _copy_artifacts_for_improvement(source_workspace, workspace)
        _write_improvement_context(
            workspace,
            source_run=run_id,
            base_goal=base_goal,
            improvement_goal=improvement_goal,
            copied_count=copied_count,
        )
        _save_run_meta(
            workspace,
            goal=goal,
            mode=mode,
            provider=provider_name,
            model=model,
            source_run=run_id,
            improvement_goal=improvement_goal,
            base_goal=base_goal,
            owner_user_id=user.id if user else "",
        )
        cfg = _build_config(mode, events=events, provider=provider_name, model=model)
        try:
            brain = _build_brain(mode, workspace, prompts, cfg)
            run_agent_loop(goal, workspace, prompts, brain, config=cfg, resume=False)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            return _render_run_page(
                runs_root=root,
                run_id=new_run_id,
                workspace=workspace,
                mode=mode,
                user=user,
                provider=provider_name,
                model=model,
                error=error,
                status_code=400,
            )
        return redirect(url_for("show_run", run_id=new_run_id))

    @app.get("/runs/<run_id>")
    @login_required(_auth_store)
    def show_run(run_id: str) -> tuple[str, int]:
        workspace = _resolve_run_workspace(root, run_id)
        user = _require_run_access(workspace)
        meta = _load_run_meta(workspace)
        return _render_run_page(
            runs_root=root,
            run_id=run_id,
            workspace=workspace,
            mode=meta.get("mode", "saved"),
            user=user,
            provider=meta.get("provider", ""),
            model=meta.get("model", ""),
        )

    @app.get("/runs/<run_id>/files/<path:file_path>")
    @login_required(_auth_store)
    def run_file(run_id: str, file_path: str) -> Response:
        workspace = _resolve_run_workspace(root, run_id)
        _require_run_access(workspace)
        target = _resolve_run_file(workspace, file_path)
        text = target.read_text(encoding="utf-8", errors="replace")
        return Response(text, mimetype="text/plain; charset=utf-8")

    @app.get("/runs/<run_id>/download")
    @login_required(_auth_store)
    def download_run(run_id: str):
        workspace = _resolve_run_workspace(root, run_id)
        user = _require_run_access(workspace)
        require_permission(user, "run:download")
        return _build_zip_response(workspace, run_id)

    @app.get("/runs/<run_id>/preview")
    @login_required(_auth_store)
    def preview_run(run_id: str) -> Response:
        workspace = _resolve_run_workspace(root, run_id)
        _require_run_access(workspace)
        return _build_preview_response(workspace)

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Software Production Agent product UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--runs-root", default="./product_runs")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    configure_logging(verbose=args.verbose)
    app = create_app(runs_root=Path(args.runs_root).resolve())
    app.run(host=args.host, port=max(int(args.port), 1), debug=args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
