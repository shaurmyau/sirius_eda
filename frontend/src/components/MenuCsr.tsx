"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { DishCard } from "@/components/DishCard";
import { normalizeMenuItems, PUBLIC_API_URL, type MenuItem } from "@/lib/api";

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: MenuItem[]; ms: number };

/**
 * CSR-версия меню: HTML-каркас приходит без блюд, данные браузер запрашивает
 * сам (useEffect + fetch, cache: "no-store"). Нужна только для сравнения с SSR.
 */
export function MenuCsr() {
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const started = performance.now();

    fetch(`${PUBLIC_API_URL}/menu/items`, {
      cache: "no-store",
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) throw new Error(`REST API вернул HTTP ${response.status}`);
        return response.json();
      })
      .then((data) =>
        setState({
          status: "ready",
          items: normalizeMenuItems(data),
          ms: Math.round(performance.now() - started),
        }),
      )
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          status: "error",
          message:
            error instanceof Error
              ? error.message
              : "Неизвестная ошибка. Проверьте бэкенд и CORS.",
        });
      });

    return () => controller.abort();
  }, [attempt]);

  const retry = () => {
    setState({ status: "loading" });
    setAttempt((value) => value + 1);
  };

  return (
    <main className="page-shell csr-page">
      <section className="csr-banner">
        <div>
          <p className="eyebrow eyebrow--light">
            <span className="eyebrow-dot" />
            CSR · рендеринг в браузере
          </p>
          <h1>
            Меню <em>после JS</em>
          </h1>
          <p>
            Сервер Next.js отдал только каркас. Блюда браузер запрашивает у
            REST API сам, поэтому в Ctrl+U их нет.
          </p>
        </div>
        <div className="csr-banner__status" aria-hidden="true">
          <i />
          <strong>{state.status === "ready" ? state.items.length : "…"}</strong>
          <span>{state.status === "ready" ? `${state.ms} ms` : "fetch"}</span>
        </div>
      </section>

      <div className="csr-explainer">
        <span className="csr-explainer__icon" aria-hidden="true">i</span>
        <p>
          Сравните с <Link href="/menu">SSR-версией</Link>: там данные уже в HTML.
          Запрос идёт из браузера на {PUBLIC_API_URL}, поэтому нужен CORS.
        </p>
        {state.status === "loading" && (
          <span className="loading-inline">Загрузка меню в браузере…</span>
        )}
        {state.status === "error" && (
          <span className="error-inline">Не удалось загрузить</span>
        )}
        {state.status === "ready" && (
          <span className="loading-inline">Загружено за {state.ms} мс</span>
        )}
      </div>

      {state.status === "loading" && (
        <div className="loading-grid csr-grid" aria-busy="true">
          {Array.from({ length: 6 }).map((_, index) => (
            <div key={index} className="loading-card">
              <div className="loading-card__art shimmer" />
              <div className="loading-card__line shimmer" />
              <div className="loading-card__line loading-card__line--short shimmer" />
            </div>
          ))}
        </div>
      )}

      {state.status === "error" && (
        <section className="error-card">
          <div className="error-card__icon" aria-hidden="true">!</div>
          <h1>Меню не загрузилось</h1>
          <p>{state.message}</p>
          <button className="button button--dark" type="button" onClick={retry}>
            Попробовать снова
          </button>
        </section>
      )}

      {state.status === "ready" && state.items.length === 0 && (
        <section className="empty-state">
          <span aria-hidden="true">🍽️</span>
          <h3>Меню пока пустое</h3>
          <p>Добавьте блюда: python seed.py в корне бэкенда.</p>
        </section>
      )}

      {state.status === "ready" && state.items.length > 0 && (
        <div className="dish-grid csr-grid">
          {state.items.map((item) => (
            <DishCard key={item.id} item={item} />
          ))}
        </div>
      )}
    </main>
  );
}
