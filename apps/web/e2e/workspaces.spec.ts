import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { fixtures, matchId } from './fixtures';

test('receiver acceptance survives reload and can release the persisted hold', async ({ page }) => {
  const state = await fixtures(page);
  await page.goto('/recipient');
  await page.getByRole('button', { name: 'Accept offer', exact: true }).click();
  expect(state.commands).toHaveLength(0);
  await page.getByRole('button', { name: 'Confirm accept offer' }).click();
  await expect(page.getByText('10 kg reserved')).toBeVisible();
  expect(state.commands[0].body).toEqual({ match_id: matchId, expected_donation_version: 4 });
  expect(state.commands[0].key).toBeTruthy();
  await page.reload();
  await page.getByRole('button', { name: 'Release reservation', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm release reservation' }).click();
  await expect(page.getByText('Reservation released.', { exact: true })).toBeVisible();
  expect(state.commands[1].body).toEqual({ expected_version: 1 });
});
test('receiver edits capacity and receiving preferences using current versions', async ({
  page,
}) => {
  const state = await fixtures(page);
  await page.goto('/recipient');
  await page.getByRole('button', { name: 'Edit preferences' }).click();
  await page.getByLabel('Chilled free storage (kg)').fill('30');
  await page.getByRole('button', { name: 'Save preferences' }).click();
  await expect(page.getByText('Receiving preferences saved.')).toBeVisible();
  expect(state.commands[0].body).toMatchObject({
    expected_version: 1,
    expected_capacity_versions: { chilled: 1 },
    reported_free_kg_by_storage: { chilled: 30 },
  });
});
test('receiver refreshes expired offer conflicts without claiming success', async ({ page }) => {
  const state = await fixtures(page);
  await page.route('**/api/v1/reservations', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    state.offers[0].status = 'expired';
    await route.fulfill({
      status: 409,
      json: { code: 'offer_expired', message: 'This offer expired. Refresh.' },
    });
  });
  await page.goto('/recipient');
  await page.getByRole('button', { name: 'Accept offer', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm accept offer' }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'This offer expired' })).toBeVisible();
  await expect(page.getByText('Expired', { exact: true })).toBeVisible();
});
test('driver accepts, confirms handling and weight, then delivers on mobile', async ({ page }) => {
  const state = await fixtures(page);
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto('/driver');
  await expect(page.getByText('Synthetic receiving center')).toBeVisible();
  await page.getByRole('button', { name: 'Accept assignment', exact: true }).click();
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Confirm pickup', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm delivery', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm delivery', exact: true }).click();
  await expect(page.getByText('Delivered', { exact: true })).toBeVisible();
  expect(state.commands.map((c) => c.body)).toEqual([
    { expected_version: 1 },
    { expected_version: 2, observed_quantity_kg: 10, handling_confirmed: true },
    { expected_version: 3, delivery_confirmed: true },
  ]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
});
test('operations displays scoped board, full history, synthetic impact and decision audit', async ({
  page,
}) => {
  await fixtures(page);
  await page.goto('/operations');
  await expect(page.getByText('Synthetic demonstration data', { exact: false })).toBeVisible();
  await expect(page.getByText('20 kg', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'View donation history' }).click();
  await expect(page.getByRole('region', { name: 'Donation history' })).toContainText(
    'Donor Confirmed',
  );
  await page.getByRole('button', { name: 'Review workflow' }).click();
  await expect(page.getByRole('heading', { name: /Workflow decisions/ })).toBeVisible();
});
test('newest offers remain visible after SSE replay and expired-cursor recovery', async ({
  page,
}) => {
  const state = await fixtures(page);
  let expired = false;
  const cursors: (string | undefined)[] = [];
  await page.route('**/api/v1/events', async (route) => {
    const cursor = route.request().headers()['last-event-id'];
    cursors.push(cursor);
    // React StrictMode can abort an initial connection before its first frame is read.
    // Drive the fixture by acknowledged cursors rather than the number of requests.
    if (cursor === '41' && !expired) {
      expired = true;
      return route.fulfill({ status: 409, json: { code: 'stream_cursor_expired' } });
    }
    if (cursor === '42') return route.fulfill({ status: 401, json: {} });
    if (expired) state.offers[0].donation.food_name = 'Updated from authoritative snapshot';
    const id = expired ? '42' : '41';
    const data = `id: ${id}\nevent: status\ndata: ${JSON.stringify({ event_id: 'event-' + id, aggregate_id: state.donation.id, aggregate_version: 5, payload: { status: 'offered' } })}\n\n`;
    return route.fulfill({ contentType: 'text/event-stream', body: data + data });
  });
  await page.goto('/recipient');
  await expect(
    page.getByRole('heading', { name: 'Updated from authoritative snapshot' }),
  ).toBeVisible({ timeout: 15000 });
  expect(cursors).toContain('41');
  expect(cursors[cursors.indexOf('41') + 1]).toBeUndefined();
  await expect(page.getByText(/Session unavailable/)).toBeVisible();
});
test('pagination loads older offers while new live offers reset to the latest page', async ({
  page,
}) => {
  const state = await fixtures(page);
  const original = state.offers[0];
  state.offers = Array.from({ length: 26 }, (_, i) => ({
    ...original,
    recommendation: { ...original.recommendation, id: String(i), donation_id: 'donation-' + i },
    donation: { ...state.donation, food_name: 'Synthetic offer ' + i },
  }));
  await page.goto('/recipient');
  await page.getByRole('button', { name: 'Load older offers' }).click();
  await expect(
    page.getByRole('heading', { name: 'Synthetic offer 25', exact: true }),
  ).toBeVisible();
  state.offers.unshift({
    ...original,
    donation: { ...state.donation, food_name: 'Newest donation' },
  });
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Newest donation' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Synthetic offer 25', exact: true })).toHaveCount(
    0,
  );
});
for (const path of ['/donor', '/recipient', '/driver', '/operations']) {
  test(`keyboard navigation and accessibility at ${path}`, async ({ page }) => {
    await fixtures(page);
    await page.goto(path);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await page.keyboard.press('Tab');
    await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.locator('#content')).toBeFocused();
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze();
    expect(results.violations).toEqual([]);
    await page.setViewportSize({ width: 360, height: 800 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      360,
    );
  });
}
