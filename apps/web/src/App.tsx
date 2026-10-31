import { NavLink, Route, Routes } from 'react-router-dom';
import { ApiStatus } from './components/ApiStatus';
import { DonorPage } from './features/donor/DonorPage';
import { RecipientPage } from './features/recipient/RecipientPage';
import { DriverPage } from './features/driver/DriverPage';
import { OperationsPage } from './features/operations/OperationsPage';

export function App() {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#content">
        Skip to content
      </a>
      <header>
        <NavLink to="/" className="wordmark" aria-label="FoodBridge home">
          food<span>bridge</span>
        </NavLink>
        <span className="environment-label">Development foundation</span>
      </header>
      <nav aria-label="Workspace">
        <NavLink to="/donor">Donor</NavLink>
        <NavLink to="/recipient">Recipient</NavLink>
        <NavLink to="/driver">Driver</NavLink>
        <NavLink to="/operations">Operations</NavLink>
      </nav>
      <main id="content">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/donor/*" element={<DonorPage />} />
          <Route path="/recipient/*" element={<RecipientPage />} />
          <Route path="/driver/*" element={<DriverPage />} />
          <Route path="/operations/*" element={<OperationsPage />} />
          <Route path="*" element={<h1>Page not found</h1>} />
        </Routes>
      </main>
      <footer>Scaffold only. No donations, reservations or sign-ins are processed yet.</footer>
    </div>
  );
}

function HomePage() {
  return (
    <>
      <p className="eyebrow">FoodBridge · Team workspace</p>
      <h1>One foundation for the whole team.</h1>
      <p>
        The role workspaces are ready for implementation. Start with your module’s README and the
        shared design document.
      </p>
      <ApiStatus />
    </>
  );
}
