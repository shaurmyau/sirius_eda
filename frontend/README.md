# Сириус.Еда — SSR-витрина (практическая работа № 8)

Next.js 16 (App Router) + TypeScript + Tailwind CSS + нативный `fetch`.
Витрина получает данные у REST API бэкенда «Сириус.Еды» (FastAPI) **на сервере**
и отдаёт браузеру готовый HTML.

**Реализовано (уровень 10 баллов):**

| Уровень | Что сделано | Где |
| --- | --- | --- |
| 6–7 | SSR списка `/menu` и карточки `/menu/[id]`, данные видны в Ctrl+U | `src/app/menu/page.tsx`, `src/app/menu/[id]/page.tsx` |
| 8 | `loading.tsx` и `error.tsx` (кнопка «Попробовать снова»), `notFound()` для отсутствующего блюда | `src/app/menu/loading.tsx`, `src/app/menu/error.tsx`, `src/app/not-found.tsx` |
| 9 | SEO-метатеги (`generateMetadata`: title, description, Open Graph) и ISR (`revalidate = 60`) | `src/app/menu/[id]/page.tsx`, `src/app/menu/page.tsx`, `src/lib/api.ts` |
| 10 | CSR-версия `/menu-csr` и сравнение SSR / CSR (ниже) | `src/app/menu-csr/page.tsx`, `src/components/MenuCsr.tsx` |

## Запуск

Бэкенд (из корня проекта, в отдельном терминале):

```bash
docker compose up -d db redis
source .venv/bin/activate
python seed.py                 # наполнить меню (идемпотентно)
uvicorn app.main:app --reload
curl -s http://127.0.0.1:8000/menu/items
```

Фронтенд:

```bash
cd frontend
npm install
cp -n .env.example .env.local   # адреса API и сайта
npm run dev                     # http://localhost:3000
```

Если бэкенд на другом хосте/порту — поменяйте `API_URL` и `NEXT_PUBLIC_API_URL`
в `.env.local` и перезапустите dev-сервер. Для `/menu-csr` origin фронтенда
(`http://localhost:3000`) должен быть в `ALLOWED_ORIGINS` бэкенда.

## Контракт с бэкендом

| Эндпоинт | Ответ |
| --- | --- |
| `GET /menu/items` | `{ "status": "success", "items": [ {id, name, price, is_available, category} ] }` |
| `GET /menu/items/{id}` | одно блюдо или `404` (эндпоинт добавлен в рамках этой работы) |

`src/lib/api.ts` принимает и обёртку `{ items }`, и «голый» массив.

## Проверки

```bash
chmod +x check.sh measure.sh
./check.sh                                                # PASS/FAIL по всем пунктам
curl -s http://localhost:3000/menu | grep -F "Сырники"    # SSR вручную
```

1. `/menu` → Ctrl+U: названия блюд есть в HTML.
2. `/menu/2` → Ctrl+U: название и цена в HTML, в `<head>` есть `<title>`,
   `<meta name="description">`, `<meta property="og:title">`.
3. Остановите бэкенд и откройте `/menu/999999` (или `/menu`, если страница ещё
   не в кеше): показывается `error.tsx` с кнопкой «Попробовать снова». Запустите
   бэкенд и нажмите кнопку — страница загрузится.
4. `/menu-csr` → Ctrl+U: блюд в HTML нет.

> Про статус 404: при `loading.tsx` Next.js отправляет заголовки раньше, чем
> выполнится `notFound()`, поэтому для `/menu/999999` может прийти HTTP 200 с
> `<meta name="robots" content="noindex">`. Это штатное поведение потоковой
> отдачи; `check.sh` учитывает оба варианта.

### Проверка ISR (только production)

```bash
npm run build && npm start
```

1. Откройте `/menu` — запомните время «Страница собрана на сервере … МСК».
2. Измените цену блюда через API (`PATCH /menu/items/{id}`, нужна роль с `menu:write`).
3. Обновите страницу в течение 60 с — время и цена не меняются (отдаётся кеш).
4. Подождите 60 с и обновите (возможно, дважды: stale-while-revalidate) — время
   и цена обновились.

В `npm run dev` ISR не работает: страницы рендерятся на каждый запрос.

## Три уровня кеша (не путать)

| Уровень | Что кешируется | Кто управляет |
| --- | --- | --- |
| Браузер | ответы и ресурсы | HTTP-заголовки |
| Next.js | готовый HTML и результаты `fetch` | `revalidate`, ISR |
| Redis | данные предметной области (меню) | бэкенд, Cache-Aside |

После `PATCH /menu/items/{id}` бэкенд сбрасывает Redis сразу, а HTML в кеше
Next.js обновится только после истечения 60 с.

## SSR vs CSR: сравнение в Chrome DevTools

Методика: DevTools → Network → «Disable cache», `npm run build && npm start`
(production), три замера на страницу (перезагрузка Ctrl+Shift+R). Метрики:
время до первого контента (Performance → FCP или Network → DOMContentLoaded) и
момент появления блюд на экране. Дополнительно можно запустить `./measure.sh`.

| Метрика | SSR: `/menu` | CSR: `/menu-csr` |
| --- | --- | --- |
| Данные в Ctrl+U | есть | нет |
| Первый контент | сразу, вместе с HTML | после загрузки JS и запроса к API |
| Запрос к API из браузера | нет (его делает сервер Next.js) | есть (виден в Network, нужен CORS) |
| Замер 1, FCP, мс | ___ | ___ |
| Замер 2, FCP, мс | ___ | ___ |
| Замер 3, FCP, мс | ___ | ___ |
| Блюда на экране (медиана), мс | ___ | ___ |

> Числовые строки заполните собственными замерами со своей машины: они зависят
> от железа и сети, поэтому здесь не подставлены.

**Вывод.** SSR показывает контент вместе с первым HTML-ответом: пользователь
видит блюда без ожидания JavaScript и второго запроса, а CSR сначала рисует
каркас и только после загрузки бандла и ответа API показывает данные. Поисковик
и превью в мессенджерах видят готовые блюда и метатеги только в SSR-версии; у
CSR в HTML пустой контейнер. Для публичной витрины, где важны скорость первой
загрузки и SEO, выбирается SSR (с ISR для снижения нагрузки на сервер
рендеринга); CSR оправдан для закрытых интерактивных разделов вроде личного
кабинета, где индексация не нужна, а данные зависят от пользователя.

## Структура

```text
frontend/
├── check.sh, measure.sh          # проверки и замеры
├── .env.example                  # адреса API и сайта
└── src/
    ├── app/
    │   ├── layout.tsx, page.tsx, globals.css, icon.svg, not-found.tsx
    │   ├── menu/                 # page.tsx (SSR+ISR), loading.tsx, error.tsx
    │   │   └── [id]/             # page.tsx (SSR, generateMetadata), loading.tsx
    │   └── menu-csr/page.tsx     # CSR-страница для сравнения
    ├── components/               # DishCard, DishArtwork, AddToCartButton, MenuCsr, шапка и подвал
    └── lib/                      # api.ts (REST-клиент), presentation.ts, time.ts
```
