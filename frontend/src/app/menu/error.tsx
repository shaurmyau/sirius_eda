"use client";

import { useRouter } from "next/navigation";
import { useEffect, useTransition } from "react";

import { PUBLIC_API_URL } from "@/lib/api";

// Границы ошибок обязаны быть клиентскими компонентами ("use client").
export default function MenuError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  useEffect(() => {
    console.error(error);
  }, [error]);

  // reset() один только перерисует клиентскую часть. Чтобы серверный
  // компонент заново запросил данные, нужен ещё router.refresh().
  const retry = () => {
    startTransition(() => {
      router.refresh();
      reset();
    });
  };

  return (
    <main className="page-shell">
      <section className="error-card" role="alert">
        <div className="error-card__icon" aria-hidden="true">!</div>
        <p className="eyebrow">
          <span className="eyebrow-dot" />
          Ошибка загрузки
        </p>
        <h1>Не удалось загрузить меню</h1>
        <p>
          Проверьте, что бэкенд запущен на {PUBLIC_API_URL}, и повторите попытку.
        </p>
        {error.digest && (
          <p className="detail-tech">Код ошибки: {error.digest}</p>
        )}
        <button
          className="button button--dark"
          type="button"
          onClick={retry}
          disabled={pending}
        >
          {pending ? "Повторяем…" : "Попробовать снова"}
        </button>
      </section>
    </main>
  );
}
