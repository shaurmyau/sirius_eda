/**
 * REST-клиент бэкенда «Сириус.Еда» (FastAPI).
 *
 * Адрес API берётся из окружения (.env.local): поменяйте API_URL /
 * NEXT_PUBLIC_API_URL — и код трогать не нужно.
 *
 * Контракт бэкенда:
 *   GET /menu/items      — { status: "success", items: [...] } (обёртка Cache-Aside);
 *   GET /menu/items/{id} — одно блюдо или 404.
 */

// Серверный адрес API. Переменные без NEXT_PUBLIC видны только на сервере
// Next.js и не попадают в клиентский бандл.
export const API_URL =
  process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

// Адрес API, доступный в браузере. Нужен CSR-странице /menu-csr.
export const PUBLIC_API_URL = process.env.NEXT_PUBLIC_API_URL ?? API_URL;

// ISR: сколько секунд Next.js держит в кеше результат fetch и готовый HTML.
export const REVALIDATE_SECONDS = 60;

export type MenuItem = {
  id: number;
  name: string;
  price: number;
  is_available?: boolean;
  category?: string | null;
};

/**
 * Бэкенд отдаёт список в обёртке { status, items }. Принимаем и обёртку,
 * и «голый» массив — так клиент не ломается, если формат ответа упростят.
 */
export function normalizeMenuItems(payload: unknown): MenuItem[] {
  if (Array.isArray(payload)) return payload as MenuItem[];
  if (
    payload !== null &&
    typeof payload === "object" &&
    Array.isArray((payload as { items?: unknown }).items)
  ) {
    return (payload as { items: MenuItem[] }).items;
  }
  throw new Error("REST API вернул неожиданный формат меню");
}

async function apiFetch(path: string): Promise<Response> {
  try {
    // ISR: ответ API кешируется Next.js на REVALIDATE_SECONDS секунд.
    return await fetch(`${API_URL}${path}`, {
      next: { revalidate: REVALIDATE_SECONDS },
    });
  } catch {
    // Сеть недоступна (бэкенд остановлен) — даём понятное сообщение для error.tsx.
    throw new Error(`REST API недоступен: ${API_URL}${path}`);
  }
}

export async function getMenuItems(): Promise<MenuItem[]> {
  const response = await apiFetch("/menu/items");
  if (!response.ok) {
    throw new Error(`REST API вернул HTTP ${response.status}`);
  }
  return normalizeMenuItems(await response.json());
}

export async function getMenuItem(id: number | string): Promise<MenuItem | null> {
  const numericId = Number(id);
  if (!Number.isInteger(numericId) || numericId <= 0) return null;

  const response = await apiFetch(`/menu/items/${numericId}`);
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`REST API вернул HTTP ${response.status}`);
  }
  return response.json();
}

export function formatPrice(price: number): string {
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "RUB",
    maximumFractionDigits: 0,
  }).format(price);
}
