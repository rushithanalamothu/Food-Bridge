export interface LiveStatus {
  status: 'ok';
  version: string;
}

export async function getLiveStatus(signal?: AbortSignal): Promise<LiveStatus> {
  const response = await fetch('/api/v1/health/live', { signal });
  if (!response.ok) throw new Error(`API returned ${response.status}`);
  const body: unknown = await response.json();
  if (
    typeof body !== 'object' ||
    body === null ||
    !('status' in body) ||
    body.status !== 'ok' ||
    !('version' in body) ||
    typeof body.version !== 'string'
  )
    throw new Error('Unexpected API health response');
  return body as LiveStatus;
}
