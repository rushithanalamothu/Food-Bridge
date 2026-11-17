import { expect, test, type Page } from '@playwright/test';
import type { DraftRead } from '../src/api/generated/intake';
import { donationId, fixtures, food, org } from './fixtures';

function gate() {
  let release!: () => void;
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { promise, release };
}

async function historyFixture(page: Page) {
  const state = await fixtures(page);
  let reason = 'initial_history';
  await page.route(`**/api/v1/workflow/donations/${donationId}`, (route) =>
    route.fulfill({
      json: {
        donation: state.donation,
        history: [
          {
            aggregate_version: state.donation.version,
            next_status: state.donation.status,
            previous_status: null,
            reason,
            occurred_at: state.donation.created_at,
          },
        ],
      },
    }),
  );
  return {
    advance: () => {
      reason = 'updated_history';
      state.donation.status = 'delivered';
      state.donation.version++;
    },
  };
}

for (const role of ['recipient', 'driver', 'operations']) {
  test(`${role} refresh reconciles an open history without any SSE events`, async ({ page }) => {
    const historyState = await historyFixture(page);
    await page.goto('/' + role);
    await page.getByRole('button', { name: 'View donation history', exact: true }).click();
    const history = page.getByRole('region', { name: 'Donation history' });
    await expect(history).toContainText('Initial History');
    historyState.advance();
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await expect(history).toContainText('Updated History');
    await expect(history).toContainText('Delivered');
  });
}

for (const count of [1, 30]) {
  test(
    count === 30
      ? 'open history continues updating after thirty live events'
      : 'reconnect reconciles open history even without a new event',
    async ({ page }) => {
      const historyState = await historyFixture(page);
      const reconnecting = gate();
      const resume = gate();
      let resumed = false;
      const event = (id: number) =>
        `id: ${id}\nevent: status\ndata: ${JSON.stringify({ event_id: 'history-' + id, event_type: 'donation.updated.v1', aggregate_id: donationId, aggregate_version: id, occurred_at: new Date().toISOString(), payload: {} })}\n\n`;
      await page.route('**/api/v1/events', async (route) => {
        const cursor = route.request().headers()['last-event-id'];
        // A StrictMode-aborted initial connection may not acknowledge the first frames.
        if (!cursor)
          return route.fulfill({
            contentType: 'text/event-stream',
            body: Array.from({ length: count }, (_, i) => event(i + 1)).join(''),
          });
        if (resumed) return route.fulfill({ status: 403, json: {} });
        reconnecting.release();
        await resume.promise;
        resumed = true;
        return route.fulfill({
          contentType: 'text/event-stream',
          body: count === 30 ? event(31) : ': reconnected\n\n',
        });
      });
      await page.goto('/operations');
      await reconnecting.promise;
      await expect(page.locator('.activity-list > li')).toHaveCount(count);
      await page.getByRole('button', { name: 'View donation history', exact: true }).click();
      const history = page.getByRole('region', { name: 'Donation history' });
      await expect(history).toContainText('Initial History');
      historyState.advance();
      resume.release();
      await expect(history).toContainText('Updated History');
      await expect(history).toContainText('Delivered');
      // The activity list stays capped independently of snapshot/history reconciliation.
      await expect(page.locator('section:not([aria-label]) > .activity-list > li')).toHaveCount(
        count,
      );
    },
  );
}

const savedId = '00000000-0000-4000-8000-000000000088';
const newId = '00000000-0000-4000-8000-000000000089';
const storageKey = 'foodbridge:draft:' + org;
function draft(id: string, description: string): DraftRead {
  const donation = food();
  return {
    id,
    description,
    donor_organization_id: org,
    created_at: donation.created_at,
    status: 'review_required',
    version: 1,
    pickup_location: donation.pickup_location,
    extraction: {
      provider: 'rules',
      fields: {
        food_name: description,
        category: 'prepared_meals',
        storage: 'chilled',
        quantity_kg: 1,
        allergens: ['soy'],
        pickup_window: donation.pickup_window,
        safe_use_by: donation.safe_use_by,
      },
    },
  };
}
async function savedDraft(page: Page) {
  await fixtures(page);
  const saved = draft(savedId, 'Saved rice draft');
  await page.route('**/api/v1/donation-drafts', (route) => {
    const description = route.request().postDataJSON().description;
    return route.fulfill({
      status: 201,
      json: description === saved.description ? saved : draft(newId, description),
    });
  });
  await page.goto('/donor');
  await page.getByLabel('Food description', { exact: true }).fill(saved.description);
  await page.getByRole('button', { name: 'Review details', exact: true }).click();
  await expect(page.getByLabel('Food name', { exact: true })).toHaveValue(saved.description);
  return saved;
}

for (const failure of [false, true]) {
  test(`late saved-draft ${failure ? 'failure' : 'success'} cannot replace a newer draft or its recovery ID`, async ({
    page,
  }) => {
    const saved = await savedDraft(page);
    const requested = gate();
    const respond = gate();
    await page.route(`**/api/v1/donation-drafts/${savedId}`, async (route) => {
      requested.release();
      await respond.promise;
      return failure
        ? route.fulfill({
            status: 503,
            json: { code: 'unavailable', message: 'Temporary draft failure' },
          })
        : route.fulfill({ json: saved });
    });
    await page.reload();
    await requested.promise;
    await page.getByLabel('Food description', { exact: true }).fill('New rice draft');
    await page.getByRole('button', { name: 'Review details', exact: true }).click();
    await expect(page.getByLabel('Food name', { exact: true })).toHaveValue('New rice draft');
    const finished = page.waitForResponse(`**/api/v1/donation-drafts/${savedId}`);
    respond.release();
    await (await finished).finished();
    await page.getByRole('button', { name: 'Edit description', exact: true }).click();
    await expect(page.getByLabel('Food description', { exact: true })).toHaveValue(
      'New rice draft',
    );
    expect(await page.evaluate((key) => sessionStorage.getItem(key), storageKey)).toBe(newId);
    await expect(
      page.getByText('Your saved draft is ready to review.', { exact: true }),
    ).toHaveCount(0);
  });
}

test('typing a new description invalidates a pending saved-draft response immediately', async ({
  page,
}) => {
  const saved = await savedDraft(page);
  const requested = gate();
  const respond = gate();
  await page.route(`**/api/v1/donation-drafts/${savedId}`, async (route) => {
    requested.release();
    await respond.promise;
    return route.fulfill({ json: saved });
  });
  await page.reload();
  await requested.promise;
  await page.getByLabel('Food description', { exact: true }).fill('Work in progress');
  const finished = page.waitForResponse(`**/api/v1/donation-drafts/${savedId}`);
  respond.release();
  await (await finished).finished();
  await page.getByLabel('Food description', { exact: true }).press('End');
  await expect(page.getByLabel('Food description', { exact: true })).toHaveValue(
    'Work in progress',
  );
  await expect(page.getByLabel('Food name', { exact: true })).toHaveCount(0);
});

for (const method of ['retry', 'reload']) {
  test(`temporary draft failures preserve recovery through ${method}`, async ({ page }) => {
    const saved = await savedDraft(page);
    let available = false;
    await page.route(`**/api/v1/donation-drafts/${savedId}`, (route) =>
      available
        ? route.fulfill({ json: saved })
        : route.fulfill({
            status: 503,
            json: { code: 'unavailable', message: 'Temporary failure' },
          }),
    );
    await page.reload();
    await expect(page.getByRole('alert')).toContainText('It is still saved.');
    expect(await page.evaluate((key) => sessionStorage.getItem(key), storageKey)).toBe(savedId);
    available = true;
    if (method === 'retry')
      await page.getByRole('button', { name: 'Retry saved draft', exact: true }).click();
    else await page.reload();
    await expect(page.getByLabel('Food name', { exact: true })).toHaveValue(saved.description);
    await expect(
      page.getByText('Your saved draft is ready to review.', { exact: true }),
    ).toBeVisible();
  });
}

test('an authoritative missing-draft response removes its obsolete recovery ID', async ({
  page,
}) => {
  await savedDraft(page);
  await page.route(`**/api/v1/donation-drafts/${savedId}`, (route) =>
    route.fulfill({ status: 404, json: { code: 'not_found', message: 'Draft unavailable' } }),
  );
  await page.reload();
  await expect(
    page.getByText('Your saved draft is no longer available. You can start a new donation.'),
  ).toBeVisible();
  expect(await page.evaluate((key) => sessionStorage.getItem(key), storageKey)).toBeNull();
  await expect(page.getByLabel('Food description', { exact: true })).toBeVisible();
});

for (const [endpoint, button] of [
  ['me', 'Refresh'],
  ['intake/policy', 'Retry donor setup'],
]) {
  test(`donor setup recovers a failed ${endpoint} request through ${button}`, async ({ page }) => {
    await fixtures(page);
    let available = false;
    await page.route(`**/api/v1/${endpoint}`, (route) =>
      available
        ? route.fallback()
        : route.fulfill({
            status: 503,
            json: { code: 'unavailable', message: 'Temporary setup failure' },
          }),
    );
    await page.goto('/donor');
    await expect(
      page.getByRole('button', { name: 'Retry donor setup', exact: true }),
    ).toBeVisible();
    await expect(page.getByLabel('Food description', { exact: true })).toHaveCount(0);
    available = true;
    await page.getByRole('button', { name: button, exact: true }).click();
    await expect(page.getByLabel('Food description', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Retry donor setup', exact: true })).toHaveCount(
      0,
    );
    await page.getByLabel('Food description', { exact: true }).fill('Keep my unsaved description');
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await expect(page.getByLabel('Food description', { exact: true })).toHaveValue(
      'Keep my unsaved description',
    );
  });
}
