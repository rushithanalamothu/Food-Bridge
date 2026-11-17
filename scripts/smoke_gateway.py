"""Verify static serving, gateway readiness, TLS and internal-route isolation."""

import argparse
import json
import ssl
import time
from urllib.parse import urlsplit

import httpx


def verify(base_url, ca_file=None, allow_local_http=False):
    url = urlsplit(base_url)
    if url.scheme != "https" and not (
        allow_local_http and url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1"}
    ):
        raise ValueError("HTTPS required; local HTTP is an explicit test-only option")
    if url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}:
        raise ValueError("Supply a public origin, not credentials or a path")
    context = ssl.create_default_context(cafile=ca_file)
    with httpx.Client(base_url=base_url.rstrip("/"), verify=context, timeout=8) as client:
        for attempt in range(10):
            try:
                root = client.get("/")
                root.raise_for_status()
                break
            except httpx.HTTPError:
                if attempt == 9:
                    raise
                time.sleep(1)
        if "/assets/" not in root.text or "/@vite/client" in root.text:
            raise ValueError("Gateway is not serving a production frontend build")
        readiness = client.get("/api/v1/health/ready")
        readiness.raise_for_status()
        if readiness.json().get("status") != "ready":
            raise ValueError("Gateway dependencies are not ready")
        if client.get("/internal/metrics").status_code != 404:
            raise ValueError("Internal monitoring route must be blocked at the public gateway")
    return {
        "production_static_assets": True,
        "api_proxy_ready": True,
        "internal_metrics_blocked": True,
        "tls_verified": url.scheme == "https",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--ca-file")
    parser.add_argument("--allow-local-http", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.base_url, args.ca_file, args.allow_local_http)))
