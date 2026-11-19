import type { Metadata } from "next";
import Link from "next/link";

import { DishCard } from "@/components/DishCard";
import { getMenuItems, REVALIDATE_SECONDS } from "@/lib/api";
import { renderTimestamp } from "@/lib/time";

// ISR: готовый HTML страницы кешируется на 60 секунд.
// Значение должно быть литералом — Next.js читает его статически.
export const revalidate = 60;

const description = "Витрина «Сириус.Еды»: блюда кампуса из REST API, HTML собран на сервере.";

export const metadata: Metadata = {
  title: "Меню",
  description,
  alternates: { canonical: "/menu" },
  openGraph: {
    title: "Меню · Сириус.Еда",
    description,
    type: "website",
    url: "/menu",
    siteName: "Сириус.Еда",
    locale: "ru_RU",
  },
  twitter: { card: "summary", title: "Меню · Сириус.Еда", description },
};

// Асинхронный серверный компонент: данные получаются до отправки HTML.
export default async function MenuPage() {
  const items = await getMenuItems();
  const renderedAt = renderTimestamp();

  return (
    <main className="page-shell menu-section" id="menu">
      <div className="section-heading mt-8">
        <div>
          <p className="eyebrow">
            <span className="eyebrow-dot" />
            Витрина · SSR
          </p>
          <h2>
            Меню<span className="heading-period">.</span>
          </h2>
          <p className="section-description">
            Данные отрендерены на сервере и видны в Ctrl+U.
          </p>
        </div>
        <div className="menu-count">
          <strong>{items.length}</strong>
          <span>
            блюд
            <br />в меню
          </span>
        </div>
      </div>

      {items.length === 0 ? (
        <section className="empty-state">
          <span aria-hidden="true">🍽️</span>
          <h3>Меню пока пустое</h3>
          <p>Добавьте блюда: запустите python seed.py в корне бэкенда.</p>
        </section>
      ) : (
        <div className="dish-grid mt-8">
          {items.map((item) => (
            <DishCard key={item.id} item={item} />
          ))}
        </div>
      )}

      <aside className="ssr-note">
        <span className="ssr-note__icon" aria-hidden="true">⚡</span>
        <div>
          <strong>Страница собрана на сервере Next.js в {renderedAt}</strong>
          <p>ISR: HTML и ответ API кешируются на {REVALIDATE_SECONDS} с.</p>
        </div>
        <Link className="ssr-note__link" href="/menu-csr">
          CSR-версия <span>↗</span>
        </Link>
      </aside>
    </main>
  );
}
