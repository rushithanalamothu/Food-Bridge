export function WorkflowProgress({
  steps,
  current,
  complete = false,
  label,
}: {
  steps: string[];
  current: number;
  complete?: boolean;
  label: string;
}) {
  return (
    <ol className="workflow-progress" aria-label={label}>
      {steps.map((step, index) => {
        const done = complete || index < current;
        return (
          <li
            key={step}
            className={done ? 'is-complete' : index === current ? 'is-current' : ''}
            aria-current={!complete && index === current ? 'step' : undefined}
          >
            <span className="progress-marker" aria-hidden="true">
              {done ? '✓' : index + 1}
            </span>
            <span>
              {step}
              {done && <span className="sr-only"> completed</span>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
