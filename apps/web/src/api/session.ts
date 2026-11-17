import type { BrowserSessionRead, SessionMembership } from './generated/workflow';
export type Membership = SessionMembership;
export type BrowserSession = BrowserSessionRead;
let selected: Membership | undefined;
export function selectMembership(value?: Membership) {
  selected = value;
  if (value) sessionStorage.setItem('foodbridge.membership', JSON.stringify(value));
  else sessionStorage.removeItem('foodbridge.membership');
  window.dispatchEvent(new Event('foodbridge:membership'));
}
export function membershipHeaders(): Record<string, string> {
  if (!selected) return {};
  return { 'X-Organization-ID': selected.organization_id, 'X-FoodBridge-Role': selected.role };
}
export function selectedMembership() {
  return selected;
}
async function fetchSession(): Promise<BrowserSession> {
  const response = await fetch('/api/v1/auth/session', {
    credentials: 'same-origin',
    cache: 'no-store',
    signal: AbortSignal.timeout(10000),
  });
  if (!response.ok)
    throw new Error('Session expired or sign-in service unavailable. Sign in again.');
  const result: BrowserSession = await response.json();
  let previous: Membership | undefined;
  try {
    previous = JSON.parse(sessionStorage.getItem('foodbridge.membership') ?? 'null');
  } catch {
    /* Invalid selection is ignored; server still authorizes every request. */
  }
  const valid = result.memberships.find(
    (m) => m.role === previous?.role && m.organization_id === previous?.organization_id,
  );
  selectMembership(valid ?? result.memberships[0]);
  return result;
}

export function sessionExpired() {
  if (typeof window !== 'undefined') window.dispatchEvent(new Event('foodbridge:session-expired'));
}

let loading: Promise<BrowserSession> | undefined;
export function loadSession(): Promise<BrowserSession> {
  loading ??= fetchSession().finally(() => {
    loading = undefined;
  });
  return loading;
}
