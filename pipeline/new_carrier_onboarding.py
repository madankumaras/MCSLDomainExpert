"""Shopify Partner onboarding runner for new-carrier validation."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path

import config

DEFAULT_PARTNER_STORES_URL = "https://dev.shopify.com/dashboard/129786666/stores"
DEFAULT_PARTNER_APPS_URL = "https://dev.shopify.com/dashboard/129786666/apps"
DEFAULT_APP_CARD_ID = "app_card_6038317"
DEFAULT_APP_SLUG = "mcsl-qa"


@dataclass(frozen=True)
class NewCarrierOnboardingResult:
    store_name: str
    store_created: bool
    app_installed: bool
    shopify_url: str
    app_url: str
    stdout: str
    stderr: str
    returncode: int
    started_at: float
    finished_at: float

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.finished_at - self.started_at)


def _automation_repo() -> Path:
    repo = Path(config.MCSL_AUTOMATION_REPO_PATH).expanduser().resolve()
    if not repo.exists():
        raise FileNotFoundError(f"Automation repo not found: {repo}")
    return repo


def _build_onboarding_script() -> str:
    return textwrap.dedent(
        """
        import { chromium } from 'playwright';
        import fs from 'node:fs';

        const storeName = process.env.NEW_CARRIER_STORE_NAME;
        const partnerStoresUrl = process.env.NEW_CARRIER_PARTNER_STORES_URL;
        const partnerAppsUrl = process.env.NEW_CARRIER_PARTNER_APPS_URL;
        const userEmail = process.env.USER_EMAIL || '';
        const shopifyUserEmail = process.env.SHOPIFY_EMAIL || userEmail;
        const appCardId = process.env.NEW_CARRIER_APP_CARD_ID || 'app_card_6038317';
        const appSearchName = process.env.NEW_CARRIER_APP_SEARCH || 'QA-MultiCarrier Shipping Label';
        const appSlug = process.env.NEW_CARRIER_APP_SLUG || 'mcsl-qa';
        const storagePath = process.env.NEW_CARRIER_STORAGE_PATH || './auth-chrome.json';
        const planName = process.env.NEW_CARRIER_SHOPIFY_PLAN || 'Advanced';

        if (!storeName) {
          throw new Error('NEW_CARRIER_STORE_NAME is required');
        }

        async function waitBestEffort(page, ms) {
          try {
            await page.waitForTimeout(ms);
          } catch {}
        }

        async function clickAccountCard(page) {
          await page.waitForLoadState('domcontentloaded').catch(() => {});
          const headings = page.getByRole('heading', { name: 'Choose an account' });
          const chooseVisible = await headings.first().isVisible().catch(() => false);
          if (!chooseVisible) return;
          const emailToUse = shopifyUserEmail || userEmail;
          let accountCard = page.locator('a.choose-account-card').filter({ hasText: emailToUse });
          if (await accountCard.count() === 0) {
            accountCard = page.locator('a.choose-account-card').first();
          }
          if (await accountCard.count() > 0) {
            await accountCard.first().click();
            await page.waitForLoadState('domcontentloaded').catch(() => {});
          }
        }

        async function maybeFillOnboarding(page) {
          const frame = page.frameLocator('iframe[name="app-iframe"]');
          const submit = frame.getByRole('button', { name: 'Submit' });
          if (await submit.count() === 0) return;

          const emailBox = frame.locator('input[type="email"]').first();
          const phoneBox = frame.locator('input[type="tel"]').first();
          const checkbox = frame.locator('input[type="checkbox"]').first();

          if (await emailBox.count()) await emailBox.fill('test@email.com');
          if (await phoneBox.count()) await phoneBox.fill('1234567890');
          if (await checkbox.count()) await checkbox.check().catch(() => {});
          await submit.click().catch(() => {});

          const startBtn = frame.getByRole('button', { name: 'Start' }).first();
          if (await startBtn.count()) {
            await startBtn.click().catch(() => {});
          }
        }

        const browser = await chromium.launch({
          channel: 'chrome',
          headless: false,
          args: ['--disable-blink-features=AutomationControlled', '--window-size=1400,1000'],
        });

        const contextOptions = {};
        if (fs.existsSync(storagePath)) {
          contextOptions.storageState = storagePath;
        }
        const context = await browser.newContext(contextOptions);
        const page = await context.newPage();

        let created = false;
        let installed = false;

        try {
          await page.goto(partnerStoresUrl, { waitUntil: 'domcontentloaded', timeout: 120000 });
          await clickAccountCard(page);

          const addStoreLink = page.getByRole('link', { name: 'Add dev store' });
          await addStoreLink.waitFor({ state: 'visible', timeout: 60000 });
          const popupPromise = page.waitForEvent('popup');
          await addStoreLink.click();
          const storePopup = await popupPromise;
          await storePopup.waitForLoadState('domcontentloaded', { timeout: 60000 }).catch(() => {});

          const nameField = storePopup.locator('input[name="storeName"]').first();
          await nameField.waitFor({ state: 'visible', timeout: 60000 });
          await nameField.fill(storeName);

          const planSelect = storePopup.locator('select[name="Shopify plan"]').first();
          if (await planSelect.count()) {
            await planSelect.selectOption(planName).catch(() => {});
          }

          await storePopup.getByText('Create store').click();
          await clickAccountCard(storePopup);
          await waitBestEffort(storePopup, 12000);
          created = true;

          await page.goto(partnerAppsUrl, { waitUntil: 'domcontentloaded', timeout: 120000 });
          await clickAccountCard(page);

          const searchField = page.locator('#apps-search-input').first();
          await searchField.waitFor({ state: 'visible', timeout: 60000 });
          await searchField.fill(appSearchName);
          await waitBestEffort(page, 3000);

          const appCard = page.locator(`#${appCardId}`).first();
          await appCard.waitFor({ state: 'visible', timeout: 60000 });
          await appCard.click();

          const installLink = page.getByRole('link', { name: 'Install app' }).first();
          await installLink.waitFor({ state: 'visible', timeout: 60000 });
          const installPopupPromise = page.waitForEvent('popup');
          await installLink.click();
          const installPopup = await installPopupPromise;
          await installPopup.waitForLoadState('domcontentloaded', { timeout: 60000 }).catch(() => {});

          const storeSearch = installPopup.locator('#P0-0').first();
          await storeSearch.waitFor({ state: 'visible', timeout: 60000 });
          await storeSearch.fill(storeName);
          await waitBestEffort(installPopup, 8000);

          const filteredStore = installPopup.locator(`text="${storeName}"`).first();
          await filteredStore.waitFor({ state: 'visible', timeout: 60000 });
          await filteredStore.click();

          const proceed = installPopup.locator('#proceed_cta').first();
          await proceed.waitFor({ state: 'visible', timeout: 60000 });
          await proceed.click();
          await waitBestEffort(installPopup, 5000);

          const frame = installPopup.frameLocator('iframe[name="app-iframe"]');
          const selectPlan = frame.getByRole('button', { name: 'Select Plan' }).nth(1);
          if (await selectPlan.count()) {
            await selectPlan.click().catch(() => {});
          }
          await waitBestEffort(installPopup, 3000);

          const approve = installPopup.locator('#approve-charges-button').first();
          if (await approve.count()) {
            await approve.click().catch(() => {});
          }
          await waitBestEffort(installPopup, 6000);
          await maybeFillOnboarding(installPopup);
          installed = true;

          const result = {
            store_name: storeName,
            store_created: created,
            app_installed: installed,
            shopify_url: `https://admin.shopify.com/store/${storeName}`,
            app_url: `https://admin.shopify.com/store/${storeName}/apps/${appSlug}`,
          };
          console.log(JSON.stringify(result));
        } finally {
          await context.close().catch(() => {});
          await browser.close().catch(() => {});
        }
        """
    ).strip()


def create_store_and_install_app(
    *,
    store_name: str,
    partner_stores_url: str = DEFAULT_PARTNER_STORES_URL,
    partner_apps_url: str = DEFAULT_PARTNER_APPS_URL,
    app_search_name: str = "QA-MultiCarrier Shipping Label",
    app_card_id: str = DEFAULT_APP_CARD_ID,
    app_slug: str = DEFAULT_APP_SLUG,
    plan_name: str = "Advanced",
    timeout_seconds: int = 900,
) -> NewCarrierOnboardingResult:
    if not store_name.strip():
        raise ValueError("Store name is required")

    repo = _automation_repo()
    script = _build_onboarding_script()
    env = os.environ.copy()
    env.update(
        {
            "NEW_CARRIER_STORE_NAME": store_name.strip(),
            "NEW_CARRIER_PARTNER_STORES_URL": partner_stores_url.strip(),
            "NEW_CARRIER_PARTNER_APPS_URL": partner_apps_url.strip(),
            "NEW_CARRIER_APP_SEARCH": app_search_name,
            "NEW_CARRIER_APP_CARD_ID": app_card_id,
            "NEW_CARRIER_APP_SLUG": app_slug,
            "NEW_CARRIER_SHOPIFY_PLAN": plan_name,
            "NEW_CARRIER_STORAGE_PATH": getattr(
                config,
                "MCSL_CHROME_AUTH_PATH",
                str(repo / "auth-chrome.json"),
            ),
        }
    )

    started_at = time.time()
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as handle:
        handle.write(script)
        temp_path = handle.name
    try:
        completed = subprocess.run(
            ["node", temp_path],
            cwd=str(repo),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    finally:
        Path(temp_path).unlink(missing_ok=True)
    finished_at = time.time()

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if completed.returncode != 0:
        raise RuntimeError(stderr.strip() or stdout.strip() or "Store onboarding failed")

    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    payload = {}
    for line in reversed(lines):
        if line.startswith("{") and line.endswith("}"):
            payload = json.loads(line)
            break
    if not payload:
        raise RuntimeError("Store onboarding completed without structured result payload")

    return NewCarrierOnboardingResult(
        store_name=str(payload.get("store_name") or store_name),
        store_created=bool(payload.get("store_created")),
        app_installed=bool(payload.get("app_installed")),
        shopify_url=str(payload.get("shopify_url") or ""),
        app_url=str(payload.get("app_url") or ""),
        stdout=stdout,
        stderr=stderr,
        returncode=int(completed.returncode),
        started_at=started_at,
        finished_at=finished_at,
    )
