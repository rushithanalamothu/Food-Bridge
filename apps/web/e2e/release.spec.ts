import { expect, test } from '@playwright/test';
import { randomUUID } from 'node:crypto';

let cleanup: (() => Promise<void>) | undefined;
test.afterEach(async () => {
  if (cleanup) await cleanup();
  cleanup = undefined;
});

test('OIDC login, scoped operations, driver delivery, SMTP capture and logout', async ({
  page,
}) => {
  test.setTimeout(120000);
  const foodName = `Synthetic release rice ${randomUUID().slice(0, 8)}`;
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/');
  await page.getByRole('link', { name: 'Sign in to FoodBridge' }).click();
  await page.locator('#username').fill('tej-demo');
  await page.locator('#password').fill('foodbridge-local-only');
  await page.locator('#kc-login').click();
  await expect(page.getByText('Signed in', { exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Donor', exact: true }).click();
  await page
    .getByLabel('Food description')
    .fill(
      'Food: vegetable rice bowls. 20 boxed meals, 10 kg. Refrigerated. Vegetarian. Allergens: soy. Tomorrow pickup 10 AM to 12 PM. Use by 2 PM.',
    );
  await page.getByRole('button', { name: 'Review details', exact: true }).click();
  await expect(page.locator('#quantity_kg')).toHaveValue('10');
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
  const mailpit = process.env.FOODBRIDGE_MAILPIT_URL ?? 'http://127.0.0.1:58025';
  const beforeMail = (await (await page.request.get(`${mailpit}/api/v1/messages`)).json()).total;
  const donor = await request('GET', '/me');
  const now = Date.now();
  const description =
    'Synthetic release verification: vegetarian rice, 1 kg, chilled, allergens soy.';
  const draft = await request('POST', '/donation-drafts', 'donor', {
    description,
    pickup_location: donor.pickup_location,
  });
  const submitted = await request('POST', '/donations', 'donor', {
    draft_id: draft.id,
    expected_draft_version: draft.version,
    confirmed: true,
    donation: {
      description,
      food_name: foodName,
      category: 'prepared_meals',
      quantity_kg: 1,
      storage: 'chilled',
      dietary_tags: ['vegetarian'],
      allergens: ['soy'],
      pickup_location: donor.pickup_location,
      pickup_window: {
        start: new Date(now - 60000).toISOString(),
        end: new Date(now + 7200000).toISOString(),
      },
      safe_use_by: new Date(now + 10800000).toISOString(),
    },
  });
  const id = submitted.donation.id;
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
  const donated = await request('GET', `/donations/${id}`);
  const offers = await request('GET', '/matches?limit=100', 'recipient');
  const offer = offers.items.find(
    (item: { recommendation: { donation_id: string } }) => item.recommendation.donation_id === id,
  );
  await request('POST', '/reservations', 'recipient', {
    match_id: offer.recommendation.id,
    expected_donation_version: donated.donation.version,
  });
  await expect
    .poll(
      async () =>
        (await request('GET', '/pickups?limit=100', 'driver')).items.some(
          (p: { donation_id: string }) => p.donation_id === id,
        ),
      { timeout: 45000 },
    )
    .toBe(true);
  const driver = memberships.find((m) => m.role === 'driver')!;
  await page.getByLabel('Workspace identity').selectOption(`${driver.organization_id}:driver`);
  await expect(page.getByRole('heading', { name: 'Your pickups' })).toBeVisible();
  const card = page.locator('article').filter({ hasText: foodName }).first();
  await expect(card.getByText(/Deliver to:/)).toBeVisible();
  await card.getByRole('button', { name: 'Accept assignment' }).click();
  await card.getByRole('checkbox').check();
  await card.getByRole('button', { name: 'Confirm pickup', exact: true }).click();
  await expect(card.getByRole('button', { name: 'Confirm delivery', exact: true })).toBeVisible();
  await card.getByRole('checkbox').check();
  await card.getByRole('button', { name: 'Confirm delivery', exact: true }).click();
  await expect
    .poll(async () => (await request('GET', `/donations/${id}`)).donation.status)
    .toBe('delivered');
  const operator = memberships.find((m) => m.role === 'operator')!;
  await page.getByLabel('Workspace identity').selectOption(`${operator.organization_id}:operator`);
  await expect(page.getByRole('heading', { name: 'Today’s operations' })).toBeVisible();
  const row = page.getByRole('row').filter({ hasText: foodName }).first();
  await expect(row).toContainText('delivered');
  await row.getByRole('button', { name: 'View history' }).click();
  await expect(page.getByRole('heading', { name: 'Donation history', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Orchestrator decisions' })).toBeVisible();
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
  await expect(page.getByRole('status').filter({ hasText: 'Disconnected' })).toBeVisible();
  await page.unroute('**/api/v1/events');
  await expect(page.getByRole('status').filter({ hasText: 'Live' })).toBeVisible({
    timeout: 15000,
  });
  await expect(page.getByRole('row').filter({ hasText: foodName }).first()).toContainText(
    'delivered',
  );
  await page.screenshot({ path: 'test-results/release-operations-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 360, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Sign in to FoodBridge' })).toBeVisible();
  expect((await (await page.request.get('/api/v1/auth/session')).json()).authenticated).toBe(false);
  expect(errors).toEqual([]);
});
