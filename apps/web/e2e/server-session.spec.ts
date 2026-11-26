import { expect, test } from '@playwright/test';
import { fixtures } from './fixtures';

test('gateway sessions use cookies, preserve organization scope and report failed logout', async ({
  page,
}) => {
  await fixtures(page);
  let signedIn = true;
  let logoutFails = true;
  await page.route('**/api/v1/auth/session', (route) =>
    route.fulfill({
      json: { login_enabled: true, authenticated: signedIn, mode: 'oidc', memberships: [] },
    }),
  );
  await page.route('**/api/v1/auth/logout', async (route) => {
    expect(route.request().method()).toBe('POST');
    expect(route.request().headers().authorization).toBeUndefined();
    if (logoutFails) return route.fulfill({ status: 503, json: { code: 'unavailable' } });
    signedIn = false;
    return route.fulfill({ json: { authenticated: false } });
  });
  await page.goto('/driver');
  await expect(
    page.getByRole('heading', { name: 'Every pickup makes a difference.' }),
  ).toBeVisible();
  const request = page.waitForRequest((r) => new URL(r.url()).pathname === '/api/v1/pickups');
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  const headers = (await request).headers();
  expect(headers.authorization).toBeUndefined();
  expect(headers['x-foodbridge-role']).toBe('driver');
  expect(headers['x-organization-id']).toBeTruthy();
  await page.getByRole('button', { name: 'Sign out of FoodBridge' }).click();
  await expect(page.getByRole('alert')).toContainText('Sign-out could not be completed');
  await expect(page.getByRole('button', { name: 'Sign out of FoodBridge' })).toBeVisible();
  logoutFails = false;
  await page.getByRole('button', { name: 'Sign out of FoodBridge' }).click();
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Every pickup makes a difference.' })).toHaveCount(
    0,
  );
});

test('gateway sign-in blocks role workspaces until authenticated', async ({ page }) => {
  await fixtures(page);
  await page.route('**/api/v1/auth/session', (route) =>
    route.fulfill({
      json: { login_enabled: true, authenticated: false, mode: null, memberships: [] },
    }),
  );
  let scopedRequests = 0;
  page.on('request', (request) => {
    if (/\/api\/v1\/(memberships|pickups|events)(\?|$)/.test(request.url())) scopedRequests++;
  });
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto('/driver');
  await expect(page.getByText('Sign in to access your organization’s workspace.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toHaveCount(1);
  const frame = await page.locator('.app-shell').boundingBox();
  expect(frame?.x).toBe(0);
  expect(frame?.width).toBe(1920);
  const footer = await page.locator('footer').boundingBox();
  expect(Math.round((footer?.y ?? 0) + (footer?.height ?? 0))).toBe(1080);
  await page.setViewportSize({ width: 360, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  await page.getByRole('link', { name: 'Receiver', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'More good food. More people around the table.' }),
  ).toBeVisible();
  await expect(page.getByRole('link', { name: 'Receiver', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  );
  expect(scopedRequests).toBe(0);
});

test('session-service outage fails closed rather than opening a demo workspace', async ({
  page,
}) => {
  await fixtures(page);
  await page.route('**/api/v1/auth/session', (route) => route.fulfill({ status: 503, json: {} }));
  await page.goto('/driver');
  await expect(page.getByRole('alert')).toContainText('Could not check your session');
  await expect(page.getByRole('heading', { name: 'Every pickup makes a difference.' })).toHaveCount(
    0,
  );
});

for (const enabled of [false, true]) {
  test(`account creation entry respects provider capability: ${enabled}`, async ({ page }) => {
    await fixtures(page);
    await page.route('**/api/v1/auth/session', (route) =>
      route.fulfill({
        json: {
          login_enabled: true,
          registration_enabled: enabled,
          authenticated: false,
          memberships: [],
        },
      }),
    );
    await page.goto('/donor');
    await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Create account', exact: true })).toHaveCount(
      enabled ? 1 : 0,
    );
  });
}

test('signed-in accounts without membership remain outside protected workspaces and can retry access', async ({
  page,
}) => {
  await fixtures(page);
  let granted = false;
  let membershipReads = 0;
  let protectedReads = 0;
  await page.route('**/api/v1/auth/session', (route) =>
    route.fulfill({
      json: {
        login_enabled: true,
        registration_enabled: true,
        authenticated: true,
        memberships: [],
      },
    }),
  );
  await page.route('**/api/v1/memberships', (route) => {
    membershipReads++;
    return granted ? route.fallback() : route.fulfill({ json: [] });
  });
  page.on('request', (request) => {
    if (
      /\/api\/v1\/(me|donations|offers|pickups|driver-origin|operations)(\/|\?|$)/.test(
        new URL(request.url()).pathname,
      )
    )
      protectedReads++;
  });
  await page.goto('/donor');
  await expect(
    page.getByRole('heading', { name: 'You’re signed in. Workspace access is next.' }),
  ).toBeVisible();
  expect(protectedReads).toBe(0);
  await page.getByRole('button', { name: 'Check access again' }).click();
  await expect.poll(() => membershipReads).toBeGreaterThan(1);
  expect(protectedReads).toBe(0);
  const driverMemberships = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/v1/memberships' &&
      response.request().headers()['x-foodbridge-role'] === 'driver',
  );
  await page.getByRole('link', { name: 'Driver', exact: true }).click();
  await driverMemberships;
  await expect(
    page.getByRole('heading', { name: 'You’re signed in. Workspace access is next.' }),
  ).toBeVisible();
  expect(protectedReads).toBe(0);
  granted = true;
  await page.getByRole('button', { name: 'Check access again' }).click();
  await expect(
    page.getByRole('heading', { name: 'Every pickup makes a difference.' }),
  ).toBeVisible();
});
