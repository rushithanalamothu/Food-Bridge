import { useEffect, useState } from 'react';
import { loadSession } from './api/session';
import { SessionBar } from './features/session/SessionBar';
import { NavLink, Route, Routes } from 'react-router-dom';
import { ApiStatus } from './components/ApiStatus';
import { DonorPage } from './features/donor/DonorPage';
import { RecipientPage } from './features/recipient/RecipientPage';
import { DriverPage } from './features/driver/DriverPage';
import { OperationsPage } from './features/operations/OperationsPage';

export function App() {
  const [sessionReady, setSessionReady] = useState(false);
  useEffect(() => {
    void loadSession()
      .catch(() => undefined)
      .finally(() => setSessionReady(true));
  }, []);
  return (
    <div className="app-shell">
      <a className="skip-link" href="#content">
        Skip to content
      </a>
      <header>
        <NavLink to="/" className="wordmark" aria-label="FoodBridge home">
          food<span>bridge</span>
        </NavLink>
        <span className="environment-label">Team workspace</span>
      </header>
      <SessionBar />
      <nav aria-label="Workspace">
        <NavLink to="/donor">Donor</NavLink>
        <NavLink to="/recipient">Recipient</NavLink>
        <NavLink to="/driver">Driver</NavLink>
        <NavLink to="/operations">Operations</NavLink>
      </nav>
      <main id="content">
        {sessionReady ? (
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/donor/*" element={<DonorPage />} />
            <Route path="/recipient/*" element={<RecipientPage />} />
            <Route path="/driver/*" element={<DriverPage />} />
            <Route path="/operations/*" element={<OperationsPage />} />
            <Route path="*" element={<h1>Page not found</h1>} />
          </Routes>
        ) : (
          <p role="status">Loading your session…</p>
        )}
      </main>
      <footer>
        FoodBridge · Confirmed food, accountable handoffs. Synthetic demo data is labeled in each
        workspace.
      </footer>
    </div>
  );
}

function HomePage() {
  return (
    <>
      <p className="eyebrow">FoodBridge · Team workspace</p>
      <h1>From donation to delivery.</h1>
      <p>
        Post confirmed food, coordinate pickup, and follow each handoff. Choose the workspace for
        your verified organization.
      </p>
      <ApiStatus />
    </>
  );
}
