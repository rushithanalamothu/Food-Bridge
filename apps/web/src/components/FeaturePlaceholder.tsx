interface Props {
  title: string;
  owner: string;
  nextStep: string;
}

export function FeaturePlaceholder({ title, owner, nextStep }: Props) {
  return (
    <section>
      <p className="eyebrow">Implementation workspace · {owner}</p>
      <h1>{title}</h1>
      <p>{nextStep}</p>
      <p className="implementation-note">
        This route is scaffolded. Its business flow is not connected yet.
      </p>
    </section>
  );
}
