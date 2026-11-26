export function WorkspaceIcon({ name }: { name: string }) {
  const paths: Record<string, React.ReactNode> = {
    donor: (
      <>
        <path d="M4 9h16l-2 11H6L4 9Z" />
        <path d="m8 9 4-6 4 6M9 13v3m6-3v3" />
      </>
    ),
    recipient: (
      <>
        <path d="m3 10 9-7 9 7M5 9v12h14V9M9 21v-7h6v7" />
      </>
    ),
    driver: (
      <>
        <path d="M3 6h11v12H3zM14 10h4l3 4v4h-7" />
        <circle cx="7" cy="18" r="2" />
        <circle cx="18" cy="18" r="2" />
      </>
    ),
    operator: (
      <>
        <rect x="3" y="3" width="7" height="7" rx="1.5" />
        <rect x="14" y="3" width="7" height="7" rx="1.5" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" />
        <rect x="14" y="14" width="7" height="7" rx="1.5" />
      </>
    ),
  };
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}
