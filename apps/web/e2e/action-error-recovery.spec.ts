import { expect, test, type Page } from '@playwright/test';
import { fixtures } from './fixtures';

function gate() {
  let release!: () => void;
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { promise, release };
}

async function attempt(page: Page, role: string) {
  if (role === 'driver') {
    await page.getByRole('checkbox').check();
    await page.getByRole('button', { name: 'Confirm pickup', exact: true }).click();
  } else if (role === 'recipient') {
    await page.getByRole('button', { name: 'Accept offer', exact: true }).click();
    await page.getByRole('button', { name: 'Confirm accept offer', exact: true }).click();
  } else {
    await page.getByRole('button', { name: 'Replay failed work', exact: true }).click();
    await page.getByRole('button', { name: 'Confirm replay failed work', exact: true }).click();
  }
}

for (const role of ['driver', 'recipient', 'operations']) {
  test(`${role} keeps rejected-action feedback across SSE, manual and focus reconciliation`, async ({
    page,
  }) => {
    const state = await fixtures(page);
    state.pickup.status = 'accepted';
    const resume = gate();
    let connected = false;
    let fail = true;
    await page.route('**/api/v1/events', async (route) => {
      if (connected) return route.fulfill({ status: 403, json: {} });
      await resume.promise;
      connected = true;
      return route.fulfill({ contentType: 'text/event-stream', body: ': reconnected\n\n' });
    });
    const path =
      role === 'driver'
        ? '**/api/v1/pickups/*/confirm-pickup'
        : role === 'recipient'
          ? '**/api/v1/reservations'
          : '**/api/v1/operations/failures/*/replay';
    await page.route(path, (route) => {
      if (route.request().method() !== 'POST') return route.fallback();
      if (!fail) return role === 'operations' ? route.fulfill({ json: {} }) : route.fallback();
      return route.fulfill({
        status: 409,
        json: {
          code: 'eligibility_changed',
          message: 'Review the rejected action before retrying.',
        },
      });
    });
    await page.goto('/' + role);
    if (role === 'operations')
      await page.getByRole('button', { name: 'Review workflow', exact: true }).click();
    await attempt(page, role);
    const error = page
      .getByRole('alert')
      .filter({ hasText: 'Review the rejected action before retrying.' });
    await expect(error).toBeVisible();
    state.donation.food_name = 'Vegetable rice lunch trays';
    resume.release();
    await expect(
      page.getByRole('heading', { name: state.donation.food_name, exact: true }),
    ).toBeVisible();
    await expect(error).toBeVisible();
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await expect(error).toBeVisible();
    const focusRead = page.waitForResponse(
      (r) =>
        r.request().method() === 'GET' &&
        /\/(pickups|matches|operations\/summary)\?*[^/]*$/.test(new URL(r.url()).pathname),
    );
    await page.evaluate(() => window.dispatchEvent(new Event('focus')));
    await (await focusRead).finished();
    await expect(error).toBeVisible();
    await page.getByRole('button', { name: 'Dismiss action error', exact: true }).click();
    await expect(error).toHaveCount(0);
    await attempt(page, role);
    await expect(error).toBeVisible();
    fail = false;
    await attempt(page, role);
    await expect(error).toHaveCount(0);
    if (role === 'driver')
      await expect(
        page.getByRole('button', { name: 'Confirm delivery', exact: true }),
      ).toBeVisible();
    else
      await expect(
        page.getByText(
          role === 'recipient'
            ? 'Reservation confirmed. Driver coordination is underway.'
            : 'Replay queued. This does not reopen terminal or expired donations.',
          { exact: true },
        ),
      ).toBeVisible();
  });
}

test('a recovered snapshot clears its load error without requiring action dismissal', async ({
  page,
}) => {
  const state = await fixtures(page);
  let fail = true;
  await page.route('**/api/v1/pickups?*', (route) =>
    route.fulfill(
      fail
        ? {
            status: 503,
            json: { code: 'unavailable', message: 'Assignments temporarily unavailable.' },
          }
        : { json: { items: [state.pickup], next_cursor: null } },
    ),
  );
  await page.goto('/driver');
  await expect(page.getByRole('alert')).toContainText('Assignments temporarily unavailable.');
  fail = false;
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Accept assignment', exact: true })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('fresh receiver snapshots block a stale offer and enable a new validated match', async ({
  page,
}) => {
  const state = await fixtures(page);
  let stale = true;
  await page.route('**/api/v1/matches?*', (route) =>
    route.fulfill({
      json: {
        items: [
          {
            ...state.offers[0],
            requires_revalidation: stale,
            recommendation: {
              ...state.offers[0].recommendation,
              id: stale
                ? state.offers[0].recommendation.id
                : '00000000-0000-4000-8000-000000000088',
            },
          },
        ],
        next_cursor: null,
      },
    }),
  );
  await page.goto('/recipient');
  await expect(page.getByRole('button', { name: 'Accept offer', exact: true })).toBeDisabled();
  await expect(page.getByText('This offer needs revalidation', { exact: false })).toBeVisible();
  stale = false;
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Accept offer', exact: true })).toBeEnabled();
  // Profile and offer GETs can reconcile on different snapshots; the server-validated
  // replacement ID must remain actionable when the profile response catches up.
  state.profile.profile.version++;
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Accept offer', exact: true })).toBeEnabled();
});
