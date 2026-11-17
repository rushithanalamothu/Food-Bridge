import { useEffect, useState } from 'react';
import type { BrowserSession } from '../../api/session';
import { loadSession, selectMembership, selectedMembership } from '../../api/session';
export function SessionBar() {
  const [session, setSession] = useState<BrowserSession>();
  const [error, setError] = useState('');
  const [choice, setChoice] = useState('');
  useEffect(() => {
    const expired = () => {
      setError('Your session expired. Sign in again.');
      setSession(undefined);
    };
    window.addEventListener('foodbridge:session-expired', expired);
    return () => window.removeEventListener('foodbridge:session-expired', expired);
  }, []);
  useEffect(() => {
    loadSession()
      .then((s) => {
        setSession(s);
        const m = selectedMembership();
        setChoice(m ? `${m.organization_id}:${m.role}` : '');
      })
      .catch((e) => setError(e.message));
  }, []);
  return (
    <section className="session-bar" aria-label="Session">
      {error && (
        <span role="alert">
          {error} <a href="/api/v1/auth/login">Sign in</a>
        </span>
      )}
      {session?.login_enabled && (!session.authenticated || session.mode === 'local_demo') && (
        <a href="/api/v1/auth/login">Sign in to FoodBridge</a>
      )}
      {session?.authenticated && (
        <>
          <span>{session.mode === 'local_demo' ? 'Local demo identity' : 'Signed in'}</span>
          {session.memberships.length > 0 ? (
            <label>
              Workspace identity{' '}
              <select
                value={choice}
                onChange={(e) => {
                  const value = session.memberships.find(
                    (m) => `${m.organization_id}:${m.role}` === e.target.value,
                  );
                  selectMembership(value);
                  setChoice(e.target.value);
                  window.location.assign(
                    value?.role === 'operator' ? '/operations' : `/${value?.role ?? ''}`,
                  );
                }}
              >
                {session.memberships.map((m) => (
                  <option
                    key={`${m.organization_id}:${m.role}`}
                    value={`${m.organization_id}:${m.role}`}
                  >
                    {m.organization_name} · {m.role}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <span>No active memberships. Ask your administrator for access.</span>
          )}
          {session.mode !== 'local_demo' && (
            <button
              onClick={async () => {
                const response = await fetch('/api/v1/auth/logout', {
                  method: 'POST',
                  credentials: 'same-origin',
                });
                if (response.ok) {
                  selectMembership();
                  window.location.assign('/');
                } else setError('Sign out could not be completed. Try again.');
              }}
            >
              Sign out
            </button>
          )}
        </>
      )}
    </section>
  );
}
