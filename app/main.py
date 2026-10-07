"""Minimal Flask service used to demo a GitHub Actions + ArgoCD DevSecOps pipeline."""

import os

from flask import Flask, jsonify
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

APP_VERSION = os.getenv("APP_VERSION", "dev")
REQUESTS = Counter("app_requests_total", "Total HTTP requests", ["endpoint"])


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        REQUESTS.labels(endpoint="/").inc()
        return jsonify(message="Hello from my-kubernetes-cluster/sample-code-files", version=APP_VERSION)

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok")

    @app.get("/readyz")
    def readyz():
        return jsonify(status="ready")

    @app.get("/metrics")
    def metrics():
        return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}

    return app


app = create_app()

if __name__ == "__main__":  # pragma: no cover
    app.run(host="127.0.0.1", port=8080)  # local dev only; gunicorn serves in containers
