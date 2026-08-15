export default function PlaceholderPage({
  title,
  description,
}: {
  title: string
  description: string
}) {
  return (
    <section className="page" aria-label={title}>
      <h2>{title}</h2>
      <div className="panel empty-state">
        <p>{description}</p>
        <p className="muted">对应能力将在后续阶段接入；当前不做可产生副作用的假开关。</p>
      </div>
    </section>
  )
}
