import { expect, test, type Page } from '@playwright/test';
import { donationId, fixtures, food } from './fixtures';

// Release requests explicitly so races are deterministic, even on a slow CI worker.
function gate() {
  let release!: () => void;
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { promise, release };
}

const otherId = '00000000-0000-4000-8000-000000000099';
async function operationsPair(page: Page) {
  const state = await fixtures(page);
  const other = { ...food(), id: otherId, food_name: 'Second donation', version: 11 };
  await page.route('**/api/v1/workflow/donations?*', (route) =>
    route.fulfill({
      json: { items: [state.donation, other], next_cursor: null },
    }),
  );
  await page.route('**/api/v1/operations/failures*', (route) =>
    route.fulfill({
      json: {
        items: [donationId, otherId].map((id, i) => ({
          id: `failure-${i}`,
          donation_id: id,
          step_id: `step-${i}`,
          code: 'matching_service_unavailable',
          attempts: 3,
          replay_count: 0,
          created_at: state.donation.created_at,
        })),
        next_cursor: null,
      },
    }),
  );
  return { state, other };
}

for (const fails of [false, true]) {
  test(`late donor refresh ${fails ? 'failure' : 'success'} leaves the new donation form intact`, async ({
    page,
  }) => {
    await fixtures(page);
    await page.goto('/donor');
    const initialDetail = page.waitForResponse(`**/api/v1/donations/${donationId}`);
    await page.getByRole('button', { name: 'Synthetic rice bowls', exact: true }).click();
    await initialDetail;
    const requested = gate();
    const response = gate();
    await page.route(`**/api/v1/donations/${donationId}`, async (route) => {
      requested.release();
      await response.promise;
      if (fails)
        return route.fulfill({
          status: 503,
          json: { code: 'unavailable', message: 'Old donation refresh failed' },
        });
      return route.fulfill({ json: { donation: food(), urgency: { priority: 'high' } } });
    });
    await page.getByRole('button', { name: 'Refresh status', exact: true }).click();
    await requested.promise;
    await page.getByRole('button', { name: 'Post another donation' }).click();
    await page.getByLabel('Food description').fill('New food description');
    const finished = page.waitForResponse(`**/api/v1/donations/${donationId}`);
    response.release();
    await (await finished).finished();
    // A subsequent browser task allows the response handler to commit before asserting.
    await page.getByLabel('Food description').press('End');
    await expect(page.getByRole('heading', { name: 'Post today’s surplus' })).toBeVisible();
    await expect(page.getByLabel('Food description')).toHaveValue('New food description');
    await expect(page.getByRole('button', { name: 'Refresh status', exact: true })).toHaveCount(0);
    await expect(page.getByText('Old donation refresh failed')).toHaveCount(0);
  });
}

test('workflow replay requires a successful review and version for the selected donation', async ({
  page,
}) => {
  const { other } = await operationsPair(page);
  const requested = gate();
  const response = gate();
  let fail = true;
  let replay: unknown;
  await page.route(`**/api/v1/workflow/donations/${otherId}`, async (route) => {
    requested.release();
    await response.promise;
    return fail
      ? route.fulfill({
          status: 503,
          json: { code: 'unavailable', message: 'Second review unavailable' },
        })
      : route.fulfill({ json: { donation: other, history: [] } });
  });
  await page.route('**/api/v1/operations/failures/*/replay', (route) => {
    replay = route.request().postDataJSON();
    return route.fulfill({ json: {} });
  });
  await page.goto('/operations');
  await page.getByRole('button', { name: 'Review workflow' }).nth(0).click();
  await expect(page.getByRole('button', { name: 'Replay failed work', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Review workflow' }).nth(1).click();
  await requested.promise;
  await expect(page.getByRole('button', { name: 'Replay failed work', exact: true })).toHaveCount(
    0,
  );
  response.release();
  await expect(page.getByRole('alert')).toContainText('Second review unavailable');
  await expect(page.getByRole('button', { name: 'Replay failed work', exact: true })).toHaveCount(
    0,
  );
  fail = false;
  await page.getByRole('button', { name: 'Review workflow' }).nth(1).click();
  await page.getByRole('button', { name: 'Replay failed work', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm replay failed work' }).click();
  await expect(page.getByText('Replay queued.', { exact: false })).toBeVisible();
  expect(replay).toEqual({ expected_version: 11 });
});

test('switching donation history clears the previous donation during loading and failure', async ({
  page,
}) => {
  await operationsPair(page);
  const requested = gate();
  const response = gate();
  await page.route(`**/api/v1/workflow/donations/${otherId}`, async (route) => {
    requested.release();
    await response.promise;
    return route.fulfill({
      status: 503,
      json: { code: 'unavailable', message: 'Second history unavailable' },
    });
  });
  await page.goto('/operations');
  await page.getByRole('button', { name: 'View donation history' }).nth(0).click();
  const history = page.getByRole('region', { name: 'Donation history' });
  await expect(history).toContainText('Synthetic rice bowls');
  await page.getByRole('button', { name: 'View donation history' }).nth(1).click();
  await requested.promise;
  await expect(history).toContainText('Loading history…');
  await expect(history).not.toContainText('Synthetic rice bowls');
  response.release();
  await expect(history.getByRole('alert')).toHaveText('Second history unavailable');
  await expect(history).not.toContainText('Synthetic rice bowls');
});

test('saving receiving preferences disables acceptance of existing offers', async ({ page }) => {
  const state = await fixtures(page);
  await page.goto('/recipient');
  // Even a confirmation already open before the save must become disabled.
  await page.getByRole('button', { name: 'Accept offer', exact: true }).click();
  await page.getByRole('button', { name: 'Edit preferences' }).click();
  await page.getByLabel('Chilled free storage (kg)').fill('30');
  await page.getByRole('button', { name: 'Save preferences' }).click();
  await expect(page.getByText('Receiving preferences saved.')).toBeVisible();
  await expect(page.getByText(/This offer needs revalidation/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Confirm accept offer' })).toBeDisabled();
  expect(state.commands.map((command) => command.path)).toEqual(['/receiving-profile']);
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Confirm accept offer' })).toBeDisabled();
});

test('profile conflicts suppress repeated acceptance after refreshing authoritative offers', async ({
  page,
}) => {
  await fixtures(page);
  let attempts = 0;
  await page.route('**/api/v1/reservations', (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    attempts++;
    return route.fulfill({
      status: 409,
      json: { code: 'recipient_profile_changed', message: 'Stale receiving profile' },
    });
  });
  await page.goto('/recipient');
  await page.getByRole('button', { name: 'Accept offer', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm accept offer' }).click();
  await expect(page.getByRole('alert')).toContainText('This offer needs revalidation');
  await expect(page.getByRole('button', { name: 'Accept offer', exact: true })).toBeDisabled();
  expect(attempts).toBe(1);
  await expect(page.getByText('Reservation confirmed.', { exact: false })).toHaveCount(0);
});

test('profile updates from another session invalidate existing offers while replacement offers stay usable', async ({
  page,
}) => {
  const state = await fixtures(page);
  await page.goto('/recipient');
  await expect(page.getByRole('button', { name: 'Accept offer', exact: true })).toBeEnabled();
  state.profile.profile.version++;
  const original = state.offers[0];
  state.offers.push({
    ...original,
    recommendation: { ...original.recommendation, id: 'replacement-match' },
    donation: { ...state.donation, food_name: 'Replacement offer' },
  });
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  const oldCard = page
    .getByRole('article')
    .filter({ has: page.getByRole('heading', { name: 'Synthetic rice bowls' }) });
  const newCard = page
    .getByRole('article')
    .filter({ has: page.getByRole('heading', { name: 'Replacement offer' }) });
  await expect(oldCard.getByRole('button', { name: 'Accept offer', exact: true })).toBeDisabled();
  await expect(newCard.getByRole('button', { name: 'Accept offer', exact: true })).toBeEnabled();
});
