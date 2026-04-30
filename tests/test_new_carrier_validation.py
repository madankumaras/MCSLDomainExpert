from __future__ import annotations

from pathlib import Path

from pipeline.new_carrier_validation import (
    NewCarrierValidationRun,
    ShopifyProductRef,
    build_new_carrier_run,
    build_carrier_env_content,
    load_new_carrier_run,
    load_existing_carrier_env,
    save_new_carrier_run,
)


def test_build_carrier_env_content_uses_expected_product_env_keys():
    run = NewCarrierValidationRun(
        carrier_code="newCarrierX",
        store_name="new-carrier-store",
        app_url="https://admin.shopify.com/store/new-carrier-store/apps/mcsl-qa",
        shopify_url="https://admin.shopify.com/store/new-carrier-store",
        shopify_access_token="shpat_test",
        product_groups={
            "simple": [ShopifyProductRef(product_id=1, variant_id=11)],
            "variable": [ShopifyProductRef(product_id=2, variant_id=22)],
            "digital": [ShopifyProductRef(product_id=3, variant_id=33)],
            "dangerous": [ShopifyProductRef(product_id=4, variant_id=44)],
        },
    )

    content = build_carrier_env_content(run)

    assert "CARRIER=newCarrierX" in content
    assert "SHOPIFY_STORE_NAME=new-carrier-store" in content
    assert "SIMPLE_PRODUCTS_JSON='[{\"product_id\":1,\"variant_id\":11}]'" in content
    assert "VARIABLE_PRODUCTS_JSON='[{\"product_id\":2,\"variant_id\":22}]'" in content
    assert "DIGITAL_PRODUCTS_JSON='[{\"product_id\":3,\"variant_id\":33}]'" in content
    assert "DANGEROUS_PRODUCTS_JSON='[{\"product_id\":4,\"variant_id\":44}]'" in content


def test_load_existing_carrier_env_returns_empty_for_missing_file():
    missing = load_existing_carrier_env("definitely-not-a-real-carrier-env")
    assert missing == {}


def test_build_new_carrier_run_persists_checkpoint_and_suite_results():
    run = build_new_carrier_run(
        carrier_code="newCarrierX",
        store_name="new-carrier-store",
        product_groups={
            "simple": [ShopifyProductRef(product_id=1, variant_id=11)],
            "variable": [],
            "digital": [],
            "dangerous": [],
        },
        registration_done=True,
        registration_notes="Carrier added in app and credentials verified.",
        suite_results={"smoke": {"returncode": 0}},
    )

    assert run.registration_done is True
    assert "credentials verified" in run.registration_notes
    assert run.suite_results["smoke"]["returncode"] == 0


def test_save_and_load_new_carrier_run_round_trip():
    run = build_new_carrier_run(
        carrier_code="newCarrierX",
        store_name="new-carrier-store",
        store_created=True,
        app_installed=True,
        app_url="https://admin.shopify.com/store/new-carrier-store/apps/mcsl-qa",
        product_groups={
            "simple": [ShopifyProductRef(product_id=1, variant_id=11)],
            "variable": [],
            "digital": [],
            "dangerous": [],
        },
        env_path="/tmp/newCarrierX.env",
        registration_done=True,
        registration_notes="QA completed carrier setup.",
        suite_results={"smoke": {"returncode": 0}},
    )

    path = save_new_carrier_run(run)
    loaded = load_new_carrier_run(path)

    assert loaded.carrier_code == "newCarrierX"
    assert loaded.store_name == "new-carrier-store"
    assert loaded.store_created is True
    assert loaded.app_installed is True
    assert loaded.env_path == "/tmp/newCarrierX.env"
    assert loaded.registration_done is True
    assert loaded.registration_notes == "QA completed carrier setup."
    assert loaded.suite_results["smoke"]["returncode"] == 0
    assert loaded.product_groups["simple"][0].product_id == 1
