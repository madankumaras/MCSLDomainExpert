"""
MCSL Order Creator
==================
Creates test Shopify orders for use by the AI QA Agent.

MCSL difference from FedEx: Product IDs come from carrier-env files
(SIMPLE_PRODUCTS_JSON, DANGEROUS_PRODUCTS_JSON), not productsconfig.json.
Each carrier has its own env file in mcsl-test-automation/carrier-envs/.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import requests
from dotenv import dotenv_values

import config
from pipeline.carrier_knowledge import get_carrier_env_path

logger = logging.getLogger(__name__)

# Default carrier-env path (falls back to UPS env if no carrier specified)
_CARRIER_ENV_DIR = Path(config.MCSL_AUTOMATION_REPO_PATH) / "carrier-envs"

def _read_carrier_env(carrier_env_path: str | Path) -> dict[str, str]:
    """Read a carrier-env file and return its key-value pairs."""
    path = Path(carrier_env_path)
    if not path.exists():
        raise FileNotFoundError(f"Carrier env file not found: {path}")
    return dict(dotenv_values(str(path)))


def _get_carrier_env_path(carrier_code: str) -> Path:
    """Return the carrier-env file path for a given carrier code."""
    return get_carrier_env_path(carrier_code)


def _default_address() -> dict[str, Any]:
    """Default test shipping address for order creation."""
    return {
        "first_name": "Test",
        "last_name": "Customer",
        "address1": "123 Main Street",
        "city": "Chicago",
        "province": "Illinois",
        "country": "US",
        "zip": "60601",
        "phone": "555-555-5555",
    }


def _build_line_items(
    env_data: dict[str, str],
    use_dangerous: bool = False,
    product_count: int = 1,
) -> list[dict]:
    """Build Shopify line_items from carrier-env product JSON.

    product_count > 1 creates an order with multiple distinct products so
    that MCSL auto-splits it into multiple packages.
    """
    key = "DANGEROUS_PRODUCTS_JSON" if use_dangerous else "SIMPLE_PRODUCTS_JSON"
    raw = env_data.get(key, "")
    if not raw:
        raw = env_data.get("SIMPLE_PRODUCTS_JSON", "[]")

    products = json.loads(raw)
    if not products:
        raise ValueError(f"No products found in carrier-env {key}")

    chosen = products[:max(1, product_count)]
    return [{"variant_id": p["variant_id"], "quantity": 1} for p in chosen]


def create_order(
    carrier_env_path: str | Path,
    address_override: dict | None = None,
    use_dangerous_products: bool = False,
) -> str:
    """
    Create a single test Shopify order.

    Returns the Shopify order ID as a string.
    Raises requests.HTTPError on API failure.
    """
    env = _read_carrier_env(carrier_env_path)

    store = env.get("SHOPIFY_STORE_NAME", "mcsl-automation")
    token = env.get("SHOPIFY_ACCESS_TOKEN") or config.SHOPIFY_ACCESS_TOKEN
    version = env.get("SHOPIFY_API_VERSION", "2023-01")

    line_items = _build_line_items(env, use_dangerous=use_dangerous_products, product_count=1)
    address = address_override or _default_address()

    url = f"https://{store}.myshopify.com/admin/api/{version}/orders.json"
    payload = {
        "order": {
            "line_items": line_items,
            "shipping_address": address,
            "billing_address": address,
            "financial_status": "paid",
            "send_receipt": False,
            "send_fulfillment_receipt": False,
        }
    }
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()

    order_id = str(resp.json()["order"]["id"])
    logger.info(f"Created Shopify order: {order_id}")
    return order_id


def _automation_root_env() -> Path:
    """Return the root .env path for the mcsl-test-automation repo."""
    return Path(config.MCSL_AUTOMATION_REPO_PATH) / ".env"


def create_order_multi_package(
    carrier_env_path: str | Path | None = None,
    num_packages: int = 2,
    address_override: dict | None = None,
) -> str:
    """Create a single Shopify order with multiple line items so MCSL splits it
    into multiple packages (one per distinct product).

    Falls back to the automation repo root .env when no carrier-specific env
    is available (e.g. carrier-envs/ directory is absent).

    Returns the Shopify order name (e.g. '#3768') as a string.
    """
    # Prefer carrier env, fall back to automation root .env
    env_path = Path(carrier_env_path) if carrier_env_path else None
    if not env_path or not env_path.exists():
        env_path = _automation_root_env()
    env = _read_carrier_env(env_path)

    store = env.get("SHOPIFY_STORE_NAME", "mcsl-automation")
    token = env.get("SHOPIFY_ACCESS_TOKEN") or config.SHOPIFY_ACCESS_TOKEN
    version = env.get("SHOPIFY_API_VERSION", "2023-01")

    line_items = _build_line_items(env, use_dangerous=False, product_count=max(2, num_packages))
    address = address_override or _default_address()

    url = f"https://{store}.myshopify.com/admin/api/{version}/orders.json"
    payload = {
        "order": {
            "line_items": line_items,
            "shipping_address": address,
            "billing_address": address,
            "financial_status": "paid",
            "send_receipt": False,
            "send_fulfillment_receipt": False,
        }
    }
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()

    order_data = resp.json()["order"]
    order_name = str(order_data.get("name", order_data["id"]))
    logger.info("Created multi-package order %s with %d line items", order_name, len(line_items))
    return order_name


def create_bulk_orders(
    carrier_env_path: str | Path,
    count: int = 3,
    address_override: dict | None = None,
    use_dangerous_products: bool = False,
) -> list[str]:
    """
    Create N test Shopify orders.

    Returns list of order ID strings.
    """
    order_ids = []
    for i in range(count):
        try:
            oid = create_order(
                carrier_env_path,
                address_override=address_override,
                use_dangerous_products=use_dangerous_products,
            )
            order_ids.append(oid)
            logger.info(f"Bulk order {i+1}/{count}: {oid}")
        except Exception as e:
            logger.error(f"Failed to create bulk order {i+1}/{count}: {e}")
            raise
    return order_ids


def get_carrier_env_for_code(carrier_code: str) -> Path:
    """Public helper: return the env file path for a carrier code string."""
    return _get_carrier_env_path(carrier_code)
