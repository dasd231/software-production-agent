# Production Deployment

This deployment path is deliberately split from the Flask local UI.

- Production platform API: FastAPI/ASGI + Gunicorn/Uvicorn.
- Model serving: vLLM or SGLang behind an OpenAI-compatible model gateway.
- Flask: local operator/product UI only, not the production serving plane.
- Ollama: developer convenience only; do not use as the production model serving plane for this project.

## Local Container Smoke

```bash
docker compose -f deploy/production/docker-compose.yml up --build platform-api
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/readyz
```

Start the vLLM model service profile:

```bash
export VLLM_IMAGE=vllm/vllm-openai:v0.8.5
docker compose -f deploy/production/docker-compose.yml --profile model up --build
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8080/api/model-runtime?probe=true
```

## Kubernetes Baseline

```bash
kubectl apply -f deploy/production/k8s/namespace.yaml
kubectl apply -f deploy/production/k8s/platform-api.yaml
kubectl apply -f deploy/production/k8s/model-vllm.yaml
kubectl apply -f deploy/production/k8s/hpa.yaml
kubectl apply -f deploy/production/k8s/pdb.yaml
kubectl apply -f deploy/production/k8s/network-policy.yaml
```

Before real production:

- Replace `registry.example.com/software-production-agent/platform-api:0.1.0`.
- Replace `platform-api-token` with a real secret.
- Pin the vLLM image tag and model id.
- Set GPU node selectors/tolerations for the model runtime.
- Add ingress, TLS, WAF/API gateway and OpenTelemetry collector.
- Add Argo Rollouts or an equivalent canary/blue-green controller.

## Readiness Gate

```json
{"type":"action","action":"enterprise_readiness_check","args":{}}
```

CI also runs `agent.enterprise.readiness.build_enterprise_readiness_report()` and blocks release when critical/high checks fail.

## Runtime Boundaries

```text
client / internal portal
  -> API gateway / ingress
  -> platform-api FastAPI ASGI service
  -> protocol / executor / resources / maturity APIs
  -> model gateway
  -> vLLM or SGLang model runtime
```

The model runtime must expose OpenAI-compatible endpoints:

- `/v1/chat/completions`
- `/v1/models`
- `/health`

`model_runtime_status` probes those endpoints and keeps the Agent code independent from vLLM/SGLang internals.
