/** The arxiviq mark: nested frames converging on a single point. */
export default function Mark({ className, title }: { className?: string; title?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1"
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
    >
      <rect x="1.5" y="1.5" width="21" height="21" />
      <rect x="7.5" y="7.5" width="9" height="9" />
      <path d="M1.5 1.5 7.5 7.5M22.5 1.5 16.5 7.5M1.5 22.5 7.5 16.5M22.5 22.5 16.5 16.5" />
      <circle cx="12" cy="12" r="1.75" fill="var(--signal)" stroke="none" />
    </svg>
  );
}
