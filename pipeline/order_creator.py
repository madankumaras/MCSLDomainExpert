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

logger = logging.getLogger(__name__)

# Default carrier-env path (falls back to UPS env if no carrier specified)
_CARRIER_ENV_DIR = Path(config.MCSL_AUTOMATION_REPO_PATH) / "carrier-envs"

# Carrier code → env file mapping
CARRIER_ENV_MAP = {
    "C2":  "packaging-fedexrest.env",   # FedEx
    "C3":  "ups.env",                    # UPS
    "C1":  "dhl.env",                    # DHL (adjust filename to actual)
    "C22": "usps-ship.env",              # USPS/EasyPost
    "C4":  "canada-post.env",            # Canada Post (adjust to actual)
}


def _read_carrier_env(carrier_env_path: str | Path) -> dict[str, str]:
    """Read a carrier-env file and return its key-value pairs."""
    path = Path(carrier_env_path)
    if not path.exists():
        raise FileNotFoundError(f"Carrier env file not found: {path}")
    return dict(dotenv_values(str(path)))


def _get_carrier_env_path(carrier_code: str) -> Path:
    """Return the carrier-env file path for a given carrier code."""
    filename = CARRIER_ENV_MAP.get(carrier_code)
    if not filename:
        raise ValueError(f"Unknown carrier code: {carrier_code}. Available: {list(CARRIER_ENV_MAP)}")
    path = _CARRIER_ENV_DIR / filename
    # Fall back to any .env file in carrier-envs/ containing the carrier code
    if not path.exists():
        for env_file in _CARRIER_ENV_DIR.glob("*.env"):
            env_data = dotenv_values(str(env_file))
            if env_data.get("CARRIER") == carrier_code:
                return env_file
        raise FileNotFoundError(f"No carrier-env file found for carrier code {carrier_code}")
    return path


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


def _build_line_items(env_data: dict[str, str], use_dangerous: bool = False) -> list[dict]:
    """Build Shopify line_items from carrier-env product JSON."""
    key = "DANGEROUS_PRODUCTS_JSON" if use_dangerous else "SIMPLE_PRODUCTS_JSON"
    raw = env_data.get(key, "")
    if not raw:
        # Fallback: use SIMPLE_PRODUCTS_JSON
        raw = env_data.get("SIMPLE_PRODUCTS_JSON", "[]")

    products = json.loads(raw)
    if not products:
        raise ValueError(f"No products found in carrier-env {key}")

    # Use first product only for single orders
    product = products[0]
    return [{
        "variant_id": product["variant_id"],
        "quantity": 1,
    }]


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

    line_items = _build_line_items(env, use_dangerous=use_dangerous_products)
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


def create_bulk_orders(
    carrier_env_path: str | Path,
    count: int = 3,
    address_override: dict | None = None,
) -> list[str]:
    """
    Create N test Shopify orders.

    Returns list of order ID strings.
    """
    order_ids = []
    for i in range(count):
        try:
            oid = create_order(carrier_env_path, address_override=address_override)
            order_ids.append(oid)
            logger.info(f"Bulk order {i+1}/{count}: {oid}")
        except Exception as e:
            logger.error(f"Failed to create bulk order {i+1}/{count}: {e}")
            raise
    return order_ids


def get_carrier_env_for_code(carrier_code: str) -> Path:
    """Public helper: return the env file path for a carrier code string."""
    return _get_carrier_env_path(carrier_code)
