import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { fixtures } from './fixtures';

test('driver starting point validates input and saves a versioned, idempotent location', async ({
  page,
}) => {
  const state = await fixtures(page);
  await page.goto('/driver');
  await expect(page.getByText('No starting point saved.', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Update starting point', exact: true }).click();
  await page.getByLabel('Starting point description').fill('Synthetic driver depot');
  await page.getByLabel('Starting latitude').fill('91');
  await page.getByLabel('Starting longitude').fill('-121.89');
  await page.getByRole('button', { name: 'Save starting point', exact: true }).click();
  expect(state.commands).toHaveLength(0);
  await page.getByLabel('Starting latitude').fill('37.332');
  await page.getByLabel('Starting point timezone').fill('Invalid/Zone');
  await page.getByRole('button', { name: 'Save starting point', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Enter a valid location timezone');
  expect(state.commands).toHaveLength(0);
  await page.getByLabel('Starting point timezone').fill('America/Los_Angeles');
  const request = page.waitForRequest(
    (r) => r.method() === 'POST' && r.url().endsWith('/driver-origin'),
  );
  await page.getByRole('button', { name: 'Save starting point', exact: true }).click();
  const headers = (await request).headers();
  expect(headers['x-foodbridge-role']).toBe('driver');
  expect(headers['idempotency-key']).toBeTruthy();
  await expect(page.getByRole('status').filter({ hasText: 'Starting point saved.' })).toBeVisible();
  expect(state.commands[0].body).toMatchObject({
    expected_version: 1,
    origin: { latitude: 37.332, longitude: -121.89 },
  });
  await page.reload();
  await expect(page.getByText('Synthetic driver depot', { exact: false })).toBeVisible();
  await expect(page.getByText('No starting point saved.', { exact: false })).toHaveCount(0);
});

test('driver version conflict requires reloading current facts before another save', async ({
  page,
}) => {
  const state = await fixtures(page);
  state.driverOrigin.origin = { ...state.donation.pickup_location, address: 'Old synthetic depot' };
  state.driverOrigin.observed_at = new Date(Date.now() - 360000).toISOString();
  await page.goto('/driver');
  await expect(
    page.getByText('Your starting point is out of date.', { exact: false }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Update starting point', exact: true }).click();
  state.driverOrigin.version++;
  state.driverOrigin.origin.address = 'Concurrent synthetic depot';
  await page.getByRole('button', { name: 'Save starting point', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Your driver details changed');
  await expect(
    page.getByRole('button', { name: 'Save starting point', exact: true }),
  ).toBeDisabled();
  await page.getByRole('button', { name: 'Reload starting point', exact: true }).click();
  await expect(page.getByLabel('Starting point description')).toHaveValue(
    'Concurrent synthetic depot',
  );
  await page.getByRole('button', { name: 'Save starting point', exact: true }).click();
  await expect(page.getByText('Starting point saved.', { exact: false })).toBeVisible();
  await expect(page.getByText('Your starting point is out of date.', { exact: false })).toHaveCount(
    0,
  );
});

test('starting point load failure can be retried without blocking driver assignments', async ({
  page,
}) => {
  const state = await fixtures(page);
  let fail = true;
  await page.route('**/api/v1/driver-origin', (route) =>
    route.fulfill(
      fail
        ? {
            status: 503,
            json: { code: 'unavailable', message: 'Starting point service unavailable.' },
          }
        : { json: state.driverOrigin },
    ),
  );
  await page.goto('/driver');
  await expect(page.getByRole('alert')).toContainText('Starting point service unavailable.');
  await expect(page.getByRole('button', { name: 'Accept assignment', exact: true })).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Update starting point', exact: true }),
  ).toBeDisabled();
  fail = false;
  await page.getByRole('button', { name: 'Reload starting point', exact: true }).click();
  await expect(
    page.getByRole('button', { name: 'Update starting point', exact: true }),
  ).toBeEnabled();
});

test('starting point form fits a narrow viewport and has accessible controls', async ({ page }) => {
  await fixtures(page);
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto('/driver');
  await page.getByRole('button', { name: 'Update starting point', exact: true }).click();
  await expect(page.getByLabel('Starting latitude')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(results.violations).toEqual([]);
});
