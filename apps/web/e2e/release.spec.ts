import { expect, test } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { locationInput } from '../src/api/time';

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
  const mailpit = process.env.FOODBRIDGE_MAILPIT_URL ?? 'http://127.0.0.1:58025';
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
