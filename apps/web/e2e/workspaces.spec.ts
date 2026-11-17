import { expect, test, type Page } from '@playwright/test';

// Contract-shaped synthetic fixtures; real-worker coverage remains in intake.spec.ts.
const org = '00000000-0000-4000-8000-000000000001';
const donationId = '00000000-0000-4000-8000-000000000002';
const matchId = '00000000-0000-4000-8000-000000000003';
const tomorrow = () => new Date(Date.now() + 86400000).toISOString();
async function shell(page: Page) {
  await page.route('**/api/v1/session', (route) =>
    route.fulfill({
      json: {
        user_id: org,
        organization_id: org,
        role: route.request().headers()['x-foodbridge-role'],
      },
    }),
  );
  await page.route('**/api/v1/events', (route) =>
    route.fulfill({ status: 403, json: { code: 'test_no_stream' } }),
  );
}

test('receiver confirms acceptance, sends the donation version and releases the hold', async ({
  page,
}) => {
  await shell(page);
  let status = 'offered';
  const commands: { path: string; body: Record<string, unknown>; key: string | undefined }[] = [];
  const offer = () => ({
    version: 1,
    status,
    recommendation: {
      id: matchId,
      donation_id: donationId,
      donation_version: 4,
      matching_round: 1,
      recipient_organization_id: org,
      distance_m: 2000,
      travel_time_s: 300,
      offer_expires_at: tomorrow(),
      explanation: 'SYNTHETIC fixture: eligible receiver.',
      algorithm: 'distance_only',
      eligibility_policy_version: 'eligibility-v2',
      ranking_config_version: 'fixture-v1',
    },
  });
  await page.route('**/api/v1/matches', (route) =>
    route.fulfill({ json: { items: [offer()], next_cursor: null } }),
  );
  await page.route('**/api/v1/reservations**', async (route) => {
    commands.push({
      path: new URL(route.request().url()).pathname,
      body: route.request().postDataJSON(),
      key: route.request().headers()['idempotency-key'],
    });
    status = 'accepted';
    await route.fulfill({
      json: {
        id: 'reservation',
        match_id: matchId,
        donation_id: donationId,
        recipient_organization_id: org,
        status: commands.length > 1 ? 'released' : 'active',
        quantity_kg: 10,
        storage: 'chilled',
        version: 1,
        donation_version: 5,
        created_at: new Date().toISOString(),
      },
    });
  });
  await page.goto('/recipient');
  await page.getByRole('button', { name: 'Accept offer', exact: true }).click();
  expect(commands).toHaveLength(0);
  await page.getByRole('button', { name: 'Confirm accept offer' }).click();
  await expect(page.getByText('10 kg reserved')).toBeVisible();
  expect(commands[0].body).toEqual({ match_id: matchId, expected_donation_version: 4 });
  expect(commands[0].key).toBeTruthy();
  await page.getByRole('button', { name: 'Release reservation', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm release reservation' }).click();
  await expect(page.getByText('Reservation released.', { exact: true })).toBeVisible();
  expect(commands[1].body).toEqual({ expected_version: 1 });
});

test('receiver refreshes an expired offer after conflict without claiming success', async ({
  page,
}) => {
  await shell(page);
  let status = 'offered';
  let reads = 0;
  await page.route('**/api/v1/matches', (route) => {
    reads++;
    return route.fulfill({
      json: {
        items: [
          {
            status,
            version: 1,
            recommendation: {
              id: matchId,
              donation_id: donationId,
              donation_version: 2,
              matching_round: 1,
              distance_m: 100,
              travel_time_s: 20,
              offer_expires_at: tomorrow(),
              explanation: 'Synthetic offer',
              algorithm: 'distance_only',
            },
          },
        ],
        next_cursor: null,
      },
    });
  });
  await page.route('**/api/v1/reservations', (route) => {
    status = 'expired';
    return route.fulfill({
      status: 409,
      json: { code: 'offer_expired', message: 'This offer expired. Refresh.' },
    });
  });
  await page.goto('/recipient');
  await page.getByRole('button', { name: 'Accept offer', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm accept offer' }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'This offer expired' })).toBeVisible();
  await expect(page.getByText('Expired', { exact: true })).toBeVisible();
  expect(reads).toBeGreaterThan(1);
  await expect(page.getByText('Reservation confirmed.')).toHaveCount(0);
});

test('driver accepts, confirms handling and weight, then confirms delivery on mobile', async ({
  page,
}) => {
  await shell(page);
  await page.setViewportSize({ width: 360, height: 800 });
  let status = 'assigned';
  let version = 1;
  const commands: Record<string, unknown>[] = [];
  const food = {
    id: donationId,
    donor_organization_id: org,
    food_name: 'Synthetic rice bowls',
    quantity_kg: 10,
    portions: 20,
    packaging_type: 'boxed',
    storage: 'chilled',
    allergens: ['soy'],
    dietary_tags: [],
    pickup_location: { address: 'Synthetic pickup kitchen', timezone: 'America/Los_Angeles' },
    pickup_window: { start: new Date(Date.now() - 60000).toISOString(), end: tomorrow() },
    safe_use_by: tomorrow(),
    handling_notes: 'Keep chilled',
    status: 'pickup_assigned',
    version: 5,
    created_at: new Date().toISOString(),
  };
  await page.route('**/api/v1/pickups', (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: 'pickup',
            donation_id: donationId,
            driver_id: org,
            reservation_id: 'reservation',
            status,
            version,
            start: food.pickup_window.start,
            end: tomorrow(),
            donation: food,
          },
        ],
        next_cursor: null,
      },
    }),
  );
  await page.route('**/api/v1/pickups/pickup/**', (route) => {
    commands.push(route.request().postDataJSON());
    const verb = route.request().url().split('/').pop();
    status = verb === 'accept' ? 'accepted' : verb === 'confirm-pickup' ? 'collected' : 'delivered';
    version++;
    return route.fulfill({ json: {} });
  });
  await page.goto('/driver');
  await page.getByRole('button', { name: 'Accept assignment', exact: true }).click();
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Confirm pickup', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm delivery', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm delivery', exact: true }).click();
  await expect(page.getByText('Delivered', { exact: true })).toBeVisible();
  expect(commands).toEqual([
    { expected_version: 1 },
    { expected_version: 2, observed_quantity_kg: 10, handling_confirmed: true },
    { expected_version: 3, delivery_confirmed: true },
  ]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
});

test('operations labels synthetic impact and displays scoped failures and audit', async ({
  page,
}) => {
  await shell(page);
  await page.route('**/api/v1/operations/summary', (route) =>
    route.fulfill({
      json: {
        organization_id: org,
        counts_by_status: { delivered: 2, matching: 1 },
        delivered_kg: 20,
        delivered_count: 2,
        synthetic: true,
        notification_counts_by_status: { sent: 2 },
      },
    }),
  );
  await page.route('**/api/v1/operations/failures', (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: 'failure',
            donation_id: donationId,
            step_id: 'step',
            code: 'matching_service_unavailable',
            attempts: 3,
            replay_count: 0,
            created_at: new Date().toISOString(),
          },
        ],
        next_cursor: null,
      },
    }),
  );
  await page.route('**/api/v1/operations/orchestrator/decisions?*', (route) =>
    route.fulfill({
      json: [{ step_id: 'step', donation_id: donationId, status: 'failed', decisions: [] }],
    }),
  );
  await page.goto('/operations');
  await expect(page.getByText('Synthetic demonstration data', { exact: false })).toBeVisible();
  await expect(page.getByText('20 kg', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Review workflow' }).click();
  await expect(page.getByRole('heading', { name: /Workflow decisions/ })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Replay failed work' })).toHaveCount(0);
});
