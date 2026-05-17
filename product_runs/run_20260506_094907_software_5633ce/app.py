from __future__ import annotations

import sys
from flask import Flask, jsonify

app = Flask(__name__)
PRODUCT_GOAL = '图书管理系统'


@app.get("/")
def index():
    return """
    <main style="font-family: system-ui; max-width: 760px; margin: 48px auto;">
      <h1>Offline Product Prototype</h1>
      <p>This local scaffold was generated without calling an LLM.</p>
      <p><a href="/api/health">Health</a> · <a href="/api/spec">Spec</a></p>
    </main>
    """


@app.get("/hello")
def hello():
    return "ok"


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "offline-product-prototype"})


@app.get("/api/spec")
def spec():
    return jsonify({
        "goal": PRODUCT_GOAL,
        "mode": "offline-template",
        "routes": ["/", "/hello", "/api/health", "/api/spec"],
    })


def selftest() -> int:
    client = app.test_client()
    checks = [
        client.get("/hello").status_code == 200,
        client.get("/api/health").json == {"ok": True, "service": "offline-product-prototype"},
        client.get("/api/spec").status_code == 200,
    ]
    print("offline flask prototype", "ok" if all(checks) else "failed")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        raise SystemExit(selftest())
    app.run(host="127.0.0.1", port=5055, debug=False)
