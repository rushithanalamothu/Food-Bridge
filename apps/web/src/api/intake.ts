import { sessionHeaders, setAccessToken } from './session';
import type {
  DonationSubmit,
  DraftCreate,
  DraftRead,
  DonorIdentity,
  IntakeDonationRead,
  EvaluationRead,
  DonationPage,
  IntakePolicy,
} from './generated/intake';

export class IntakeApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public details: Record<string, string> = {},
  ) {
    super(message);
  }
}

// The gateway can provide an in-memory access token; never persist it in localStorage or URLs.

export function setIntakeAccessToken(token?: string) {
  setAccessToken(token);
}

export async function intakeRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...sessionHeaders(),
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
export const getDonorIdentity = () => intakeRequest<DonorIdentity>('/me');
export const createDraft = (body: DraftCreate, key: string) =>
  intakeRequest<DraftRead>('/donation-drafts', {
    method: 'POST',
    headers: { 'Idempotency-Key': key },
    body: JSON.stringify(body),
  });
export const submitDonation = (body: DonationSubmit, key: string) =>
  intakeRequest<IntakeDonationRead>('/donations', {
    method: 'POST',
    headers: { 'Idempotency-Key': key },
    body: JSON.stringify(body),
  });
export const getDonation = (id: string) => intakeRequest<IntakeDonationRead>(`/donations/${id}`);
export const listDonations = (cursor?: string | null) =>
  intakeRequest<DonationPage>(
    '/donations' + (cursor ? '?cursor=' + encodeURIComponent(cursor) : ''),
  );
export const getDraft = (id: string) => intakeRequest<DraftRead>(`/donation-drafts/${id}`);
export const demoEligibility = (id: string, key: string) =>
  intakeRequest<EvaluationRead>(`/donations/${id}/demo-eligibility`, {
    method: 'POST',
    headers: { 'Idempotency-Key': key },
  });
export const getEvaluation = (id: string, signal?: AbortSignal) =>
  intakeRequest<EvaluationRead>(`/intake/evaluations/${id}`, { signal });

export const getIntakePolicy = () => intakeRequest<IntakePolicy>('/intake/policy');
