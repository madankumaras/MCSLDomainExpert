"""Deterministic Shopify product creation for new-carrier validation.

This module creates the exact product groups expected by
`mcsl-test-automation/support/pages/shopifyAPI/createOrderAPI.ts`:

- simple
- variable
- digital
- dangerous

The goal is to create stable product/variant IDs that can be written into a
carrier env file before smoke/sanity/regression execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

import config

_DEFAULT_API_VERSION = config.SHOPIFY_API_VERSION or "2023-01"


@dataclass(frozen=True)
class ProductSeedSpec:
    group: str
    title: str
    body_html: str
    product_type: str
    vendor: str
    tags: str
    variants: list[dict[str, Any]]
    options: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class ProductSeedResult:
    group: str
    product_id: int
    variant_id: int
    title: str


def _seed_specs(carrier_code: str) -> list[ProductSeedSpec]:
    prefix = carrier_code.strip() or "new-carrier"
    return [
        ProductSeedSpec(
            group="simple",
            title=f"{prefix} Simple Product A",
            body_html="<p>Simple physical product for carrier onboarding smoke coverage.</p>",
            product_type="simple",
            vendor="MCSL QA",
            tags="mcsl,new-carrier,simple",
            variants=[{"price": "19.99", "sku": f"{prefix}-simple-a", "inventory_management": None}],
        ),
        ProductSeedSpec(
            group="simple",
            title=f"{prefix} Simple Product B",
            body_html="<p>Secondary simple product for multi-product flows.</p>",
            product_type="simple",
            vendor="MCSL QA",
            tags="mcsl,new-carrier,simple",
            variants=[{"price": "24.99", "sku": f"{prefix}-simple-b", "inventory_management": None}],
        ),
        ProductSeedSpec(
            group="variable",
            title=f"{prefix} Variable Product A",
            body_html="<p>Variant-backed product for variable-product order creation.</p>",
            product_type="variable",
            vendor="MCSL QA",
            tags="mcsl,new-carrier,variable",
            options=[{"name": "Size", "values": ["Small", "Large"]}],
            variants=[
                {"option1": "Small", "price": "29.99", "sku": f"{prefix}-var-a-s"},
                {"option1": "Large", "price": "34.99", "sku": f"{prefix}-var-a-l"},
            ],
        ),
        ProductSeedSpec(
            group="variable",
            title=f"{prefix} Variable Product B",
            body_html="<p>Second variant-backed product for regression coverage.</p>",
            product_type="variable",
            vendor="MCSL QA",
            tags="mcsl,new-carrier,variable",
            options=[{"name": "Pack", "values": ["Single", "Bundle"]}],
            variants=[
                {"option1": "Single", "price": "39.99", "sku": f"{prefix}-var-b-s"},
                {"option1": "Bundle", "price": "69.99", "sku": f"{prefix}-var-b-b"},
            ],
        ),
        ProductSeedSpec(
            group="digital",
            title=f"{prefix} Digital Product A",
            body_html="<p>Digital product for non-shipping order coverage.</p>",
            product_type="digital",
            vendor="MCSL QA",
            tags="mcsl,new-carrier,digital",
            variants=[
                {
                    "price": "9.99",
                    "sku": f"{prefix}-digital-a",
                    "requires_shipping": False,
                    "inventory_management": None,
                }
            ],
        ),
        ProductSeedSpec(
            group="digital",
            title=f"{prefix} Digital Product B",
            body_html="<p>Secondary digital product for mixed catalog coverage.</p>",
            product_type="digital",
            vendor="MCSL QA",
            tags="mcsl,new-carrier,digital",
            variants=[
                {
                    "price": "14.99",
                    "sku": f"{prefix}-digital-b",
                    "requires_shipping": False,
                    "inventory_management": None,
                }
            ],
        ),
        ProductSeedSpec(
            group="dangerous",
            title=f"{prefix} Dangerous Goods Product",
            body_html="<p>Dangerous goods product for carrier hazard scenarios.</p>",
            product_type="dangerous",
            vendor="MCSL QA",
            tags="mcsl,new-carrier,dangerous,goods",
            variants=[{"price": "129.99", "sku": f"{prefix}-dangerous", "inventory_management": None}],
        ),
    ]


def _base_headers(shopify_access_token: str) -> dict[str, str]:
    return {
        "X-Shopify-Access-Token": shopify_access_token,
        "Content-Type": "application/json",
    }


def _build_product_payload(spec: ProductSeedSpec) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "product": {
            "title": spec.title,
            "body_html": spec.body_html,
            "product_type": spec.product_type,
            "vendor": spec.vendor,
            "tags": spec.tags,
            "status": "active",
            "variants": spec.variants,
        }
    }
    if spec.options:
        payload["product"]["options"] = spec.options
    return payload


def _extract_primary_variant_id(product: dict[str, Any]) -> int:
    variants = product.get("variants") or []
    if not variants:
        raise ValueError("Created Shopify product did not include variants")
    variant_id = variants[0].get("id")
    if not variant_id:
        raise ValueError("Created Shopify variant did not include an id")
    return int(variant_id)


def create_seed_products(
    *,
    carrier_code: str,
    store_name: str,
    shopify_access_token: str,
    shopify_api_version: str | None = None,
    timeout_seconds: int = 30,
) -> dict[str, list[ProductSeedResult]]:
    """Create deterministic seed products for a new carrier test store."""
    if not store_name.strip():
        raise ValueError("Shopify store name is required")
    if not shopify_access_token.strip():
        raise ValueError("Shopify access token is required")

    api_version = (shopify_api_version or _DEFAULT_API_VERSION).strip() or _DEFAULT_API_VERSION
    url = f"https://{store_name}.myshopify.com/admin/api/{api_version}/products.json"
    session = requests.Session()
    headers = _base_headers(shopify_access_token)
    results: dict[str, list[ProductSeedResult]] = {
        "simple": [],
        "variable": [],
        "digital": [],
        "dangerous": [],
    }

    for spec in _seed_specs(carrier_code):
        response = session.post(
            url,
            json=_build_product_payload(spec),
            headers=headers,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        product = (response.json() or {}).get("product") or {}
        product_id = product.get("id")
        if not product_id:
            raise ValueError(f"Created Shopify product missing id for {spec.title}")
        results[spec.group].append(
            ProductSeedResult(
                group=spec.group,
                product_id=int(product_id),
                variant_id=_extract_primary_variant_id(product),
                title=str(product.get("title") or spec.title),
            )
        )

    return results
