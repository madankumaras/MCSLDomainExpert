from __future__ import annotations

from pipeline.shopify_product_seed import _seed_specs


def test_seed_specs_cover_expected_product_groups():
    specs = _seed_specs("fedex-rest")

    groups = {}
    for spec in specs:
        groups[spec.group] = groups.get(spec.group, 0) + 1

    assert groups["simple"] >= 2
    assert groups["variable"] >= 2
    assert groups["digital"] >= 2
    assert groups["dangerous"] >= 1
