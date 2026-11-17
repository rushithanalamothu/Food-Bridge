import { afterEach, expect, it, vi } from 'vitest';
import { reserve, pickupCommand, workflowRequest } from './workflow';
import { setAccessToken, setOrganization } from './session';
afterEach(() => {
  vi.unstubAllGlobals();
  setAccessToken();
  setOrganization();
});
it('uses the expected donation version and same command key across reservation retries', async () => {
  const fetch = vi.fn().mockImplementation(async () => Response.json({ id: 'receipt' }));
  vi.stubGlobal('fetch', fetch);
  setAccessToken('token');
  setOrganization('org');
  await reserve({ match_id: 'match', expected_donation_version: 4 }, 'command');
  await reserve({ match_id: 'match', expected_donation_version: 4 }, 'command');
  expect(fetch.mock.calls[1][1]).toEqual(fetch.mock.calls[0][1]);
  expect(fetch.mock.calls[0][1].headers).toMatchObject({
    'Idempotency-Key': 'command',
    'X-FoodBridge-Role': 'recipient',
    Authorization: 'Bearer token',
  });
});
it('does not claim success on conflict or invalid service response', async () => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce(
        Response.json({ code: 'stale_version', message: 'Refresh.' }, { status: 409 }),
      )
      .mockResolvedValueOnce(new Response('<html>offline</html>')),
  );
  await expect(
    pickupCommand('pickup', 'accept', { expected_version: 2 }, 'key'),
  ).rejects.toMatchObject({ status: 409, code: 'stale_version' });
  await expect(workflowRequest('driver', '/pickups')).rejects.toMatchObject({
    code: 'invalid_response',
  });
});
