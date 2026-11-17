import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { InMemoryWebStorage, UserManager, WebStorageStateStore } from 'oidc-client-ts';
import { useLocation, useNavigate } from 'react-router-dom';
import { setAccessToken, setOrganization, getOrganization } from '../api/session';
import { getSession, getMemberships } from '../api/workflow';
import type { Actor, Role, MembershipRead } from '../api/generated/workflow';
import { Notice } from './Workspace';

const env = import.meta.env;
const manager =
  env.VITE_OIDC_AUTHORITY && env.VITE_OIDC_CLIENT_ID
    ? new UserManager({
        authority: env.VITE_OIDC_AUTHORITY,
        client_id: env.VITE_OIDC_CLIENT_ID,
        redirect_uri: window.location.origin + '/auth/callback',
        response_type: 'code',
        scope: env.VITE_OIDC_SCOPE || 'openid profile',
        userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
        stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
        automaticSilentRenew: false,
        loadUserInfo: false,
        extraQueryParams: env.VITE_OIDC_AUDIENCE ? { audience: env.VITE_OIDC_AUDIENCE } : undefined,
      })
    : undefined;
let callback: Promise<unknown> | undefined;
const SessionContext = createContext({ revision: 0, actor: undefined as Actor | undefined });
export const useSession = () => useContext(SessionContext);
export function routeRole(path: string): Role | undefined {
  if (path.startsWith('/donor')) return 'donor';
  if (path.startsWith('/recipient')) return 'recipient';
  if (path.startsWith('/driver')) return 'driver';
  if (path.startsWith('/operations')) return 'operator';
}
export function SessionProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const role = routeRole(location.pathname);
  const [revision, setRevision] = useState(0);
  const [ready, setReady] = useState(!manager);
  const [actor, setActor] = useState<Actor>();
  const [error, setError] = useState('');
  const [org, setOrg] = useState('');
  const [choices, setChoices] = useState<MembershipRead[]>([]);
  const [select, setSelect] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const [resolvedScope, setResolvedScope] = useState('');
  useEffect(() => {
    if (!manager) return;
    const loaded = (user: { access_token: string }) => {
      setAccessToken(user.access_token);
      setSignedIn(true);
      setRevision((v) => v + 1);
    };
    const expired = () => {
      setAccessToken();
      setActor(undefined);
      setSignedIn(false);
      setError('Your session has expired. Sign in again to continue.');
      setRevision((v) => v + 1);
    };
    manager.events.addUserLoaded(loaded);
    manager.events.addAccessTokenExpired(expired);
    if (window.location.pathname === '/auth/callback') {
      callback ??= manager.signinRedirectCallback().then((user) => {
        if (!user || user.expired) throw new Error('Session expired');
        const state = user.state as { returnTo?: string } | undefined;
        setAccessToken(user.access_token);
        setSignedIn(true);
        setRevision((v) => v + 1);
        const target = state?.returnTo;
        navigate(target && routeRole(target) ? '/' + target.split('/')[1] : '/', {
          replace: true,
        });
      });
      // A full navigation would discard the memory-only token. Complete routing in this document.
      void callback
        .catch(() => {
          navigate('/', { replace: true });
          setError('Sign-in could not be completed. Please start again.');
        })
        .finally(() => setReady(true));
    } else setReady(true);
    return () => {
      manager.events.removeUserLoaded(loaded);
      manager.events.removeAccessTokenExpired(expired);
    };
  }, []);
  useEffect(() => {
    if (!ready || !role) {
      setActor(undefined);
      return;
    }
    const controller = new AbortController();
    setActor(undefined);
    setError('');
    setSelect(false);
    void getMemberships(role)
      .then((memberships) => {
        if (controller.signal.aborted) return;
        const options = memberships.filter((item) => item.role === role);
        setChoices(options);
        const current = getOrganization();
        const next = options.some((item) => item.organization_id === current)
          ? current
          : options.length === 1
            ? options[0].organization_id
            : undefined;
        setOrg(next ?? '');
        if (next !== current) {
          setOrganization(next);
          setRevision((v) => v + 1);
          return;
        }
        return getSession(role, controller.signal);
      })
      .then((value) => {
        if (!controller.signal.aborted && value) setActor(value);
      })
      .catch((e) => {
        if (!controller.signal.aborted) {
          setError(e.message);
          setSelect(e.code === 'membership_selection_required');
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setResolvedScope(`${role}:${revision}`);
      });
    return () => controller.abort();
  }, [ready, role, revision]);
  async function signIn() {
    setError('');
    try {
      await manager?.signinRedirect({
        state: { returnTo: location.pathname === '/auth/callback' ? '/' : location.pathname },
      });
    } catch {
      setError('Could not open your organization’s sign-in page. Please retry.');
    }
  }
  return (
    <SessionContext.Provider value={{ revision, actor }}>
      <div className="account-bar">
        <span>
          {actor
            ? 'Organization ' + actor.organization_id.slice(0, 8) + ' · ' + actor.role
            : 'Your community food workspace'}
        </span>
        <div className="actions">
          {manager && !signedIn && (
            <button className="quiet-button" onClick={() => void signIn()}>
              Sign in
            </button>
          )}
          {signedIn && (
            <button
              className="quiet-button"
              onClick={() => {
                void manager?.removeUser();
                setAccessToken();
                setOrganization();
                setSignedIn(false);
                setActor(undefined);
                setRevision((v) => v + 1);
              }}
            >
              Sign out of FoodBridge
            </button>
          )}
          {role && choices.length > 1 && (
            <button className="text-button" onClick={() => setSelect((v) => !v)}>
              Choose organization
            </button>
          )}
        </div>
      </div>
      {select && (
        <form
          className="organization-form"
          onSubmit={(event) => {
            event.preventDefault();
            setOrganization(org);
            setRevision((v) => v + 1);
          }}
        >
          <label htmlFor="organization">Organization</label>
          <select
            id="organization"
            value={org}
            onChange={(event) => setOrg(event.target.value)}
            required
          >
            <option value="">Choose your organization</option>
            {choices.map((item) => (
              <option key={item.organization_id} value={item.organization_id}>
                {item.organization_name}
              </option>
            ))}
          </select>
          <button>Use organization</button>
        </form>
      )}
      {error && (
        <Notice error>
          {error}
          {!manager && ' Organization sign-in has not been configured for this installation.'}
        </Notice>
      )}
      {!ready || (role && resolvedScope !== `${role}:${revision}`) ? (
        <p role="status">Loading your workspace…</p>
      ) : (
        <div key={`${role}:${revision}`}>{children}</div>
      )}
    </SessionContext.Provider>
  );
}
