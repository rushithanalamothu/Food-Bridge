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
  await page.goto('/driver');
  await expect(page.getByText('Sign in to access your organization’s workspace.')).toBeVisible();
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
