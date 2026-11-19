// Показывается, пока серверный компонент ждёт данные от REST API.
export default function MenuLoading() {
  return (
    <main className="page-shell loading-page" aria-busy="true" aria-live="polite">
      <div className="loading-title shimmer" />
      <div className="loading-grid">
        {Array.from({ length: 6 }).map((_, index) => (
          <div key={index} className="loading-card">
            <div className="loading-card__art shimmer" />
            <div className="loading-card__line shimmer" />
            <div className="loading-card__line loading-card__line--short shimmer" />
          </div>
        ))}
      </div>
    </main>
  );
}
