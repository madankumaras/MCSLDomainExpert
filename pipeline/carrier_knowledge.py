"""Shared MCSL carrier knowledge and card scope detection."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from dotenv import dotenv_values

import config


@dataclass(frozen=True)
class CarrierProfile:
    canonical_name: str
    internal_code: str = ""
    aliases: tuple[str, ...] = ()
    env_filenames: tuple[str, ...] = ()
    platform_supported: bool = True
    automation_ready: bool = False
    notes: tuple[str, ...] = ()
    support_summary: str = ""
    typical_areas: tuple[str, ...] = ()
    verification_focus: tuple[str, ...] = ()


@dataclass(frozen=True)
class CarrierScope:
    scope: str
    carriers: tuple[CarrierProfile, ...] = ()

    @property
    def is_generic(self) -> bool:
        return self.scope == "generic"

    @property
    def primary(self) -> CarrierProfile | None:
        return self.carriers[0] if self.carriers else None


CARRIER_PROFILES: tuple[CarrierProfile, ...] = (
    CarrierProfile(
        canonical_name="FedEx",
        internal_code="C2",
        aliases=("fedex", "fed ex", "fedex rest", "fedexrest"),
        env_filenames=("packaging-fedexrest.env",),
        automation_ready=True,
        notes=("special services include HAL, signature, dry ice, alcohol, insurance",),
        support_summary="FedEx in MCSL commonly touches special services, customs/commercial invoice data, and request/label payload accuracy.",
        typical_areas=("Carriers", "Products", "ORDERS", "Request Log"),
        verification_focus=("special services in product/carrier settings", "rate request payload", "label request payload", "generated customs docs"),
    ),
    CarrierProfile(
        canonical_name="UPS",
        internal_code="C3",
        aliases=("ups", "ups surepost", "surepost", "ups int", "ups international"),
        env_filenames=("ups.env", "packaging-ups.env", "packaging-upsint.env"),
        automation_ready=True,
        notes=("supports COD, insurance, SurePost, international variants",),
        support_summary="UPS usually involves negotiated rates, SurePost/COD/international behavior, and service-selection automation rules.",
        typical_areas=("Carriers", "ORDERS", "Automation Rules", "Shipping Rates"),
        verification_focus=("selected service and rate rules", "rate response", "label creation", "international settings"),
    ),
    CarrierProfile(
        canonical_name="DHL",
        internal_code="C1",
        aliases=("dhl", "dhl express"),
        env_filenames=("dhl.env",),
        automation_ready=True,
        notes=("carrier-specific signature and international flows may apply",),
        support_summary="DHL work is typically international and may involve duty/tax, paperless trade, and customs-document accuracy.",
        typical_areas=("Carriers", "Products", "ORDERS", "LABELS"),
        verification_focus=("international account setup", "customs values", "paperless trade docs", "label/document generation"),
    ),
    CarrierProfile(
        canonical_name="USPS",
        internal_code="C22",
        aliases=("usps", "usps ship", "shippo usps"),
        env_filenames=("usps-ship.env",),
        automation_ready=True,
        support_summary="USPS often covers domestic/international parcel rules, service pricing, and label or customs handling.",
        typical_areas=("Carriers", "ORDERS", "LABELS"),
        verification_focus=("service availability", "commercial pricing", "label output", "customs docs where relevant"),
    ),
    CarrierProfile(
        canonical_name="USPS Stamps",
        internal_code="C22",
        aliases=("stamps", "stamps.com", "usps stamps"),
        env_filenames=("usps-stamps.env",),
        automation_ready=True,
        support_summary="USPS Stamps flows commonly include commercial pricing, sample labels, and registered/certified-style services.",
        typical_areas=("Carriers", "ORDERS", "LABELS"),
        verification_focus=("Stamps account path", "service mapping", "label generation"),
    ),
    CarrierProfile(
        canonical_name="EasyPost",
        internal_code="C22",
        aliases=("easypost",),
        env_filenames=(),
    ),
    CarrierProfile(
        canonical_name="Canada Post",
        internal_code="C4",
        aliases=("canada post",),
        env_filenames=("canada-post.env",),
        automation_ready=True,
        support_summary="Canada Post can involve service-point and proof-of-age style requirements plus label/output localization.",
        typical_areas=("Carriers", "ORDERS", "LABELS"),
        verification_focus=("carrier account settings", "service options", "label text/output", "tracking sync"),
    ),
    CarrierProfile(
        canonical_name="Australia Post",
        aliases=("australia post", "auspost"),
        env_filenames=("australia-post.env",),
        automation_ready=True,
        support_summary="Australia Post flows usually follow the shared MCSL order and label path with carrier-specific account/setup checks.",
    ),
    CarrierProfile(
        canonical_name="TNT Australia",
        aliases=("tnt australia",),
        env_filenames=("tnt-australia.env",),
        automation_ready=True,
    ),
    CarrierProfile(
        canonical_name="Blue Dart",
        aliases=("blue dart", "bluedart"),
        env_filenames=("blue-dart.env",),
        automation_ready=True,
    ),
    CarrierProfile(
        canonical_name="Amazon Shipping",
        aliases=("amazon shipping", "amazon"),
        env_filenames=("amazon.env",),
        automation_ready=True,
        support_summary="Amazon Shipping issues often include seller/account setup constraints and service availability behavior.",
    ),
    CarrierProfile(
        canonical_name="MyPost",
        aliases=("mypost", "my post"),
        env_filenames=("packaging-mypost.env",),
        automation_ready=True,
    ),
    CarrierProfile(
        canonical_name="Purolator",
        internal_code="C16",
        aliases=("purolator",),
        env_filenames=("purolator.env",),
        automation_ready=True,
        support_summary="Purolator support often focuses on carrier-specific account/service behavior and Canadian shipment constraints.",
    ),
    CarrierProfile(
        canonical_name="PostNord",
        aliases=("postnord", "post nord"),
        env_filenames=("postnord.env",),
        automation_ready=True,
        support_summary="PostNord scenarios are usually carrier-specific label/customs/document behavior on top of shared MCSL flows.",
    ),
    CarrierProfile(
        canonical_name="TNT Express",
        aliases=("tnt express",),
        env_filenames=("tnt-express.env",),
        automation_ready=True,
        support_summary="TNT Express is generally a carrier-specific international/service workflow layered onto shared MCSL order processing.",
    ),
    CarrierProfile(
        canonical_name="Parcel Force",
        aliases=("parcel force", "parcelforce"),
        env_filenames=("parcelforce.env",),
        automation_ready=True,
        support_summary="Parcel Force tends to follow shared app flows with carrier-specific service/account and label checks.",
    ),
    CarrierProfile(
        canonical_name="EasyPost USPS",
        aliases=("easy post usps", "easypost usps", "easy post", "easypost"),
        env_filenames=("easypost-usps.env",),
        automation_ready=True,
        support_summary="EasyPost USPS should be treated as a USPS-family REST workflow with EasyPost integration behavior.",
    ),
    CarrierProfile(
        canonical_name="Post NL",
        aliases=("post nl", "postnl"),
        env_filenames=("postnl.env",),
        automation_ready=True,
        support_summary="Post NL uses shared MCSL flows with carrier-specific service and label expectations.",
    ),
    CarrierProfile(
        canonical_name="Aramex",
        aliases=("aramex",),
        env_filenames=("aramex.env",),
        automation_ready=True,
        support_summary="Aramex scenarios usually require carrier-specific setup and request/label validation within shared MCSL navigation.",
    ),
    CarrierProfile(
        canonical_name="NZ Post",
        aliases=("nz post", "new zealand post"),
        env_filenames=("nz-post.env",),
        automation_ready=True,
        support_summary="NZ Post follows the standard MCSL navigation with carrier-specific rating/label/account rules.",
    ),
    CarrierProfile(
        canonical_name="Sendle",
        aliases=("sendle",),
        env_filenames=("sendle.env",),
        automation_ready=True,
        support_summary="Sendle support should focus on the named carrier’s account/setup and request/response behavior in shared flows.",
    ),
    CarrierProfile(
        canonical_name="APC Postal Logistics",
        aliases=("apc postal logistics", "apc"),
        env_filenames=("apc-postal-logistics.env",),
        automation_ready=True,
        support_summary="APC Postal Logistics is carrier-specific and should be verified through shared order/label flows plus carrier setup.",
    ),
    CarrierProfile(
        canonical_name="Landmark Global",
        aliases=("landmark global",),
        env_filenames=("landmark-global.env",),
        automation_ready=True,
        support_summary="Landmark Global is cross-border focused and should be checked for carrier setup plus document/label behavior.",
    ),
)

DEFAULT_GENERIC_CARRIER = "USPS Stamps"


def all_supported_carrier_names() -> list[str]:
    return [profile.canonical_name for profile in CARRIER_PROFILES]


def automation_ready_carrier_names() -> list[str]:
    return [profile.canonical_name for profile in CARRIER_PROFILES if profile.automation_ready]


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


def detect_carrier_scope(*texts: str) -> CarrierScope:
    combined = _normalize(" ".join(texts))
    found: list[CarrierProfile] = []
    for profile in CARRIER_PROFILES:
        if any(alias in combined for alias in profile.aliases):
            found.append(profile)
    if not found:
        return CarrierScope(scope="generic", carriers=())
    deduped: list[CarrierProfile] = []
    seen = set()
    for profile in found:
        if profile.canonical_name not in seen:
            seen.add(profile.canonical_name)
            deduped.append(profile)
    return CarrierScope(scope="carrier_specific", carriers=tuple(deduped))


def carrier_prompt_block(*texts: str) -> str:
    scope = detect_carrier_scope(*texts)
    automation_ready = ", ".join(automation_ready_carrier_names())
    if scope.is_generic:
        return (
            "Carrier scope: GENERIC / carrier-agnostic.\n"
            f"No explicit carrier was detected, so the card should be treated as a generic MCSL flow. "
            f"For QA planning, a stable default carrier path such as {DEFAULT_GENERIC_CARRIER} may be used "
            "unless the retrieved context says the scenario must be carrier-neutral or must cover multiple carriers.\n"
            "Platform note: MCSL supports many carriers globally; local automation-ready carriers currently include "
            f"{automation_ready}."
        )
    lines = [
        "Carrier scope: CARRIER-SPECIFIC.",
        "Detected carriers: " + ", ".join(profile.canonical_name for profile in scope.carriers),
    ]
    primary = scope.primary
    if primary and primary.internal_code:
        lines.append(f"Primary carrier internal code: {primary.internal_code}")
    if primary:
        lines.append(
            f"Automation readiness: {'yes' if primary.automation_ready else 'not confirmed from local carrier envs'}"
        )
        if primary.support_summary:
            lines.append(f"Support summary: {primary.support_summary}")
        if primary.typical_areas:
            lines.append("Typical MCSL areas: " + ", ".join(primary.typical_areas))
        if primary.verification_focus:
            lines.append("Verification focus: " + ", ".join(primary.verification_focus))
    return "\n".join(lines)


def carrier_research_context(*texts: str, max_docs: int = 4) -> str:
    """Build richer carrier-aware context from registry metadata plus KB/wiki retrieval."""
    scope = detect_carrier_scope(*texts)
    sections: list[str] = [carrier_prompt_block(*texts)]

    if scope.is_generic:
        sections.append(
            "Generic execution rule: prefer shared MCSL flows first "
            "(ORDERS, LABELS, PICKUP, Products, Carriers, Packaging, Request Log)."
        )
        return "\n\n".join(section for section in sections if section.strip())

    primary = scope.primary
    if primary:
        profile_lines = [
            f"Primary carrier profile: {primary.canonical_name}",
            f"Platform supported: {'yes' if primary.platform_supported else 'unknown'}",
            f"Automation ready locally: {'yes' if primary.automation_ready else 'no'}",
        ]
        if primary.env_filenames:
            profile_lines.append("Local env files: " + ", ".join(primary.env_filenames))
        if primary.notes:
            profile_lines.append("Known notes: " + "; ".join(primary.notes))
        sections.append("\n".join(profile_lines))

    query_parts = [profile.canonical_name for profile in scope.carriers]
    query_parts.extend(
        [
            "carrier configuration",
            "label generation",
            "request log",
            "automation rules",
            "shopify",
        ]
    )
    query = " ".join(query_parts)
    try:
        from rag.vectorstore import search_filtered

        retrieved: list[str] = []
        for source_type, label in (("wiki", "Wiki"), ("kb_articles", "KB")):
            docs = search_filtered(query, k=max_docs, source_type=source_type) or []
            if not docs:
                continue
            snippets: list[str] = []
            for doc in docs[:max_docs]:
                source = (
                    doc.metadata.get("title")
                    or doc.metadata.get("source")
                    or doc.metadata.get("file_path")
                    or label.lower()
                )
                snippets.append(f"[{source}]\n{doc.page_content[:500]}")
            if snippets:
                retrieved.append(f"{label} carrier context:\n" + "\n\n---\n\n".join(snippets))
        if retrieved:
            sections.extend(retrieved)
    except Exception:
        pass

    return "\n\n".join(section for section in sections if section.strip())


def get_carrier_env_path(carrier_code: str) -> Path:
    env_dir = Path(config.MCSL_AUTOMATION_REPO_PATH) / "carrier-envs"
    matching_profile = next((profile for profile in CARRIER_PROFILES if profile.internal_code == carrier_code), None)
    candidate_names = matching_profile.env_filenames if matching_profile else ()
    for filename in candidate_names:
        path = env_dir / filename
        if path.exists():
            return path
    for env_file in env_dir.glob("*.env"):
        try:
            text = env_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if f"CARRIER={carrier_code}" in text or f'CARRIER="{carrier_code}"' in text:
            return env_file
    raise FileNotFoundError(f"No carrier env file found for carrier code {carrier_code}")


def _read_env_value(env_path: Path, key: str) -> str:
    try:
        data = dotenv_values(env_path)
    except Exception:
        return ""
    value = (data.get(key) or "").strip()
    return value


def get_default_store_slug(*texts: str) -> str:
    """Return the preferred Shopify store slug for a card/context.

    Carrier-specific cards use the detected carrier env first.
    Generic cards default to USPS Stamps.
    """
    scope = detect_carrier_scope(*texts)
    target_profile: CarrierProfile | None = scope.primary
    if scope.is_generic:
        target_profile = next(
            (profile for profile in CARRIER_PROFILES if profile.canonical_name == DEFAULT_GENERIC_CARRIER),
            None,
        )

    if target_profile and target_profile.internal_code:
        try:
            env_path = get_carrier_env_path(target_profile.internal_code)
            store = _read_env_value(env_path, "SHOPIFY_STORE_NAME")
            if store:
                return store
        except Exception:
            pass

    # Fall back to the automation repo .env (SHOPIFY_STORE_NAME there is authoritative)
    _auto_env = Path(getattr(config, "MCSL_AUTOMATION_REPO_PATH", "") or "").parent / ".env"
    if not _auto_env.exists():
        _auto_env = Path(getattr(config, "MCSL_AUTOMATION_REPO_PATH", "") or "") / ".env"
    store = _read_env_value(_auto_env, "SHOPIFY_STORE_NAME") if _auto_env.exists() else ""
    if store:
        return store.removesuffix(".myshopify.com")

    raw = (getattr(config, "STORE", "") or "").strip()
    return raw.removesuffix(".myshopify.com")


def get_default_app_url(*texts: str) -> str:
    # APPURL in the automation repo .env is the most reliable source
    _auto_env = Path(getattr(config, "MCSL_AUTOMATION_REPO_PATH", "") or "") / ".env"
    if _auto_env.exists():
        url = _read_env_value(_auto_env, "APPURL")
        if url:
            return url.rstrip("/")

    store = get_default_store_slug(*texts)
    if not store:
        return ""
    return f"https://admin.shopify.com/store/{store}/apps/mcsl-qa"
