import type {
  Actor,
  Role,
  OfferPage,
  PickupPage,
  OperationsSummary,
  FailurePage,
  ReservationRead,
  DonationRead,
  PickupRead,
  ReplayResult,
  OrchestrationAudit,
} from './generated/workflow';
import type { ReservationRequest } from './generated/domain';
import { IntakeApiError } from './intake';
import { sessionHeaders } from './session';

export async function workflowRequest<T>(
  role: Role,
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    headers: {
      ...sessionHeaders(role),
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...options.headers,
    },
  });
  let body;
  try {
    body = await response.json();
  } catch {
    throw new IntakeApiError(
      'invalid_response',
      'The service returned an unreadable response. Retry shortly.',
      response.status,
    );
  }
  if (!response.ok)
    throw new IntakeApiError(
      body.code ?? 'request_failed',
      body.message ?? 'Request failed.',
      response.status,
      body.details ?? {},
    );
  return body as T;
}
const page = (path: string, cursor?: string | null) =>
  path + (cursor ? `?cursor=${encodeURIComponent(cursor)}` : '');
export const getSession = (role: Role, signal?: AbortSignal) =>
  workflowRequest<Actor>(role, '/session', { signal });
export const getOffers = (cursor?: string | null) =>
  workflowRequest<OfferPage>('recipient', page('/matches', cursor));
export const getPickups = (cursor?: string | null) =>
  workflowRequest<PickupPage>('driver', page('/pickups', cursor));
export const getSummary = () =>
  workflowRequest<OperationsSummary>('operator', '/operations/summary');
export const getFailures = (cursor?: string | null) =>
  workflowRequest<FailurePage>('operator', page('/operations/failures', cursor));
export const getDecisions = (donation: string) =>
  workflowRequest<OrchestrationAudit[]>(
    'operator',
    `/operations/orchestrator/decisions?donation_id=${encodeURIComponent(donation)}`,
  );
// Keep the same key for an uncertain response. A changed body is a new command.
export async function command<T>(role: Role, path: string, body: unknown, key: string): Promise<T> {
  return workflowRequest<T>(role, path, {
    method: 'POST',
    headers: { 'Idempotency-Key': key },
    body: JSON.stringify(body),
  });
}
export const reserve = (body: ReservationRequest, key: string) =>
  command<ReservationRead>('recipient', '/reservations', body, key);
export const declineOffer = (id: string, version: number, key: string) =>
  command<DonationRead>('recipient', `/matches/${id}/decline`, { expected_version: version }, key);
export const releaseReservation = (id: string, version: number, key: string) =>
  command<ReservationRead>(
    'recipient',
    `/reservations/${id}/release`,
    { expected_version: version },
    key,
  );
export const cancelDonation = (id: string, version: number, key: string) =>
  command<DonationRead>(
    'donor',
    `/donations/${id}/cancel`,
    { expected_donation_version: version },
    key,
  );
export const pickupCommand = (id: string, verb: string, body: unknown, key: string) =>
  command<PickupRead>('driver', `/pickups/${id}/${verb}`, body, key);
export const replayFailure = (id: string, version: number, key: string) =>
  command<ReplayResult>(
    'operator',
    `/operations/failures/${id}/replay`,
    { expected_version: version },
    key,
  );
