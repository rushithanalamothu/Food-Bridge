"""Generate private self-hosted deployment configuration; never uploads or starts services."""

import argparse
import json
import re
import secrets
from pathlib import Path


def initialize(directory, domain, auth_domain, backend_image, web_image):
    for value in (domain, auth_domain):
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}", value):
            raise ValueError("Supply DNS hostnames, not URLs")
    for value in (backend_image, web_image):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:@-]+", value):
            raise ValueError("Invalid image reference")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (directory / "runtime.env").exists():
        raise ValueError("Configuration already exists; refusing to replace credentials")
    database, password, admin, metrics, redis_password = (
        secrets.token_urlsafe(32) for _ in range(5)
    )
    values = {
        "FOODBRIDGE_ENVIRONMENT": "production",
        "FOODBRIDGE_PUBLIC_URL": f"https://{domain}",
        "FOODBRIDGE_DOMAIN": domain,
        "FOODBRIDGE_AUTH_DOMAIN": auth_domain,
        "FOODBRIDGE_BACKEND_IMAGE": backend_image,
        "FOODBRIDGE_WEB_IMAGE": web_image,
        "POSTGRES_PASSWORD": database,
        "KEYCLOAK_DB_PASSWORD": password,
        "KEYCLOAK_ADMIN_PASSWORD": admin,
        "FOODBRIDGE_DATABASE_URL": f"postgresql+psycopg://foodbridge:{database}@db:5432/foodbridge",
        "REDIS_PASSWORD": redis_password,
        "FOODBRIDGE_REDIS_URL": f"redis://:{redis_password}@redis:6379/0",
        "FOODBRIDGE_CORS_ORIGINS": json.dumps([f"https://{domain}"]),
        "FOODBRIDGE_ENABLE_LOCAL_INTAKE_DEMO": "false",
        "FOODBRIDGE_ENABLE_LOCAL_WORKFLOW_DEMO": "false",
        "FOODBRIDGE_NOTIFICATION_MODE": "disabled",
        "FOODBRIDGE_AI_PROVIDER": "rules",
        "FOODBRIDGE_BROWSER_AUTH_ENABLED": "true",
        "FOODBRIDGE_OIDC_CLIENT_ID": "foodbridge-web",
        "FOODBRIDGE_OIDC_AUDIENCE": "foodbridge-api",
        "FOODBRIDGE_OIDC_ISSUER": f"https://{auth_domain}/realms/foodbridge",
        "FOODBRIDGE_OIDC_JWKS_URL": f"https://{auth_domain}/realms/foodbridge/protocol/openid-connect/certs",
        "FOODBRIDGE_METRICS_TOKEN": metrics,
    }
    # Single quotes prevent Compose interpolation; all generated secrets are URL-safe.
    (directory / "runtime.env").write_text("".join(f"{k}='{v}'\n" for k, v in values.items()))
    (directory / "runtime.env").chmod(0o600)
    (directory / "metrics-token").write_text(metrics)
    # Prometheus runs unprivileged; the containing directory restricts host access.
    (directory / "metrics-token").chmod(0o644)
    realm = json.loads(Path("deploy/keycloak/local-realm.json").read_text())
    realm["sslRequired"] = "external"
    realm["users"] = []
    realm["clients"][0]["redirectUris"] = [f"https://{domain}/api/v1/auth/callback"]
    realm["clients"][0]["webOrigins"] = [f"https://{domain}"]
    (directory / "realm.json").write_text(json.dumps(realm, indent=2) + "\n")
    print("Created private runtime.env, metrics-token and realm.json. No secret values displayed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--auth-domain", required=True)
    parser.add_argument("--backend-image", required=True)
    parser.add_argument("--web-image", required=True)
    parser.add_argument("--directory", default="deploy/runtime")
    args = parser.parse_args()
    initialize(args.directory, args.domain, args.auth_domain, args.backend_image, args.web_image)
