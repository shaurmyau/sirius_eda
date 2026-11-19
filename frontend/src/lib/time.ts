/**
 * Время рендера страницы. Выводится на странице, чтобы наглядно видеть
 * SSR/ISR: при ISR время не меняется до истечения revalidate (60 с).
 */
export function renderTimestamp(): string {
  return new Date().toLocaleTimeString("ru-RU", { timeZone: "Europe/Moscow" }) + " МСК";
}
