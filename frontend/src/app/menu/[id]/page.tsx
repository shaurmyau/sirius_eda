import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AddToCartButton } from "@/components/AddToCartButton";
import { DishArtwork } from "@/components/DishArtwork";
import { formatPrice, getMenuItem, REVALIDATE_SECONDS } from "@/lib/api";
import { presentDish } from "@/lib/presentation";
import { renderTimestamp } from "@/lib/time";

// ISR: HTML карточки кешируется на 60 секунд.
export const revalidate = 60;

type PageProps = {
  // В Next.js 16 params — это Promise.
  params: Promise<{ id: string }>;
};

// SEO: title, description и Open Graph формируются на сервере из данных блюда.
// Повторный getMenuItem() не создаёт второй запрос — Next.js дедуплицирует fetch.
export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  const item = await getMenuItem(id);

  if (!item) {
    return { title: "Блюдо не найдено", robots: { index: false } };
  }

  const category = item.category ?? "Меню";
  const description = `${item.name} — ${formatPrice(item.price)}. Категория: ${category}. Заказ в «Сириус.Еде».`;
  const ogTitle = `${item.name} · Сириус.Еда`;

  return {
    title: item.name,
    description,
    alternates: { canonical: `/menu/${item.id}` },
    openGraph: {
      title: ogTitle,
      description,
      type: "website",
      url: `/menu/${item.id}`,
      siteName: "Сириус.Еда",
      locale: "ru_RU",
    },
    twitter: { card: "summary", title: ogTitle, description },
  };
}

export default async function MenuItemPage({ params }: PageProps) {
  const { id } = await params;
  const item = await getMenuItem(id);

  // Если блюда нет — отдаём 404.
  if (!item) notFound();

  const art = presentDish(item);
  const category = item.category ?? "Меню";
  const available = item.is_available !== false;

  return (
    <main className="page-shell detail-page">
      <div className="breadcrumbs">
        <Link href="/menu">Меню</Link>
        <span aria-hidden="true">/</span>
        <span>{item.name}</span>
      </div>

      <article className="detail-card">
        <div className="detail-card__art">
          <DishArtwork emoji={art.emoji} tone={art.tone} category={category} compact />
          <span className="detail-card__art-caption">#{item.id}</span>
        </div>

        <div className="detail-card__info">
          <p className="eyebrow">
            <span className="eyebrow-dot" />
            {category}
          </p>
          <h1>{item.name}</h1>
          <p className="detail-card__description">
            Блюдо из меню кампуса «Сириус.Еды». Страница собрана на сервере:
            название и цена уже есть в HTML ответа.
          </p>

          <div className="detail-price-row">
            <div>
              <span className="detail-price-label">Цена</span>
              <strong className="detail-price">{formatPrice(item.price)}</strong>
            </div>
            <span className={`availability${available ? "" : " availability--no"}`}>
              <i />
              {available ? "В наличии" : "Нет в наличии"}
            </span>
          </div>

          <AddToCartButton available={available} />

          <div className="detail-tech">
            <span><b>SSR</b> Собрано на сервере Next.js в {renderTimestamp()}</span>
            <span><b>ISR</b> HTML кешируется на {REVALIDATE_SECONDS} с</span>
            <span><b>API</b> GET /menu/items/{item.id}</span>
          </div>
        </div>
      </article>

      <Link className="back-link" href="/menu">
        ← Назад к меню
      </Link>
    </main>
  );
}
