"""New carrier validation planning and env generation helpers.

This module defines the first backend contract for the planned
`🚚 New Carrier Validation` workflow:

- product groups that automation already expects
- a persisted run model
- carrier-env file generation in the exact shape used by
  `mcsl-test-automation/support/pages/shopifyAPI/createOrderAPI.ts`
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from dotenv import dotenv_values

import config

_CARRIER_ENV_DIR = Path(config.MCSL_AUTOMATION_REPO_PATH) / "carrier-envs"
_RUNS_DIR = Path(__file__).resolve().parent.parent / "data" / "new_carrier_runs"

PRODUCT_GROUP_KEYS = (
    "simple",
    "variable",
    "digital",
    "dangerous",
)

ENV_PRODUCT_KEY_MAP = {
    "simple": "SIMPLE_PRODUCTS_JSON",
    "variable": "VARIABLE_PRODUCTS_JSON",
    "digital": "DIGITAL_PRODUCTS_JSON",
    "dangerous": "DANGEROUS_PRODUCTS_JSON",
}


@dataclass(frozen=True)
class ShopifyProductRef:
    product_id: int
    variant_id: int

    def to_env_dict(self) -> dict[str, int]:
        return {
            "product_id": int(self.product_id),
            "variant_id": int(self.variant_id),
        }


@dataclass
class NewCarrierValidationRun:
    carrier_code: str
    store_name: str
    store_created: bool = False
    app_installed: bool = False
    app_url: str = ""
    shopify_url: str = ""
    partner_url: str = ""
    partner_apps_url: str = ""
    user_email: str = ""
    user_password: str = ""
    store_password: str = ""
    shopify_access_token: str = ""
    shopify_api_version: str = "2023-01"
    slack_webhook_url: str = ""
    product_groups: dict[str, list[ShopifyProductRef]] = field(default_factory=dict)
    env_path: str = ""
    notes: str = ""
    registration_done: bool = False
    registration_notes: str = ""
    suite_results: dict[str, dict] = field(default_factory=dict)

    def normalized_product_groups(self) -> dict[str, list[ShopifyProductRef]]:
        groups: dict[str, list[ShopifyProductRef]] = {}
        for key in PRODUCT_GROUP_KEYS:
            groups[key] = list(self.product_groups.get(key, []))
        return groups


def _slugify_carrier_code(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "new-carrier"


def _to_env_json(products: list[ShopifyProductRef]) -> str:
    payload = [item.to_env_dict() for item in products]
    return json.dumps(payload, separators=(",", ":"))


def build_carrier_env_content(run: NewCarrierValidationRun) -> str:
    """Build carrier env file content in the automation repo format."""
    product_groups = run.normalized_product_groups()
    lines = [
        f"CARRIER={run.carrier_code}",
        f"SLACK_WEBHOOK_URL={run.slack_webhook_url}",
        f"PARTNER_URL={run.partner_url}",
        f"SHOPIFYURL={run.shopify_url}",
        f"APPURL={run.app_url}",
        f"USER_EMAIL={run.user_email}",
        f"USER_PASSWORD={run.user_password}",
        f"STORE_PASSWORD={run.store_password}",
        f"SHOPIFY_API_VERSION={run.shopify_api_version or config.SHOPIFY_API_VERSION}",
        f"SHOPIFY_STORE_NAME={run.store_name}",
        f"SHOPIFY_ACCESS_TOKEN={run.shopify_access_token or config.SHOPIFY_ACCESS_TOKEN}",
    ]

    for group_key in PRODUCT_GROUP_KEYS:
        env_key = ENV_PRODUCT_KEY_MAP[group_key]
        lines.append(f"{env_key}='{_to_env_json(product_groups[group_key])}'")

    return "\n".join(lines).strip() + "\n"


def write_carrier_env_file(
    run: NewCarrierValidationRun,
    *,
    overwrite: bool = True,
) -> Path:
    """Write the carrier env file for a newly onboarded carrier/store."""
    _CARRIER_ENV_DIR.mkdir(parents=True, exist_ok=True)
    carrier_slug = _slugify_carrier_code(run.carrier_code)
    path = _CARRIER_ENV_DIR / f"{carrier_slug}.env"
    if path.exists() and not overwrite:
        raise FileExistsError(f"Carrier env already exists: {path}")
    path.write_text(build_carrier_env_content(run), encoding="utf-8")
    run.env_path = str(path)
    return path


def save_new_carrier_run(run: NewCarrierValidationRun) -> Path:
    """Persist a carrier-validation run record under data/new_carrier_runs/."""
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    carrier_slug = _slugify_carrier_code(run.carrier_code)
    store_slug = _slugify_carrier_code(run.store_name)
    path = _RUNS_DIR / f"{carrier_slug}--{store_slug}.json"
    payload = asdict(run)
    payload["product_groups"] = {
        key: [item.to_env_dict() for item in values]
        for key, values in run.normalized_product_groups().items()
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _product_groups_from_payload(payload: dict) -> dict[str, list[ShopifyProductRef]]:
    groups: dict[str, list[ShopifyProductRef]] = {}
    for key in PRODUCT_GROUP_KEYS:
        values = payload.get("product_groups", {}).get(key, []) or []
        groups[key] = [
            ShopifyProductRef(
                product_id=int(item["product_id"]),
                variant_id=int(item["variant_id"]),
            )
            for item in values
            if item.get("product_id") is not None and item.get("variant_id") is not None
        ]
    return groups


def build_new_carrier_run(
    *,
    carrier_code: str,
    store_name: str,
    product_groups: dict[str, list[ShopifyProductRef]],
    store_created: bool = False,
    app_installed: bool = False,
    app_url: str = "",
    shopify_url: str = "",
    partner_url: str = "",
    partner_apps_url: str = "",
    user_email: str = "",
    user_password: str = "",
    store_password: str = "",
    shopify_access_token: str = "",
    shopify_api_version: str = "2023-01",
    slack_webhook_url: str = "",
    env_path: str = "",
    notes: str = "",
    registration_done: bool = False,
    registration_notes: str = "",
    suite_results: dict[str, dict] | None = None,
) -> NewCarrierValidationRun:
    return NewCarrierValidationRun(
        carrier_code=carrier_code,
        store_name=store_name,
        store_created=store_created,
        app_installed=app_installed,
        app_url=app_url,
        shopify_url=shopify_url,
        partner_url=partner_url,
        partner_apps_url=partner_apps_url,
        user_email=user_email,
        user_password=user_password,
        store_password=store_password,
        shopify_access_token=shopify_access_token,
        shopify_api_version=shopify_api_version,
        slack_webhook_url=slack_webhook_url,
        product_groups=product_groups,
        env_path=env_path,
        notes=notes,
        registration_done=registration_done,
        registration_notes=registration_notes,
        suite_results=dict(suite_results or {}),
    )


def list_new_carrier_runs() -> list[Path]:
    """Return persisted new-carrier run files, newest first."""
    if not _RUNS_DIR.exists():
        return []
    return sorted(_RUNS_DIR.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)


def load_new_carrier_run(path: str | Path) -> NewCarrierValidationRun:
    """Load a persisted new-carrier run from disk."""
    run_path = Path(path)
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    return NewCarrierValidationRun(
        carrier_code=str(payload.get("carrier_code", "")),
        store_name=str(payload.get("store_name", "")),
        store_created=bool(payload.get("store_created", False)),
        app_installed=bool(payload.get("app_installed", False)),
        app_url=str(payload.get("app_url", "")),
        shopify_url=str(payload.get("shopify_url", "")),
        partner_url=str(payload.get("partner_url", "")),
        partner_apps_url=str(payload.get("partner_apps_url", "")),
        user_email=str(payload.get("user_email", "")),
        user_password=str(payload.get("user_password", "")),
        store_password=str(payload.get("store_password", "")),
        shopify_access_token=str(payload.get("shopify_access_token", "")),
        shopify_api_version=str(payload.get("shopify_api_version", "2023-01")),
        slack_webhook_url=str(payload.get("slack_webhook_url", "")),
        product_groups=_product_groups_from_payload(payload),
        env_path=str(payload.get("env_path", "")),
        notes=str(payload.get("notes", "")),
        registration_done=bool(payload.get("registration_done", False)),
        registration_notes=str(payload.get("registration_notes", "")),
        suite_results=dict(payload.get("suite_results", {}) or {}),
    )


def load_existing_carrier_env(carrier_code: str) -> dict[str, str]:
    """Load an existing carrier env file from the automation repo if present."""
    path = _CARRIER_ENV_DIR / f"{_slugify_carrier_code(carrier_code)}.env"
    if not path.exists():
        return {}
    return dict(dotenv_values(str(path)))
