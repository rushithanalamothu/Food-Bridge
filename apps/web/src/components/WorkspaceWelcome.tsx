import { Button } from './Button';
import type { Role } from '../api/generated/workflow';
import { WorkspaceIcon } from './WorkspaceIcon';

const workspaces = {
  donor: {
    name: 'Donor',
    title: 'Something good starts with what you share.',
    description:
      'Give surplus food a place to go. Share what’s available, connect with a receiving organization, and follow every handoff.',
    tasks: ['Describe your surplus', 'Confirm the details', 'Follow its journey'],
  },
  recipient: {
    name: 'Receiver',
    title: 'More good food. More people around the table.',
    description:
      'Find the donations that work for your organization. Review offers, keep your receiving preferences up to date, and coordinate each delivery.',
    tasks: ['Review donation offers', 'Manage receiving preferences', 'Coordinate deliveries'],
  },
  driver: {
    name: 'Driver',
    title: 'You make the connection that matters.',
    description:
      'Help good food get where it’s needed. See your assignments, review handling details, and keep each pickup and delivery moving.',
    tasks: ['Review your assignments', 'Confirm each pickup', 'Complete the handoff'],
  },
  operator: {
    name: 'Operations',
    title: 'A clearer view of every shared meal.',
    description:
      'Bring the whole journey together. Follow donations, review decisions, and help your organization keep every handoff on track.',
    tasks: [
      'Follow donation progress',
      'Review the decision history',
      'Resolve workflow exceptions',
    ],
  },
};

export function WorkspaceWelcome({
  role,
  signIn,
  register,
}: {
  role: Role;
  signIn: () => void;
  register?: () => void;
}) {
  const workspace = workspaces[role];
  return (
    <section className="workspace-welcome" aria-labelledby="welcome-title">
      <div className="welcome-copy">
        <p className="welcome-label">
          <WorkspaceIcon name={role} />
          {workspace.name} workspace
        </p>
        <h1 id="welcome-title">{workspace.title}</h1>
        <p className="welcome-description">{workspace.description}</p>
        <div className="actions">
          <Button size="large" className="welcome-sign-in" onClick={signIn}>
            Sign in
          </Button>
          {register && (
            <Button size="large" variant="secondary" onClick={register}>
              Create account
            </Button>
          )}
        </div>
        <p className="welcome-access">Sign in to access your organization’s workspace.</p>
        <ul className="welcome-tasks">
          {workspace.tasks.map((task) => (
            <li key={task}>
              <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
                <path
                  d="m5 10 3 3 7-7"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              {task}
            </li>
          ))}
        </ul>
      </div>
      <div className="welcome-art" aria-hidden="true">
        <span className="art-caption">A LITTLE SURPLUS. A LOT OF POSSIBILITY.</span>
        <svg className="food-basket" viewBox="0 0 480 340" fill="none">
          <circle cx="240" cy="166" r="132" fill="#dce8d6" />
          <ellipse cx="240" cy="298" rx="134" ry="10" fill="#284f3e" opacity=".09" />
          <path d="M157 211c0-149 169-149 169 0" stroke="#315e45" strokeWidth="9" />
          <path d="m185 226-45-87c-12-24 19-45 35-20l57 87" fill="#d58b55" />
          <path
            d="m153 132 15-9m-4 29 14-9m-3 29 14-9"
            stroke="#ad6139"
            strokeWidth="4"
            strokeLinecap="round"
          />
          <path d="M164 119c-25-5-34-22-30-37 17 1 29 13 30 37Z" fill="#78946c" />
          <path d="M163 119c-4-28 6-42 21-44 8 17 1 33-21 44Z" fill="#315e45" />
          <path d="m234 218 23-101c7-31 51-31 59-6l17 110" fill="#e2be81" />
          <path
            d="m274 127 25 10m-30 14 34 12m-39 11 42 14"
            stroke="#bc945a"
            strokeWidth="5"
            strokeLinecap="round"
          />
          <path
            d="M206 230c-44-28-43-63-19-79 21 1 36 17 32 44-2-34 19-64 44-62 20 24 10 61-28 92"
            fill="#55794e"
          />
          <path d="m215 224 30-66" stroke="#b0c39a" strokeWidth="3" strokeLinecap="round" />
          <path
            d="m133 211 25 71c3 10 12 16 23 16h120c11 0 20-6 23-16l25-71H133Z"
            fill="#e9d5ae"
            stroke="#365d45"
            strokeWidth="4"
            strokeLinejoin="round"
          />
          <path
            d="m179 229 10 49m27-49 3 49m27-49-3 49m37-49-10 49m38-49-10 49"
            stroke="#c6ac7d"
            strokeWidth="4"
            strokeLinecap="round"
          />
          <path d="M131 211h220" stroke="#365d45" strokeWidth="9" strokeLinecap="round" />
          <path d="M344 106c18-4 29-16 29-32-17 0-28 13-29 32Z" fill="#9aac7c" />
          <path
            d="m108 225 4-12m-10 4 14 4M356 166l4-12m-10 4 14 4"
            stroke="#a77e53"
            strokeWidth="3"
            strokeLinecap="round"
          />
        </svg>
        <div className="art-note">
          <span className="art-note-icon">
            <WorkspaceIcon name="donor" />
          </span>
          <span>
            Good food belongs
            <br />
            <strong>at someone’s table.</strong>
          </span>
        </div>
        <div className="art-journey">
          <span>Share</span>
          <i />
          <span>Connect</span>
          <i />
          <span>Deliver</span>
        </div>
      </div>
    </section>
  );
}
