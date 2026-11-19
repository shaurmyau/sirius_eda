import Link from "next/link";

export default function NotFound() {
  return (
    <main className="page-shell">
      <section className="empty-state">
        <span aria-hidden="true">🍽️</span>
        <h3>Такой страницы или блюда нет</h3>
        <p>Возможно, блюдо убрали из меню или ссылка набрана с ошибкой.</p>
        <Link className="button button--dark" href="/menu">
          Вернуться к меню
        </Link>
      </section>
    </main>
  );
}
