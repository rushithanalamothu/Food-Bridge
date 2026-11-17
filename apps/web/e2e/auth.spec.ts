import { expect, test } from '@playwright/test';
import { createHash, generateKeyPairSync, sign } from 'node:crypto';
import { fixtures } from './fixtures';
const issuer = 'https://identity.foodbridge.test';
const client = 'foodbridge-browser-tests';
const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const encode = (value: unknown) => Buffer.from(JSON.stringify(value)).toString('base64url');
test.use({ baseURL: 'http://127.0.0.1:5174' });

test('OIDC PKCE callback, bearer session, logout and token storage boundaries', async ({
  page,
}) => {
  await fixtures(page);
  let challenge = '';
  let tokenIssued = false;
  let nonce: string | null = null;
  await page.route(issuer + '/**', async (route) => {
    const url = new URL(route.request().url());
    const headers = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Headers': 'Content-Type',
      'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
    };
    if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
    if (url.pathname.includes('.well-known'))
      return route.fulfill({
        headers,
        json: {
          issuer,
          authorization_endpoint: issuer + '/authorize',
          token_endpoint: issuer + '/token',
          jwks_uri: issuer + '/jwks',
          response_types_supported: ['code'],
          subject_types_supported: ['public'],
          id_token_signing_alg_values_supported: ['RS256'],
          code_challenge_methods_supported: ['S256'],
        },
      });
    if (url.pathname === '/jwks')
      return route.fulfill({
        headers,
        json: { keys: [{ ...publicKey.export({ format: 'jwk' }), kid: 'fixture' }] },
      });
    if (url.pathname === '/authorize') {
      challenge = url.searchParams.get('code_challenge')!;
      nonce = url.searchParams.get('nonce');
      expect(url.searchParams.get('code_challenge_method')).toBe('S256');
      expect(url.searchParams.get('response_type')).toBe('code');
      const callback = new URL(url.searchParams.get('redirect_uri')!);
      callback.searchParams.set('code', 'synthetic-code');
      callback.searchParams.set('state', url.searchParams.get('state')!);
      return route.fulfill({ status: 302, headers: { location: callback.href } });
    }
    if (url.pathname === '/token') {
      const body = new URLSearchParams(route.request().postData()!);
      expect(createHash('sha256').update(body.get('code_verifier')!).digest('base64url')).toBe(
        challenge,
      );
      expect(body.get('code')).toBe('synthetic-code');
      const unsigned =
        encode({ alg: 'RS256', kid: 'fixture' }) +
        '.' +
        encode({
          iss: issuer,
          aud: client,
          sub: 'synthetic-user',
          iat: Math.floor(Date.now() / 1000),
          exp: Math.floor(Date.now() / 1000) + 300,
          ...(nonce ? { nonce } : {}),
        });
      const id_token =
        unsigned +
        '.' +
        sign('RSA-SHA256', Buffer.from(unsigned), privateKey).toString('base64url');
      tokenIssued = true;
      return route.fulfill({
        headers,
        json: {
          access_token: 'synthetic-memory-access-token',
          id_token,
          token_type: 'Bearer',
          expires_in: 300,
          scope: 'openid profile',
        },
      });
    }
    return route.fulfill({ status: 404 });
  });
  await page.goto('/driver');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Sign out of FoodBridge' })).toBeVisible();
  expect(tokenIssued).toBe(true);
  const requestPromise = page.waitForRequest(
    (request) =>
      new URL(request.url()).pathname.endsWith('/pickups') &&
      request.headers()['authorization'] === 'Bearer synthetic-memory-access-token',
  );
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await requestPromise;
  const stored = await page.evaluate(() =>
    JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }),
  );
  expect(stored).not.toContain('synthetic-memory-access-token');
  expect(stored).not.toContain('id_token');
  await expect(page).toHaveURL(/\/driver$/);
  await page.getByRole('button', { name: 'Sign out of FoodBridge' }).click();
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
});
test('invalid callback state fails visibly and removes authorization data from URL', async ({
  page,
}) => {
  await fixtures(page);
  await page.goto('/auth/callback?code=untrusted-code&state=unknown-state');
  await expect(
    page.getByRole('alert').filter({ hasText: 'Sign-in could not be completed' }),
  ).toBeVisible();
  await expect(page).toHaveURL('http://127.0.0.1:5174/');
});
