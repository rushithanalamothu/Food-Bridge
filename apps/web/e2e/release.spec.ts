import { expect, test } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { locationInput } from '../src/api/time';
import AxeBuilder from '@axe-core/playwright';

let cleanup: (() => Promise<void>) | undefined;
test.afterEach(async () => {
  if (cleanup) await cleanup();
  cleanup = undefined;
});

test('real identity screens match the app theme, including password errors and mobile layout', async ({
  page,
}) => {
  test.setTimeout(60000);
  await page.goto('/donor');
  const signIn = page.getByRole('button', { name: 'Sign in', exact: true });
  const appearance = (element: Element) => {
    const style = getComputedStyle(element);
    return {
      background: style.backgroundColor,
      color: style.color,
      font: style.fontFamily,
      size: style.fontSize,
      radius: style.borderRadius,
      minHeight: style.minHeight,
    };
  };
  const appButton = await signIn.evaluate(appearance);
  const appBackground = await page
    .locator('.app-shell')
    .evaluate((element) => getComputedStyle(element).backgroundColor);
  await signIn.click();
  await expect(page.locator('#username')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Sign in to FoodBridge' })).toBeVisible();
  expect(new URL(page.url()).origin).toBe('http://localhost:55173');
  expect(new URL(page.url()).pathname).toContain('/identity/realms/foodbridge/');
  await expect.poll(() => page.locator('#kc-login').evaluate(appearance)).toEqual(appButton);
  await expect(page.locator('body')).toHaveCSS('background-color', appBackground);
  await page.getByRole('button', { name: 'Show password', exact: true }).click();
  await expect(page.locator('#password')).toHaveAttribute('type', 'text');
  await page.getByRole('button', { name: 'Hide password', exact: true }).click();
  await expect(page.locator('#password')).toHaveAttribute('type', 'password');
  await page.screenshot({ path: 'test-results/identity-desktop.png', fullPage: true });
  expect(
    (await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze())
      .violations,
  ).toEqual([]);
  await page.locator('#username').fill('tej-demo');
  await page.locator('#password').fill('incorrect-local-test-password');
  await page.locator('#kc-login').click();
  await expect(page.locator('#input-error')).toBeVisible();
  await expect.poll(() => page.locator('#kc-login').evaluate(appearance)).toEqual(appButton);
  await page.setViewportSize({ width: 360, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  await expect(page.locator('#kc-login')).toHaveCSS('min-height', appButton.minHeight);
  await page.screenshot({ path: 'test-results/identity-error-mobile.png', fullPage: true });
  expect(
    (await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze())
      .violations,
  ).toEqual([]);
});

test('identity provider error pages retain the FoodBridge theme', async ({ page }) => {
  await page.goto('/donor');
  const background = await page
    .locator('.app-shell')
    .evaluate((element) => getComputedStyle(element).backgroundColor);
  const identity = process.env.FOODBRIDGE_KEYCLOAK_URL ?? 'http://localhost:55173/identity';
  await page.goto(
    `${identity}/realms/foodbridge/protocol/openid-connect/auth?client_id=nonexistent-local-test-client`,
  );
  await expect(page.locator('#kc-error-message')).toBeVisible();
  await expect(page.locator('.fb-auth-card')).toBeVisible();
  await expect(page.locator('body')).toHaveCSS('background-color', background);
  await page.screenshot({ path: 'test-results/identity-error-desktop.png', fullPage: true });
  expect(
    (await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze())
      .violations,
  ).toEqual([]);
});

test('OIDC login, scoped operations, driver delivery, SMTP capture and logout', async ({
  page,
}) => {
  test.setTimeout(120000);
  const foodName = `Synthetic release rice ${randomUUID().slice(0, 8)}`;
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.locator('#username').fill('tej-demo');
  await page.locator('#password').fill('foodbridge-local-only');
  await page.locator('#kc-login').click();
  await expect(page.getByRole('button', { name: 'Sign out of FoodBridge' })).toBeVisible();
  await page.getByRole('link', { name: 'Donor', exact: true }).click();
  await page
    .getByLabel('Food description')
    .fill(
      'Food: vegetable rice bowls. 20 boxed meals, 10 kg. Refrigerated. Vegetarian. Allergens: soy. Tomorrow pickup 10 AM to 12 PM. Use by 2 PM.',
    );
  await page.getByRole('button', { name: 'Review details', exact: true }).click();
  await expect(page.locator('#quantity_kg')).toHaveValue('10', { timeout: 45000 });
  await expect(
    page.getByRole('button', { name: 'Confirm and post donation', exact: true }),
  ).toBeDisabled();
  const cookies = await page.context().cookies();
  expect(cookies.find((c) => c.name === 'foodbridge_release_session')?.httpOnly).toBe(true);
  expect(await page.evaluate(() => Object.keys(localStorage).some((k) => /token/i.test(k)))).toBe(
    false,
  );
  const info = await page.request.get('/api/v1/auth/session');
  const memberships = (await info.json()).memberships as {
    organization_id: string;
    role: string;
  }[];
  expect(memberships).toHaveLength(4);
  const request = async (method: string, path: string, role = 'donor', body?: unknown) => {
    const membership = memberships.find((m) => m.role === role)!;
    const response = await page.request.fetch(`/api/v1${path}`, {
      method,
      headers: {
        'X-FoodBridge-Role': role,
        'X-Organization-ID': membership.organization_id,
        Origin: 'http://localhost:55173',
        ...(method === 'POST' ? { 'Idempotency-Key': randomUUID() } : {}),
      },
      data: body,
    });
    expect(response.ok(), `${method} ${path}: ${response.status()} ${await response.text()}`).toBe(
      true,
    );
    return response.json();
  };
  const mailpit = process.env.FOODBRIDGE_MAILPIT_URL ?? 'http://localhost:55173/test-inbox';
  const beforeMail = (await (await page.request.get(`${mailpit}/api/v1/messages`)).json()).total;
  const now = Date.now();
  const zone = 'America/Los_Angeles';
  await page.locator('#food_name').fill(foodName);
  await page.locator('#category').selectOption('prepared_meals');
  await page.locator('#quantity_kg').fill('1');
  await page.locator('#storage').selectOption('chilled');
  await page.locator('#allergens').fill('soy');
  await page.locator('#dietary_tags').fill('vegetarian');
  await page.locator('#start').fill(locationInput(new Date(now - 120000).toISOString(), zone));
  await page.locator('#end').fill(locationInput(new Date(now + 3600000).toISOString(), zone));
  await page
    .locator('#safe_use_by')
    .fill(locationInput(new Date(now + 7200000).toISOString(), zone));
  await page.getByRole('checkbox').check();
  const posted = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/v1/donations' &&
      response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Confirm and post donation', exact: true }).click();
  const submitted = await posted;
  expect(submitted.ok(), await submitted.text()).toBe(true);
  const id = (await submitted.json()).donation.id;
  cleanup = async () => {
    const member = memberships.find((m) => m.role === 'donor')!;
    const headers = {
      'X-FoodBridge-Role': 'donor',
      'X-Organization-ID': member.organization_id,
      Origin: 'http://localhost:55173',
    };
    const response = await page.request.get(`/api/v1/donations/${id}`, { headers });
    if (!response.ok()) return; // Successful logout intentionally removes cookie access.
    const current = (await response.json()).donation;
    if (
      ['submitted', 'matching', 'offered', 'reserved', 'pickup_assigned'].includes(current.status)
    ) {
      const cancelled = await page.request.post(`/api/v1/donations/${id}/cancel`, {
        headers: { ...headers, 'Idempotency-Key': randomUUID() },
        data: { expected_donation_version: current.version },
      });
      expect([200, 409]).toContain(cancelled.status());
    }
  };
  await expect
    .poll(async () => (await request('GET', `/donations/${id}`)).donation.status, {
      timeout: 45000,
    })
    .toBe('offered');
  await page.getByRole('link', { name: 'Receiver', exact: true }).click();
  const receiver = page.getByRole('article').filter({ hasText: foodName }).first();
  await receiver.getByRole('button', { name: 'Accept offer', exact: true }).click();
  await receiver.getByRole('button', { name: 'Confirm accept offer' }).click();
  await expect(
    page.getByText('Reservation confirmed. Driver coordination is underway.'),
  ).toBeVisible();
  await expect
    .poll(
      async () =>
        (await request('GET', '/pickups?limit=100', 'driver')).items.some(
          (p: { donation_id: string }) => p.donation_id === id,
        ),
      { timeout: 45000 },
    )
    .toBe(true);
  await page.getByRole('link', { name: 'Driver', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Every pickup makes a difference.' }),
  ).toBeVisible();
  const card = page.locator('article').filter({ hasText: foodName }).first();
  await expect(card.getByText(/Deliver to /)).toBeVisible();
  await card.getByRole('button', { name: 'Accept assignment' }).click();
  await card.getByRole('checkbox').check();
  await card.getByRole('button', { name: 'Confirm pickup', exact: true }).click();
  await expect(card.getByRole('button', { name: 'Confirm delivery', exact: true })).toBeVisible();
  await card.getByRole('button', { name: 'Confirm delivery', exact: true }).click();
  await card.getByRole('button', { name: 'Confirm delivery', exact: true }).click();
  await expect
    .poll(async () => (await request('GET', `/donations/${id}`)).donation.status)
    .toBe('delivered');
  await page.getByRole('link', { name: 'Operations', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'The whole picture. Every handoff.' }),
  ).toBeVisible();
  const row = page.getByRole('article').filter({ hasText: foodName }).first();
  await expect(row).toContainText('Delivered');
  await row.getByRole('button', { name: 'View donation history' }).click();
  await expect(page.getByRole('region', { name: 'Donation history' })).toContainText('Delivered');
  const audits = await request(
    'GET',
    `/operations/orchestrator/decisions?donation_id=${id}`,
    'operator',
  );
  expect(audits.length).toBeGreaterThan(0);
  const cross = await page.request.get('/api/v1/operations/donations', {
    headers: { 'X-FoodBridge-Role': 'operator', 'X-Organization-ID': randomUUID() },
  });
  expect(cross.status()).toBe(403);
  const csrf = await page.request.post('/api/v1/auth/logout', {
    headers: { Origin: 'https://evil.example' },
  });
  expect(csrf.status()).toBe(403);
  await expect
    .poll(
      async () => {
        const response = await page.request.get(`${mailpit}/api/v1/messages`);
        return (await response.json()).total;
      },
      { timeout: 30000 },
    )
    .toBeGreaterThan(beforeMail);
  await expect(page.getByRole('status').filter({ hasText: 'Live' })).toBeVisible();
  await page.route('**/api/v1/events', (route) => route.abort());
  await page.reload();
  await expect(page.getByRole('status').filter({ hasText: 'Reconnecting' })).toBeVisible();
  await page.unroute('**/api/v1/events');
  await expect(page.getByRole('status').filter({ hasText: 'Live' })).toBeVisible({
    timeout: 15000,
  });
  await expect(page.getByRole('article').filter({ hasText: foodName }).first()).toContainText(
    'Delivered',
  );
  await page.screenshot({ path: 'test-results/release-operations-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 360, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  await page.getByRole('button', { name: 'Sign out of FoodBridge', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
  expect((await (await page.request.get('/api/v1/auth/session')).json()).authenticated).toBe(false);
  expect(errors).toEqual([]);
});

test('email-first signup, resend, verified access gate and password recovery use real SMTP', async ({
  page,
  browser,
}) => {
  test.setTimeout(150000);
  const identity = process.env.FOODBRIDGE_KEYCLOAK_URL ?? 'http://localhost:55173/identity';
  const inbox = process.env.FOODBRIDGE_MAILPIT_URL ?? 'http://localhost:55173/test-inbox';
  const username = `signup-${randomUUID().slice(0, 12)}`;
  const email = `${username}@example.test`;
  const password = 'Synthetic-first-password-2026';
  const replacement = 'Synthetic-recovered-password-2026';
  const messages = async () => {
    const body = await (await page.request.get(`${inbox}/api/v1/messages?limit=200`)).json();
    return body.messages.filter((m: { To: { Address: string }[] }) =>
      m.To.some((t) => t.Address === email),
    );
  };
  const emailLink = async (count: number) => {
    await expect.poll(async () => (await messages()).length).toBe(count);
    const latest = (await messages())[0];
    const mail = await (await page.request.get(`${inbox}/api/v1/message/${latest.ID}`)).json();
    const links = [...mail.HTML.matchAll(/href="([^"]+)"/g)].map((m) =>
      m[1].replaceAll('&amp;', '&'),
    );
    const link = links.find((value) => value.includes('/login-actions/action-token'));
    if (!link) throw new Error('Expected native identity action in captured email');
    const url = new URL(link);
    expect(url.origin).toBe(new URL(identity).origin);
    expect(url.pathname).toBe(
      `${new URL(identity).pathname}/realms/foodbridge/login-actions/action-token`,
    );
    return link;
  };
  const accessible = async () => {
    await expect(page.locator('.fb-auth-card')).toBeVisible();
    await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(248, 250, 247)');
    expect(
      (await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze())
        .violations,
    ).toEqual([]);
  };
  await page.goto('/donor');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByText(/Enter your details first/)).toBeVisible();
  await accessible();
  for (const [id, value] of Object.entries({
    username,
    email,
    firstName: 'Synthetic',
    lastName: 'Account',
  }))
    await page.locator(`#${id}`).fill(value);
  await page.locator('#kc-register-form input[type=submit]').click();
  await expect(
    page.getByRole('heading', { name: 'Email verification', exact: true }),
  ).toBeVisible();
  expect((await (await page.request.get('/api/v1/auth/session')).json()).authenticated).toBe(false);
  await emailLink(1);
  await accessible();
  await page.setViewportSize({ width: 360, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  await page.screenshot({ path: 'test-results/account-verification-mobile.png', fullPage: true });
  // Keycloak enforces its native resend cooldown; do not bypass it in the test.
  await page.waitForTimeout(31000);
  await page.getByRole('link', { name: 'Resend verification email', exact: true }).click();
  const verificationLink = await emailLink(2);
  const invalid = new URL(verificationLink);
  const parts = invalid.searchParams.get('key')!.split('.');
  parts[2] = (parts[2][0] === 'a' ? 'b' : 'a') + parts[2].slice(1);
  invalid.searchParams.set('key', parts.join('.'));
  const stranger = await browser.newContext();
  const strangerPage = await stranger.newPage();
  await strangerPage.goto(invalid.toString());
  await expect(strangerPage.locator('#kc-error-message')).toBeVisible();
  expect(
    (await (await strangerPage.request.get('http://localhost:55173/api/v1/auth/session')).json())
      .authenticated,
  ).toBe(false);
  await stranger.close();
  await page.goto(verificationLink);
  await expect(page.locator('#password-new')).toBeVisible();
  await accessible();
  await page.locator('#password-new').fill(password);
  await page.locator('#password-confirm').fill(password);
  await page.locator('#kc-passwd-update-form input[type=submit]').click();
  await expect(
    page.getByRole('heading', { name: 'You’re signed in. Workspace access is next.' }),
  ).toBeVisible({ timeout: 15000 });
  const session = await (await page.request.get('/api/v1/auth/session')).json();
  expect(session.authenticated).toBe(true);
  expect(session.memberships).toEqual([]);
  await page.getByRole('button', { name: 'Sign out of FoodBridge' }).click();
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
  // App logout does not erase the identity provider’s SSO cookie. Test recovery
  // as a person returning in a fresh browser without that identity session.
  const recoveryContext = await browser.newContext({ baseURL: 'http://localhost:55173' });
  page = await recoveryContext.newPage();
  await page.goto('/donor');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('link', { name: 'Forgot password?', exact: true }).click();
  await accessible();
  await page.locator('#username').fill(email);
  await page.locator('#kc-reset-password-form input[type=submit]').click();
  await expect(page.locator('.fb-auth-notice')).toContainText(/receive an email/i);
  const resetLink = await emailLink(3);
  await page.goto(resetLink);
  await page.locator('#password-new').fill(replacement);
  await page.locator('#password-confirm').fill(replacement);
  await page.locator('#kc-passwd-update-form input[type=submit]').click();
  // A fresh browser proves the recovered credential works, independently of SSO.
  const recovered = await browser.newContext();
  const recoveredPage = await recovered.newPage();
  await recoveredPage.goto('http://localhost:55173/donor');
  await recoveredPage.getByRole('button', { name: 'Sign in', exact: true }).click();
  await recoveredPage.locator('#username').fill(username);
  await recoveredPage.locator('#password').fill(password);
  await recoveredPage.locator('#kc-login').click();
  await expect(recoveredPage.locator('#input-error')).toBeVisible();
  await recoveredPage.locator('#password').fill(replacement);
  await recoveredPage.locator('#kc-login').click();
  await expect(
    recoveredPage.getByRole('heading', { name: 'You’re signed in. Workspace access is next.' }),
  ).toBeVisible();
  await recovered.close();
  await page.goto(resetLink);
  await expect(page.locator('#password-new')).toHaveCount(0);
  await recoveryContext.close();
});

test('forgot-password confirmation does not disclose an unknown account', async ({ page }) => {
  const email = `missing-${randomUUID()}@example.test`;
  await page.goto('/donor');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('link', { name: 'Forgot password?', exact: true }).click();
  await page.locator('#username').fill(email);
  await page.locator('#kc-reset-password-form input[type=submit]').click();
  await expect(page.locator('.fb-auth-notice')).toContainText(
    'You should receive an email shortly with further instructions.',
  );
  const inbox = process.env.FOODBRIDGE_MAILPIT_URL ?? 'http://localhost:55173/test-inbox';
  const body = await (await page.request.get(`${inbox}/api/v1/messages?limit=200`)).json();
  expect(
    body.messages.some((m: { To: { Address: string }[] }) => m.To.some((t) => t.Address === email)),
  ).toBe(false);
});
