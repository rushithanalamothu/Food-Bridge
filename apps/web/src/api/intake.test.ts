import { afterEach, expect, it, vi } from 'vitest';
import { createDraft, intakeRequest, setIntakeAccessToken } from './intake';

afterEach(() => {
  vi.unstubAllGlobals();
  setIntakeAccessToken();
});

it('sends the same explicit command key and in-memory bearer token on a retry', async () => {
  const fetch = vi.fn().mockImplementation(async () => Response.json({ id: 'draft' }));
  vi.stubGlobal('fetch', fetch);
  setIntakeAccessToken('test-token');
  const body = {
    description: 'food',
    pickup_location: { address: 'test', latitude: 1, longitude: 1, timezone: 'UTC' },
  };
  await createDraft(body, 'same-key');
  await createDraft(body, 'same-key');
  const headers = fetch.mock.calls[1][1].headers;
  expect(headers['Idempotency-Key']).toBe('same-key');
  expect(headers.Authorization).toBe('Bearer test-token');
  expect(fetch.mock.calls[0][1].body).toBe(fetch.mock.calls[1][1].body);
});

it('surfaces a conflict instead of reporting submission success', async () => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue(
        Response.json({ code: 'stale_version', message: 'Refresh draft.' }, { status: 409 }),
      ),
  );
  await expect(intakeRequest('/donations')).rejects.toMatchObject({
    code: 'stale_version',
    status: 409,
  });
});

it('retains field validation messages for the review form', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      Response.json(
        {
          code: 'validation_error',
          message: 'Check details.',
          details: { 'body.donation.quantity_kg': 'Must be positive' },
        },
        { status: 422 },
      ),
    ),
  );
  await expect(intakeRequest('/donations')).rejects.toMatchObject({
    details: { 'body.donation.quantity_kg': 'Must be positive' },
  });
});
