import { useEffect, useRef } from 'react';
import { Link, NavLink, Route, Routes, useLocation } from 'react-router-dom';
import { ApiStatus } from './components/ApiStatus';
import { SessionProvider } from './components/SessionProvider';
import { WorkspaceIcon } from './components/WorkspaceIcon';
import { DonorPage } from './features/donor/DonorPage';
import { RecipientPage } from './features/recipient/RecipientPage';
import { DriverPage } from './features/driver/DriverPage';
import { OperationsPage } from './features/operations/OperationsPage';

export function App() {
  const { pathname } = useLocation();
  const previousPath = useRef(pathname);
  useEffect(() => {
    if (previousPath.current === pathname) return;
    previousPath.current = pathname;
    document.getElementById('content')?.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }, [pathname]);
  return (
    <div className="app-shell">
      <a className="skip-link" href="#content">
        Skip to content
      </a>
      <header className="app-header">
        <NavLink to="/" className="wordmark" aria-label="FoodBridge home">
          food<span>bridge</span>
          <span className="brand-dot">●</span>
        </NavLink>
        <nav className="workspace-nav" aria-label="Workspace">
          {[
            { path: 'donor', label: 'Donor', icon: 'donor' },
            { path: 'recipient', label: 'Receiver', icon: 'recipient' },
            { path: 'driver', label: 'Driver', icon: 'driver' },
            { path: 'operations', label: 'Operations', icon: 'operator' },
          ].map((item) => (
            <NavLink key={item.path} to={'/' + item.path}>
              <WorkspaceIcon name={item.icon} />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <span className="header-caption">Good food. Stronger communities.</span>
      </header>
      <main id="content" tabIndex={-1}>
        <SessionProvider>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/auth/callback" element={<p role="status">Completing sign-in…</p>} />
            <Route
              path="/auth/error"
              element={
                <section className="access-pending">
                  <p className="eyebrow">Account access</p>
                  <h1>Let’s start sign-in again.</h1>
                  <p>
                    We couldn’t complete that sign-in. The link may have expired, already been used,
                    or been opened in a different browser.
                  </p>
                  <p>
                    Your verification or password change may still be complete. Start a fresh
                    sign-in to continue.
                  </p>
                  <Link className="button" to="/donor">
                    Return to sign in
                  </Link>
                </section>
              }
            />
            <Route path="/donor/*" element={<DonorPage />} />
            <Route path="/recipient/*" element={<RecipientPage />} />
            <Route path="/driver/*" element={<DriverPage />} />
            <Route path="/operations/*" element={<OperationsPage />} />
            <Route
              path="*"
              element={
                <>
                  <h1>Page not found</h1>
                  <Link to="/">Return to FoodBridge</Link>
                </>
              }
            />
          </Routes>
        </SessionProvider>
      </main>
      <footer>
        <span className="wordmark">
          food<span>bridge</span>
        </span>
        <p>
          Connecting surplus food with the people who can use it. One thoughtful handoff at a time.
        </p>
      </footer>
    </div>
  );
}
function HomePage() {
  return (
    <>
      <section className="hero">
        <div>
          <p className="eyebrow">FROM SURPLUS TO SOMETHING GOOD</p>
          <h1>
            Less food wasted.
            <br />
            <em>More community nourished.</em>
          </h1>
          <p>
            A shared place for kitchens, receiving organizations and drivers to turn surplus food
            into a timely delivery.
          </p>
          <Link className="button" to="/donor">
            Share surplus food
          </Link>
        </div>
        <div className="journey" aria-label="Donation journey">
          <div>
            <span>01</span>
            <strong>Share</strong>
            <p>Describe your surplus and confirm the details.</p>
          </div>
          <div>
            <span>02</span>
            <strong>Connect</strong>
            <p>An eligible receiver accepts the offer.</p>
          </div>
          <div>
            <span>03</span>
            <strong>Deliver</strong>
            <p>A driver completes the handoff safely.</p>
          </div>
        </div>
      </section>
      <div className="section-heading">
        <h2>Find your workspace</h2>
        <span className="eyebrow">ONE CONNECTED COMMUNITY</span>
      </div>
      <div className="workspace-links">
        {[
          {
            path: 'donor',
            title: 'I have food to share',
            text: 'Post surplus and follow its journey.',
            number: '01',
          },
          {
            path: 'recipient',
            title: 'We receive donations',
            text: 'Review offers and manage acceptance.',
            number: '02',
          },
          {
            path: 'driver',
            title: 'I make the connection',
            text: 'Manage assignments and confirm delivery.',
            number: '03',
          },
          {
            path: 'operations',
            title: 'I coordinate the work',
            text: 'Monitor progress and resolve exceptions.',
            number: '04',
          },
        ].map((item) => (
          <Link key={item.path} to={'/' + item.path}>
            <span className="eyebrow">{item.number}</span>
            <h3>{item.title}</h3>
            <p>{item.text}</p>
          </Link>
        ))}
      </div>
      <ApiStatus />
    </>
  );
}
