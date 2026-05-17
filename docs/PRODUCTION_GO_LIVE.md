# Production Go-Live Plan

目标：把平台承载和模型承载从开发模式切到企业上线模式，避免用 Flask 或 Ollama 承担生产流量。

## 生产边界

```text
Ingress / API Gateway
  -> platform-api FastAPI ASGI service
  -> protocol / executor / registry / maturity APIs
  -> model admission controller
  -> model gateway / queue worker
  -> vLLM or SGLang model runtime
```

### 不用于生产承载

- Flask：只保留本地产品 UI，不作为生产 API 面。
- Ollama：只适合个人开发便利，不作为本项目 100+ 终端和企业灰度承载。

### 用于生产承载

- Platform API：FastAPI + Gunicorn + UvicornWorker。
- Model Runtime：vLLM 优先，SGLang 用于结构化 Agent / prefix 复用专项场景。
- Model Boundary：OpenAI-compatible `/v1` API。
- Deployment：Kubernetes + HPA，后续接 Argo Rollouts。

## 已落地文件

- `agent/platform/api.py`：生产 ASGI API。
- `deploy/production/Dockerfile.platform`：平台 API 容器。
- `deploy/production/docker-compose.yml`：平台 API + vLLM profile。
- `deploy/production/k8s/platform-api.yaml`：平台 Deployment/Service/PVC。
- `deploy/production/k8s/model-vllm.yaml`：vLLM GPU Deployment/Service。
- `deploy/production/k8s/model-pools.yaml`：short/long vLLM 模型池 Deployment/Service。
- `deploy/production/k8s/hpa.yaml`：平台 API HPA。
- `deploy/production/k8s/pdb.yaml`：平台 API PodDisruptionBudget。
- `deploy/production/k8s/network-policy.yaml`：平台/API 与模型服务网络边界。
- `.github/workflows/ci.yml`：pytest、编译和企业 readiness 静态门禁。

## 模型访问承载

必须经过 model gateway 思路：

- 统一 base_url：`MAIN_DEEPSEEK_BASE_URL=http://model-vllm:8000/v1`
- 统一模型允许列表。
- 统一鉴权、限流、审计、prompt/response sampling。
- 短上下文、长上下文、Agent JSON 任务拆模型池。
- `model_route_plan` 先做 token 估算、业务类型识别、池子选择和准入；真正模型调用只消费该计划。
- `model_admission` 发放 per-pool lease；池满返回 429/backpressure，不让请求失控排队。
- 用 `model_runtime_status` 探测 `/health` 与 `/v1/models`。

## 平台承载

平台 API 提供：

- `/healthz`
- `/readyz`
- `/api/resources`
- `/api/model-runtime`
- `/api/model-pools`
- `/api/model-route-plan`
- `/api/model-admission/status`
- `/api/model-admission/acquire`
- `/api/model-admission/release`
- `/api/intent/compile`
- `/api/workflow/dry-run`
- `/api/enterprise-stack`
- `/api/industrial-maturity`
- `/api/evidence-ledger`

控制面 API 可用 `AGENT_PLATFORM_API_TOKEN` 开启 Bearer Token。

## 上线前门禁

1. 镜像使用固定 tag，不使用 `latest`。
2. vLLM/SGLang 模型服务单独 GPU 节点池。
3. API gateway/Ingress 开 TLS、限流、WAF 或等价策略。
4. 平台 API 和模型服务都有 readiness/liveness。
5. HPA 先覆盖平台 API；模型服务扩缩容按 queue depth、TTFT、GPU utilization 接入。
6. 所有模型请求必须先 acquire lease，结束 release；超时 lease 自动回收。
7. 多副本生产把 `MODEL_ADMISSION_BACKEND=local` 替换成 Redis/队列实现，保证跨 worker 硬并发。
8. CI 必须运行全量 pytest、SAST/secret scan、SBOM 和容器扫描。
9. 发布使用 canary 或 blue-green，禁止直接覆盖生产。

## 快速验证

```bash
python -m agent.platform.api --host 0.0.0.0 --port 8080
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/readyz
```

```bash
docker compose -f deploy/production/docker-compose.yml up --build platform-api
export VLLM_IMAGE=vllm/vllm-openai:v0.8.5
docker compose -f deploy/production/docker-compose.yml --profile model up --build
```

```bash
kubectl apply -f deploy/production/k8s/namespace.yaml
kubectl apply -f deploy/production/k8s/platform-api.yaml
kubectl apply -f deploy/production/k8s/model-vllm.yaml
kubectl apply -f deploy/production/k8s/model-pools.yaml
kubectl apply -f deploy/production/k8s/hpa.yaml
kubectl apply -f deploy/production/k8s/pdb.yaml
kubectl apply -f deploy/production/k8s/network-policy.yaml
```

## 企业 Readiness 门禁

```json
{"type":"action","action":"enterprise_readiness_check","args":{}}
```

该门禁检查：

- FastAPI/ASGI 控制面。
- Gunicorn/Uvicorn 进程模型。
- 生产部署不包含 Flask/Ollama。
- vLLM/OpenAI-compatible 模型服务。
- Token Estimator / Model Router / short-long-agent-training 池子准入。
- Model Admission / per-pool lease / backpressure。
- 镜像不使用 `latest`。
- K8s probes/resources。
- HPA、PDB、NetworkPolicy。
- CI 和上线文档。

## 参考

- FastAPI deployment: <https://fastapi.tiangolo.com/deployment/>
- Uvicorn deployment: <https://www.uvicorn.org/deployment/>
- vLLM serving docs: <https://docs.vllm.ai/>
- SGLang docs: <https://docs.sglang.ai/>
- Kubernetes HPA: <https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/>
