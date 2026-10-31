import { useEffect, useState } from 'react';
import { getLiveStatus } from '../api/health';

export function ApiStatus() {
  const [message, setMessage] = useState('Checking API…');
  useEffect(() => {
    const controller = new AbortController();
    void getLiveStatus(controller.signal)
      .then((data) =>
        setMessage(
          `API process reachable · v${data.version}. Infrastructure readiness is checked separately.`,
        ),
      )
      .catch(() => {
        if (!controller.signal.aborted)
          setMessage('API unavailable. Start it with make api, or inspect the Compose logs.');
      });
    return () => controller.abort();
  }, []);
  return (
    <p role="status" className="api-status">
      {message}
    </p>
  );
}
