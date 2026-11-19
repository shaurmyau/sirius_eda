export default function MenuItemLoading() {
  return (
    <main className="page-shell loading-page" aria-busy="true" aria-live="polite">
      <div className="loading-title shimmer" />
      <div className="loading-hero shimmer" />
    </main>
  );
}
