import { intakeRequest } from './intake';
import { membershipHeaders, selectedMembership } from './session';
const keys = new Map<string, string>();
export function roleHeaders(role: string): Record<string, string> {
  const member = selectedMembership();
  return {
    ...(member?.role === role ? membershipHeaders() : { 'X-Organization-ID': '' }),
    'X-FoodBridge-Role': role,
  };
}
export function workflowGet<T>(path: string, role: string, signal?: AbortSignal) {
  return intakeRequest<T>(path, { headers: roleHeaders(role), signal });
}
export function workflowPost<T>(path: string, role: string, body: unknown) {
  const identity = JSON.stringify([roleHeaders(role), path, body]);
  if (!keys.has(identity)) {
    if (keys.size > 200) keys.clear();
    keys.set(identity, crypto.randomUUID());
  }
  return intakeRequest<T>(path, {
    method: 'POST',
    headers: { ...roleHeaders(role), 'Idempotency-Key': keys.get(identity)! },
    body: JSON.stringify(body),
  });
}
export type SSEFrame = { id?: string; data: string };
export function parseFrame(frame: string): SSEFrame | undefined {
  let id: string | undefined;
  const data: string[] = [];
  for (const line of frame.split('\n')) {
    if (line.startsWith('id:')) id = line.slice(3).trim();
    if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
  }
  return data.length ? { id, data: data.join('\n') } : undefined;
}
