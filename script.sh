#!/usr/bin/env bash
# =============================================================================
# Практическая работа № 8 — SSR-витрина «Сириус.Еды» на Next.js.
#
# Запуск из КОРНЯ проекта (там, где лежат app/, docker-compose.yml, README.md):
#     bash setup_lab8.sh
#
# Что делает скрипт (можно запускать повторно):
#   Бэкенд (минимальные правки, существующая логика не меняется):
#     * app/modules/menu/service.py — + MenuService.get_menu_item()
#     * app/modules/menu/router.py  — + GET /menu/items/{item_id} (404, если нет)
#     * .env — в ALLOWED_ORIGINS добавляется http://127.0.0.1:3000 (CORS для /menu-csr)
#     * seed.py — наполнение меню блюдами (нового файла в проекте не было)
#     * tests/test_menu_item_endpoint.py — тесты нового эндпоинта
#     * README.md, start.txt, do_project.txt.sh — короткие дописки
#   Фронтенд (новая папка frontend/):
#     * Next.js 16 + TypeScript + Tailwind: SSR /menu и /menu/[id],
#       loading.tsx, error.tsx, SEO + ISR, CSR-страница /menu-csr,
#       check.sh, measure.sh, README.md с таблицей SSR vs CSR.
#
# Перед изменением каждого существующего файла его копия кладётся в .lab8_backup/.
# =============================================================================
set -euo pipefail

if [ ! -f app/main.py ] || [ ! -d app/modules/menu ]; then
  echo "ОШИБКА: запустите скрипт из корня проекта (нужны app/main.py и app/modules/menu)." >&2
  exit 1
fi

FRONT="frontend"
BACKUP=".lab8_backup"

backup() {
  # Однократная копия исходного файла перед правкой.
  if [ -f "$1" ] && [ ! -f "$BACKUP/$1" ]; then
    mkdir -p "$BACKUP/$(dirname "$1")"
    cp "$1" "$BACKUP/$1"
  fi
}

write_file() {
  # write_file <путь>  — содержимое берётся из stdin.
  mkdir -p "$(dirname "$1")"
  cat > "$1"
  echo "  + $1"
}

echo "== 1/4  Бэкенд: эндпоинт GET /menu/items/{id}"
backup app/modules/menu/service.py
backup app/modules/menu/router.py
python3 - <<'__LAB8_PY__'
import re
from pathlib import Path

# ---- service.py ------------------------------------------------------------
p = Path("app/modules/menu/service.py")
s = p.read_text(encoding="utf-8")
if "def get_menu_item(" in s:
    print("  = service.py: get_menu_item уже есть")
else:
    anchor = "    @staticmethod\n    def _to_dict(item) -> dict:"
    if anchor not in s:
        raise SystemExit("service.py: не найдена точка вставки (_to_dict)")
    new = (
        "    def get_menu_item(self, item_id: int) -> dict:\n"
        "        item = self.repository.get_menu_item_by_id(item_id)\n"
        "        if not item:\n"
        "            raise NotFoundError(\"Блюдо не найдено\")\n"
        "        return self._to_dict(item)\n\n"
    )
    p.write_text(s.replace(anchor, new + anchor, 1), encoding="utf-8")
    print("  ~ service.py: добавлен get_menu_item")

# ---- router.py -------------------------------------------------------------
p = Path("app/modules/menu/router.py")
s = p.read_text(encoding="utf-8")
if '"/items/{item_id}"' in s and "def read_menu_item(" in s:
    print("  = router.py: GET /items/{item_id} уже есть")
else:
    anchor = '@router.get("/categories/{category}")'
    if anchor not in s:
        raise SystemExit("router.py: не найдена точка вставки (/categories/{category})")
    new = (
        '@router.get("/items/{item_id}")\n'
        'def read_menu_item(item_id: int, service: MenuService = Depends(get_menu_service)):\n'
        '    """Одно блюдо (для SSR-карточки /menu/[id]). 404, если блюда нет."""\n'
        '    try:\n'
        '        return service.get_menu_item(item_id)\n'
        '    except ValueError as e:\n'
        '        raise to_http_error(e)\n\n\n'
    )
    p.write_text(s.replace(anchor, new + anchor, 1), encoding="utf-8")
    print("  ~ router.py: добавлен GET /items/{item_id}")

# ---- .env: CORS для CSR-страницы -------------------------------------------
p = Path(".env")
if p.exists():
    s = p.read_text(encoding="utf-8")
    m = re.search(r"^ALLOWED_ORIGINS=(.*)$", s, flags=re.M)
    if m and "127.0.0.1:3000" not in m.group(1) and '"http://localhost:3000"' in m.group(1):
        Path(".lab8_backup").mkdir(exist_ok=True)
        if not Path(".lab8_backup/.env").exists():
            Path(".lab8_backup/.env").write_text(s, encoding="utf-8")
        new_line = m.group(0).replace(
            '"http://localhost:3000"',
            '"http://localhost:3000","http://127.0.0.1:3000"', 1)
        p.write_text(s.replace(m.group(0), new_line, 1), encoding="utf-8")
        print("  ~ .env: в ALLOWED_ORIGINS добавлен http://127.0.0.1:3000 (перезапустите uvicorn)")
    else:
        print("  = .env: ALLOWED_ORIGINS не требует изменений")
else:
    print("  = .env не найден — пропуск (по умолчанию разрешён http://localhost:3000)")
__LAB8_PY__

write_file seed.py <<'__LAB8_EOF__'
"""Наполнение меню тестовыми блюдами (практическая работа № 8).

Идемпотентно: блюда с уже существующим названием не дублируются.
Запуск из корня проекта:  python seed.py
"""
from app.database import SessionLocal
from app.models import MenuItem
from app.modules.menu.repository import SqlMenuRepository

DISHES: list[tuple[str, float, str]] = [
    ("Сырники", 150, "food"),
    ("Борщ", 190, "food"),
    ("Паста карбонара", 320, "food"),
    ("Пицца Маргарита", 380, "food"),
    ("Оливье", 140, "food"),
    ("Куриный суп", 170, "food"),
    ("Американо", 110, "drink"),
    ("Капучино", 150, "drink"),
    ("Морс клюквенный", 90, "drink"),
    ("Круассан", 120, "other"),
]


def main() -> None:
    db = SessionLocal()
    try:
        existing = {name for (name,) in db.query(MenuItem.name).all()}
        added = 0
        for name, price, category in DISHES:
            if name in existing:
                continue
            db.add(MenuItem(name=name, price=price, is_available=True, category=category))
            added += 1
        db.commit()
        # Сбрасываем кеш Redis, чтобы /menu/items сразу увидел новые блюда.
        SqlMenuRepository(db).invalidate_cache()
        print(f"[seed] добавлено блюд: {added}, всего в справочнике: {len(existing) + added}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
__LAB8_EOF__

write_file tests/test_menu_item_endpoint.py <<'__LAB8_EOF__'
"""GET /menu/items/{id} — эндпоинт для SSR-карточки блюда (in-memory)."""
import os

os.environ["REPO_BACKEND"] = "memory"
os.environ["RATE_LIMIT_ENABLED"] = "False"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.entities import MenuItem  # noqa: E402
from app.main import app  # noqa: E402
from app.memory_store import memory_store  # noqa: E402


@pytest.fixture
def client():
    memory_store.clear()
    return TestClient(app)


def test_get_menu_item_ok(client):
    memory_store.menu_items[1] = MenuItem(1, "Сырники", 150.0, True, "food")
    r = client.get("/menu/items/1")
    assert r.status_code == 200
    assert r.json() == {
        "id": 1,
        "name": "Сырники",
        "price": 150.0,
        "is_available": True,
        "category": "food",
    }


def test_get_menu_item_not_found(client):
    r = client.get("/menu/items/999999")
    assert r.status_code == 404
__LAB8_EOF__

echo "== 2/4  Фронтенд: папка $FRONT/"
mkdir -p "$FRONT"
write_file "$FRONT/package.json" <<'__LAB8_EOF__'
{
  "name": "sirius-food-frontend",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start"
  },
  "dependencies": {
    "next": "16.4.5",
    "react": "19.3.0",
    "react-dom": "19.3.0"
  },
  "devDependencies": {
    "@tailwindcss/turbopack": "^4",
    "@types/node": "^20",
    "@types/react": "^19",
    "@types/react-dom": "^19",
    "tailwindcss": "^4",
    "typescript": "^5"
  }
}
__LAB8_EOF__

write_file "$FRONT/next.config.ts" <<'__LAB8_EOF__'
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Keep the lecture demo visually clean; the dev server logs still show build status.
  devIndicators: false,
  /*
   * В учебном проекте используем классическую модель кеширования Next.js:
   * fetch-запрос к REST API кешируется через `next: { revalidate: 60 }`.
   * Поэтому Cache Components (cacheComponents) намеренно выключены.
   */
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
__LAB8_EOF__

write_file "$FRONT/tsconfig.json" <<'__LAB8_EOF__'
{
  "compilerOptions": {
    "target": "ES2017",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "react-jsx",
    "incremental": true,
    "plugins": [
      {
        "name": "next"
      }
    ],
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": [
    "next-env.d.ts",
    "**/*.ts",
    "**/*.tsx",
    ".next/types/**/*.ts",
    ".next/dev/types/**/*.ts",
    "**/*.mts"
  ],
  "exclude": ["node_modules"]
}
__LAB8_EOF__

write_file "$FRONT/.gitignore" <<'__LAB8_EOF__'
# See https://help.github.com/articles/ignoring-files/ for more about ignoring files.

# dependencies
/node_modules
/.pnp
.pnp.*
.yarn/*
!.yarn/patches
!.yarn/plugins
!.yarn/releases
!.yarn/versions

# testing
/coverage

# next.js
/.next/
/out/

# production
/build

# misc
.DS_Store
*.pem

# debug
npm-debug.log*
yarn-debug.log*
yarn-error.log*
.pnpm-debug.log*

# env files (can opt-in for committing if needed)
.env*
!.env.example

# vercel
.vercel

# typescript
*.tsbuildinfo
next-env.d.ts
__LAB8_EOF__

write_file "$FRONT/src/app/globals.css" <<'__LAB8_EOF__'
@import "tailwindcss";

:root {
  color-scheme: light;
  --paper: #f4f2e9;
  --paper-deep: #ece9dd;
  --ink: #1d2d26;
  --muted: #7b8279;
  --forest: #183a2e;
  --forest-light: #254b3c;
  --lime: #d5f47a;
  --orange: #e16c42;
  --line: #e8e5da;
  --white: #fffefa;
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  -webkit-font-smoothing: antialiased;
}
button, a { -webkit-tap-highlight-color: transparent; }
a { color: inherit; text-decoration: none; }
button { font: inherit; }
::selection { background: var(--lime); color: var(--ink); }

.site-header {
  width: min(1280px, calc(100% - 64px));
  min-height: 86px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 28px;
}
.brand { display: inline-flex; align-items: center; gap: 11px; width: fit-content; }
.brand-mark {
  width: 42px; height: 42px; border-radius: 14px;
  display: grid; place-items: center;
  background: var(--forest); color: var(--lime);
  font-size: 19px; font-weight: 900; letter-spacing: -1.5px;
}
.brand-copy { display: grid; gap: 1px; }
.brand-copy strong { font-size: 15px; letter-spacing: -.04em; }
.brand-copy small { color: var(--muted); font-size: 10px; letter-spacing: .08em; text-transform: uppercase; }
.main-nav { display: flex; align-items: center; gap: 32px; color: #68736b; font-size: 13px; font-weight: 600; }
.main-nav a { transition: color .2s ease; }
.main-nav a:hover { color: var(--forest); }
.main-nav a span { color: var(--orange); }
.header-action {
  justify-self: end;
  display: inline-flex; align-items: center; gap: 18px;
  padding: 12px 16px 12px 19px; border-radius: 999px;
  background: var(--white); border: 1px solid var(--line);
  font-size: 12px; font-weight: 700;
  transition: transform .2s ease, border-color .2s ease;
}
.header-action:hover { transform: translateY(-2px); border-color: #b9c1ad; }
.header-action span { color: var(--orange); font-size: 16px; }

.page-shell { width: min(1280px, calc(100% - 64px)); margin: 0 auto; }
.hero-panel {
  min-height: 490px; position: relative; isolation: isolate; overflow: hidden;
  display: grid; grid-template-columns: 1.05fr .95fr; align-items: center;
  padding: clamp(38px, 6vw, 76px); border-radius: 32px;
  background: var(--forest); color: #fffefa;
}
.hero-panel::before {
  content: ""; position: absolute; z-index: -1; inset: 0;
  background: radial-gradient(circle at 83% 42%, rgba(213,244,122,.13), transparent 32%),
    radial-gradient(circle at 0% 100%, rgba(225,108,66,.17), transparent 35%);
}
.hero-panel::after {
  content: ""; position: absolute; z-index: -1; width: 410px; height: 410px;
  border: 1px solid rgba(255,255,255,.1); border-radius: 50%; right: 7%; top: 8%;
  box-shadow: 0 0 0 36px rgba(255,255,255,.025), 0 0 0 72px rgba(255,255,255,.02);
}
.hero-copy { max-width: 610px; position: relative; z-index: 2; }
.eyebrow { display: flex; align-items: center; gap: 9px; margin: 0 0 18px; color: #798078; font-size: 10px; font-weight: 800; letter-spacing: .15em; text-transform: uppercase; }
.eyebrow--light { color: rgba(255,255,255,.68); }
.eyebrow-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--orange); box-shadow: 0 0 0 4px rgba(225,108,66,.13); }
.eyebrow--light .eyebrow-dot { background: var(--lime); box-shadow: 0 0 0 4px rgba(213,244,122,.13); }
.hero-panel h1 { margin: 0; max-width: 660px; font-size: clamp(44px, 5.5vw, 76px); font-weight: 650; line-height: .99; letter-spacing: -.075em; }
.hero-panel h1 em { color: var(--lime); font-family: Georgia, "Times New Roman", serif; font-weight: 400; letter-spacing: -.07em; }
.hero-description { max-width: 440px; margin: 22px 0 0; color: rgba(255,255,255,.69); font-size: 15px; line-height: 1.7; }
.hero-actions { display: flex; flex-wrap: wrap; gap: 11px; margin-top: 29px; }
.button { min-height: 48px; display: inline-flex; justify-content: center; align-items: center; gap: 17px; padding: 0 19px; border: 0; border-radius: 999px; font-size: 12px; font-weight: 800; cursor: pointer; transition: transform .2s ease, background .2s ease; }
.button:hover { transform: translateY(-2px); }
.button--lime { background: var(--lime); color: var(--forest); }
.button--lime span { font-size: 16px; }
.button--outline { color: #fff; border: 1px solid rgba(255,255,255,.24); background: transparent; }
.button--outline:hover { background: rgba(255,255,255,.08); }
.button--dark { background: var(--forest); color: white; }
.hero-footnote { display: flex; align-items: center; gap: 11px; margin-top: 35px; color: rgba(255,255,255,.66); font-size: 11px; }
.hero-footnote__avatars { display: flex; padding-left: 2px; }
.hero-footnote__avatars i { width: 24px; height: 24px; margin-left: -3px; display: grid; place-items: center; border: 2px solid var(--forest); border-radius: 50%; background: #f1aa70; color: var(--forest); font-size: 8px; font-style: normal; font-weight: 900; }
.hero-footnote__avatars i:nth-child(2) { background: var(--lime); }
.hero-footnote__avatars i:nth-child(3) { background: #e9d8b9; }

.hero-visual { min-height: 370px; position: relative; display: grid; place-items: center; }
.hero-visual__halo { position: absolute; width: min(340px, 75%); aspect-ratio: 1; border-radius: 50%; background: rgba(213,244,122,.09); }
.hero-visual__dish { width: min(340px, 75%); aspect-ratio: 1; position: relative; z-index: 1; border: 1px solid rgba(255,255,255,.25); border-radius: 50%; padding: 14px; background: rgba(255,255,255,.08); box-shadow: 0 28px 80px rgba(0,0,0,.2); transform: rotate(-8deg); }
.hero-visual__dish .dish-art { height: 100%; border: 0; border-radius: 50%; }
.hero-visual__dish .dish-art__category { display: none; }
.hero-visual__dish .dish-art__plate { width: 65%; }
.hero-visual__dish .dish-art__plate span { font-size: clamp(70px, 9vw, 130px); }
.hero-visual__fallback { width: 250px; aspect-ratio: 1; display: grid; place-items: center; border-radius: 50%; background: #f9e4c6; font-size: 115px; }
.hero-callout { position: absolute; z-index: 3; display: grid; gap: 5px; padding: 12px 16px; border: 1px solid rgba(255,255,255,.22); border-radius: 15px; background: rgba(255,255,255,.94); color: var(--ink); box-shadow: 0 15px 45px rgba(0,0,0,.15); }
.hero-callout--top { top: 7%; right: 2%; display: flex; align-items: center; gap: 8px; font-size: 10px; font-weight: 800; transform: rotate(4deg); }
.hero-callout__spark { color: var(--orange); font-size: 18px; }
.hero-callout--bottom { bottom: 5%; left: 0; min-width: 188px; transform: rotate(-3deg); }
.hero-callout--bottom strong { font-size: 15px; }
.hero-callout--bottom > span:last-child { color: #6e776f; font-size: 11px; }
.hero-callout--bottom i { padding: 0 4px; color: var(--orange); font-style: normal; }
.hero-callout__label { color: #889087; font-size: 9px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
.hero-stamp { position: absolute; z-index: 2; right: 3%; bottom: 17%; width: 78px; height: 78px; display: grid; place-content: center; border: 1px solid rgba(213,244,122,.8); border-radius: 50%; color: var(--lime); font-size: 9px; font-weight: 900; letter-spacing: .1em; line-height: 1.5; text-align: center; transform: rotate(12deg); }

.tech-panel { display: grid; grid-template-columns: 1.3fr repeat(3, 1fr); gap: 22px; align-items: center; margin: 24px 0 100px; padding: 23px 28px; border: 1px solid #e5e2d8; border-radius: 20px; background: rgba(255,254,250,.72); }
.tech-panel__intro { display: grid; gap: 7px; }
.tech-panel__kicker { color: #92988e; font-size: 9px; font-weight: 800; letter-spacing: .16em; }
.tech-panel__intro strong { font-size: 15px; line-height: 1.35; letter-spacing: -.03em; }
.tech-fact { display: flex; align-items: center; gap: 12px; padding-left: 20px; border-left: 1px solid var(--line); }
.tech-fact__number { align-self: flex-start; color: var(--orange); font-family: Georgia, serif; font-size: 13px; font-style: italic; }
.tech-fact div { display: grid; gap: 4px; }
.tech-fact strong { font-size: 12px; }
.tech-fact small { color: var(--muted); font-size: 10px; }

.menu-section { padding-bottom: 54px; scroll-margin-top: 24px; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 24px; }
.section-heading .eyebrow { margin-bottom: 10px; }
.section-heading h2 { margin: 0; font-size: clamp(38px, 5vw, 58px); line-height: 1; letter-spacing: -.075em; }
.heading-period { color: var(--orange); }
.section-description { margin: 12px 0 0; color: var(--muted); font-size: 13px; line-height: 1.6; }
.menu-count { display: flex; align-items: center; gap: 12px; padding: 10px 0 4px 20px; border-left: 1px solid #dcd9ce; }
.menu-count strong { color: var(--orange); font-family: Georgia, serif; font-size: 43px; font-weight: 400; letter-spacing: -.06em; }
.menu-count span { color: var(--muted); font-size: 10px; line-height: 1.5; }
.category-nav { display: flex; gap: 8px; overflow-x: auto; padding: 25px 0 28px; scrollbar-width: none; }
.category-nav::-webkit-scrollbar { display: none; }
.category-chip { flex: 0 0 auto; padding: 10px 15px; border: 1px solid #e2dfd4; border-radius: 999px; color: #68736b; background: rgba(255,254,250,.62); font-size: 11px; font-weight: 700; transition: all .2s ease; }
.category-chip:hover, .category-chip--active { color: white; border-color: var(--forest); background: var(--forest); }
.menu-groups { display: grid; gap: 43px; }
.menu-group { scroll-margin-top: 24px; }
.menu-group__heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 15px; }
.menu-group__heading h3 { margin: 0; font-size: 20px; letter-spacing: -.05em; }
.menu-group__heading span { color: #999d94; font-size: 10px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.dish-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 17px; }
.dish-card { min-width: 0; overflow: hidden; border: 1px solid #e8e5da; border-radius: 20px; background: var(--white); box-shadow: 0 5px 18px rgba(38,48,40,.025); transition: transform .25s ease, box-shadow .25s ease, border-color .25s ease; }
.dish-card:hover { transform: translateY(-4px); border-color: #d9d6c9; box-shadow: 0 16px 36px rgba(38,48,40,.09); }
.dish-card__art-link { display: block; padding: 10px 10px 0; }
.dish-art { height: 185px; position: relative; isolation: isolate; overflow: hidden; display: grid; place-items: center; border: 1px solid rgba(34,47,38,.06); border-radius: 14px; }
.dish-art::before { content: ""; position: absolute; z-index: -1; width: 72%; aspect-ratio: 1; border: 1px solid rgba(255,255,255,.65); border-radius: 50%; box-shadow: 0 0 0 17px rgba(255,255,255,.15), 0 0 0 34px rgba(255,255,255,.12); }
.dish-art::after { content: ""; position: absolute; z-index: -1; inset: 0; background: linear-gradient(135deg, rgba(255,255,255,.32), transparent 50%, rgba(40,40,20,.04)); }
.dish-art--tomato { background: #f2c7a7; }
.dish-art--chili { background: #f0b69b; }
.dish-art--cream { background: #e9dec1; }
.dish-art--gold { background: #e8c981; }
.dish-art--orange { background: #e9b18c; }
.dish-art--rose { background: #ecc0b5; }
.dish-art--sea { background: #b7d4ca; }
.dish-art--spice { background: #dca47c; }
.dish-art--lime { background: #d2d8a1; }
.dish-art--butter { background: #e9d9aa; }
.dish-art--leaf { background: #bfd0a6; }
.dish-art--mint { background: #c2d9c2; }
.dish-art--berry { background: #e2bbc2; }
.dish-art--coffee { background: #d6bca4; }
.dish-art--citrus { background: #e4d889; }
.dish-art--latte { background: #e4c4a2; }
.dish-art--espresso { background: #c7aa8e; }
.dish-art--smoothie { background: #d1c1db; }
.dish-art--pastry { background: #e9c991; }
.dish-art--honey { background: #ecc87a; }
.dish-art--sage { background: #c7d3bb; }
.dish-art__plate { width: 118px; aspect-ratio: 1; position: relative; z-index: 1; display: grid; place-items: center; border: 7px solid rgba(255,255,255,.8); border-radius: 50%; background: radial-gradient(circle, #fffefa 0 58%, #f7f3e9 59% 100%); box-shadow: 0 13px 24px rgba(48,52,35,.16), inset 0 0 0 1px rgba(67,75,55,.08); transform: rotate(-7deg); transition: transform .35s ease; }
.dish-card:hover .dish-art__plate { transform: rotate(3deg) scale(1.04); }
.dish-art__plate span { font-size: 59px; filter: drop-shadow(0 5px 3px rgba(0,0,0,.1)); }
.dish-art__category { position: absolute; z-index: 2; top: 13px; left: 13px; padding: 6px 9px; border-radius: 999px; background: rgba(255,254,250,.78); color: #465047; font-size: 9px; font-weight: 800; }
.dish-art__spark { position: absolute; z-index: 2; color: rgba(255,255,255,.88); }
.dish-art__spark--one { top: 28%; right: 18%; font-size: 17px; }
.dish-art__spark--two { bottom: 20%; left: 18%; font-size: 12px; }
.dish-art__shadow { position: absolute; bottom: 20px; width: 90px; height: 15px; border-radius: 50%; background: rgba(54,49,34,.12); filter: blur(7px); }
.dish-art--compact .dish-art__plate { width: 72%; border-width: 10px; }
.dish-art--compact .dish-art__plate span { font-size: clamp(72px, 10vw, 132px); }
.dish-art--compact .dish-art__category { top: 7%; left: 7%; padding: 8px 12px; font-size: 10px; }
.dish-card__content { padding: 15px 16px 16px; }
.dish-card__meta { display: flex; justify-content: space-between; align-items: center; color: #92988f; font-size: 9px; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; }
.dish-card__id { color: #b2b5ac; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 9px; letter-spacing: 0; }
.dish-card__title-link { display: block; width: fit-content; margin-top: 8px; }
.dish-card__title { margin: 0; font-size: 17px; letter-spacing: -.045em; transition: color .2s ease; }
.dish-card__title-link:hover { color: var(--orange); }
.dish-card__note { min-height: 16px; margin: 5px 0 15px; color: #92988f; font-size: 10px; }
.dish-card__bottom { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.dish-card__price { white-space: nowrap; font-size: 15px; letter-spacing: -.04em; }
.add-button { min-height: 35px; display: inline-flex; justify-content: center; align-items: center; gap: 7px; padding: 0 12px; border: 1px solid #dfe4d9; border-radius: 999px; background: #f4f7ef; color: var(--forest); font-size: 10px; font-weight: 800; cursor: pointer; transition: all .2s ease; }
.add-button:hover:not(:disabled) { background: var(--lime); border-color: var(--lime); }
.add-button > span { font-size: 14px; line-height: 1; }
.add-button--added { background: var(--forest); border-color: var(--forest); color: white; }
.add-button--added:hover { background: var(--forest-light); border-color: var(--forest-light); }
.add-button:disabled { cursor: not-allowed; opacity: .55; }

.ssr-note { display: flex; align-items: center; gap: 14px; margin: 30px 0 80px; padding: 17px 20px; border: 1px solid #dfe6d7; border-radius: 16px; background: #edf1e6; }
.ssr-note__icon { width: 36px; height: 36px; flex: 0 0 auto; display: grid; place-items: center; border-radius: 11px; background: var(--forest); color: var(--lime); font-size: 18px; font-weight: 800; }
.ssr-note strong { font-size: 12px; }
.ssr-note p { margin: 4px 0 0; color: #798176; font-size: 10px; }
.ssr-note__link { margin-left: auto; color: #52704c; font-size: 10px; font-weight: 800; white-space: nowrap; }
.ssr-note__link:hover { color: var(--orange); }
.ssr-note__link span { margin-left: 3px; color: var(--orange); }
.ssr-note__badge { display: inline-flex; align-items: center; gap: 7px; margin-left: auto; padding: 8px 10px; border-radius: 999px; background: #fffefa; color: #637064; font-size: 9px; font-weight: 800; white-space: nowrap; }
.ssr-note__badge i, .footer-status i, .availability i { width: 7px; height: 7px; border-radius: 50%; background: #76a568; }

.breadcrumbs { display: flex; align-items: center; gap: 10px; margin: 24px 0 18px; color: #8a9086; font-size: 11px; }
.breadcrumbs a:hover, .back-link:hover { color: var(--orange); }
.detail-page { min-height: 70vh; }
.detail-card { display: grid; grid-template-columns: .95fr 1.05fr; gap: clamp(28px, 5vw, 68px); align-items: center; padding: clamp(20px, 4vw, 44px); border: 1px solid var(--line); border-radius: 28px; background: var(--white); }
.detail-card__art { min-height: 430px; position: relative; overflow: hidden; border-radius: 21px; background: var(--paper-deep); }
.detail-card__art .dish-art { height: 100%; min-height: 430px; border: 0; border-radius: 21px; }
.detail-card__art .dish-art__plate { width: 58%; }
.detail-card__art-caption { position: absolute; right: 16px; bottom: 15px; z-index: 2; padding: 9px 12px; border-radius: 999px; background: rgba(255,254,250,.85); color: #747d72; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 10px; }
.detail-card__info { max-width: 520px; padding: 18px 0; }
.detail-card__info h1 { margin: 0; font-size: clamp(42px, 5vw, 64px); line-height: .98; letter-spacing: -.075em; }
.detail-card__description { max-width: 420px; margin: 20px 0 28px; color: #747c73; font-size: 14px; line-height: 1.75; }
.detail-price-row { display: flex; justify-content: space-between; align-items: end; gap: 12px; padding: 19px 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.detail-price-row > div { display: grid; gap: 4px; }
.detail-price-label { color: #90968d; font-size: 9px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
.detail-price { font-size: 28px; letter-spacing: -.06em; }
.availability { display: inline-flex; align-items: center; gap: 7px; padding: 8px 10px; border-radius: 999px; background: #eef4e9; color: #607b56; font-size: 9px; font-weight: 800; }
.availability--no { background: #f8eee7; color: #a16d4e; }
.availability--no i { background: #d18c59; }
.detail-card__info > .add-button { min-height: 44px; margin-top: 18px; padding: 0 18px; font-size: 11px; }
.detail-tech { display: grid; gap: 9px; margin-top: 25px; color: #8b9188; font-size: 10px; }
.detail-tech b { display: inline-block; min-width: 42px; color: var(--forest); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 9px; }
.back-link { display: inline-block; margin: 21px 0 70px; color: #727a71; font-size: 11px; font-weight: 700; transition: color .2s ease; }

.csr-page { min-height: 72vh; padding-bottom: 60px; }
.csr-banner { display: flex; justify-content: space-between; align-items: center; gap: 30px; min-height: 300px; margin: 22px 0 22px; padding: clamp(32px, 5vw, 60px); border-radius: 28px; background: var(--forest); color: var(--white); }
.csr-banner h1 { margin: 0; font-size: clamp(38px, 5vw, 58px); line-height: 1; letter-spacing: -.07em; }
.csr-banner h1 em { color: var(--lime); font-family: Georgia, serif; font-weight: 400; }
.csr-banner p:not(.eyebrow) { max-width: 450px; margin: 16px 0 0; color: rgba(255,255,255,.67); font-size: 13px; line-height: 1.7; }
.csr-banner__status { width: 160px; height: 160px; flex: 0 0 auto; position: relative; display: grid; place-content: center; gap: 4px; border: 1px solid rgba(213,244,122,.48); border-radius: 50%; text-align: center; transform: rotate(8deg); }
.csr-banner__status strong { color: var(--lime); font-family: Georgia, serif; font-size: 40px; font-weight: 400; }
.csr-banner__status span { color: rgba(255,255,255,.65); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 8px; }
.csr-banner__status i { width: 8px; height: 8px; position: absolute; top: 10px; right: 18px; border-radius: 50%; background: var(--orange); }
.csr-explainer { display: flex; align-items: center; gap: 12px; margin: 24px 0; padding: 15px 18px; border: 1px solid #e5e2d8; border-radius: 15px; background: rgba(255,254,250,.74); }
.csr-explainer__icon { width: 31px; height: 31px; flex: 0 0 auto; display: grid; place-items: center; border-radius: 10px; background: #f4e5d7; color: var(--orange); font-weight: 800; }
.csr-explainer p { margin: 0; color: #717a70; font-size: 11px; line-height: 1.55; }
.csr-explainer p a { color: var(--forest); font-weight: 800; text-decoration: underline; text-underline-offset: 3px; }
.loading-inline, .error-inline { margin-left: auto; color: #798176; font-size: 10px; white-space: nowrap; }
.error-inline { color: #b34d39; }
.csr-grid { margin-top: 18px; }

.empty-state, .error-card { max-width: 580px; margin: 55px auto 100px; padding: 42px; border: 1px solid var(--line); border-radius: 24px; background: var(--white); text-align: center; }
.empty-state > span { font-size: 42px; }
.empty-state h3, .error-card h1 { margin: 12px 0 8px; font-size: 28px; letter-spacing: -.05em; }
.empty-state p, .error-card > p:not(.eyebrow) { margin: 0 auto 22px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.empty-state .button { margin: 0 auto; }
.error-card__icon { width: 48px; height: 48px; margin: 0 auto 18px; display: grid; place-items: center; border-radius: 16px; background: #f7e5d8; color: #bd6541; font-family: Georgia, serif; font-size: 26px; }
.error-card .eyebrow { justify-content: center; }

.loading-page { padding-top: 25px; padding-bottom: 80px; }
.shimmer { background: linear-gradient(100deg, #e7e5dc 20%, #f3f1e9 38%, #e7e5dc 56%); background-size: 200% 100%; animation: shimmer 1.4s ease-in-out infinite; }
@keyframes shimmer { to { background-position-x: -200%; } }
.loading-hero { height: 340px; border-radius: 30px; }
.loading-title { width: 240px; height: 42px; margin: 55px 0 24px; border-radius: 10px; }
.loading-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.loading-card { padding: 10px; border: 1px solid var(--line); border-radius: 20px; background: var(--white); }
.loading-card__art { height: 175px; border-radius: 14px; }
.loading-card__line { width: 70%; height: 14px; margin: 16px 5px 9px; border-radius: 999px; }
.loading-card__line--short { width: 38%; margin-top: 0; }

.site-footer { width: min(1280px, calc(100% - 64px)); min-height: 100px; margin: 0 auto; display: flex; align-items: center; gap: 24px; border-top: 1px solid #e2dfd4; }
.brand--footer .brand-mark { width: 35px; height: 35px; border-radius: 11px; font-size: 16px; }
.brand--footer .brand-copy strong { font-size: 12px; }
.brand--footer .brand-copy small { font-size: 8px; }
.site-footer > p { margin: 0; color: #92988f; font-size: 10px; }
.footer-status { display: inline-flex; align-items: center; gap: 7px; margin-left: auto; color: #7a857b; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 9px; }

@media (max-width: 980px) {
  .site-header, .page-shell, .site-footer { width: min(100% - 40px, 760px); }
  .site-header { grid-template-columns: 1fr auto; }
  .main-nav { display: none; }
  .hero-panel { grid-template-columns: 1.1fr .9fr; padding: 44px 34px; }
  .hero-panel h1 { font-size: clamp(42px, 6.5vw, 64px); }
  .hero-visual { min-height: 310px; }
  .tech-panel { grid-template-columns: 1fr 1fr; margin-bottom: 75px; }
  .tech-fact:nth-child(2) { border-left: 0; padding-left: 0; }
  .dish-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .detail-card { gap: 26px; }
  .detail-card__art, .detail-card__art .dish-art { min-height: 340px; }
}

@media (max-width: 640px) {
  .site-header, .page-shell, .site-footer { width: calc(100% - 28px); }
  .site-header { min-height: 72px; gap: 8px; }
  .brand-mark { width: 37px; height: 37px; border-radius: 12px; }
  .header-action { gap: 8px; padding: 10px 12px; font-size: 10px; }
  .hero-panel { min-height: 0; grid-template-columns: 1fr; gap: 12px; padding: 34px 24px 20px; border-radius: 24px; }
  .hero-panel h1 { font-size: clamp(43px, 12vw, 60px); }
  .hero-description { max-width: 100%; font-size: 13px; }
  .hero-actions { gap: 8px; margin-top: 23px; }
  .button { min-height: 44px; padding: 0 14px; font-size: 10px; }
  .hero-footnote { margin-top: 24px; }
  .hero-visual { min-height: 285px; margin-top: 2px; }
  .hero-visual__dish { width: 245px; }
  .hero-visual__halo { width: 245px; }
  .hero-callout--top { top: 0; right: 0; }
  .hero-callout--bottom { bottom: 0; left: 0; }
  .hero-stamp { right: -2px; bottom: 20%; width: 65px; height: 65px; font-size: 8px; }
  .tech-panel { grid-template-columns: 1fr 1fr; gap: 18px 12px; margin: 14px 0 58px; padding: 19px; }
  .tech-panel__intro { grid-column: 1 / -1; }
  .tech-panel__intro strong br { display: none; }
  .tech-fact { gap: 8px; padding-left: 10px; }
  .tech-fact:nth-child(2) { padding-left: 0; }
  .tech-fact__number { font-size: 10px; }
  .tech-fact strong { font-size: 10px; }
  .tech-fact small { font-size: 8px; }
  .menu-section { padding-bottom: 30px; }
  .section-heading { align-items: end; }
  .section-heading h2 { font-size: 42px; }
  .section-description { max-width: 270px; font-size: 11px; }
  .menu-count { gap: 6px; padding-left: 10px; }
  .menu-count strong { font-size: 32px; }
  .menu-count span { font-size: 8px; }
  .category-nav { margin-right: -14px; padding: 20px 14px 22px 0; }
  .category-chip { padding: 9px 12px; font-size: 9px; }
  .menu-groups { gap: 30px; }
  .menu-group__heading h3 { font-size: 17px; }
  .dish-grid { grid-template-columns: 1fr 1fr; gap: 9px; }
  .dish-card { border-radius: 15px; }
  .dish-card__art { padding: 7px 7px 0; }
  .dish-art { height: 125px; border-radius: 10px; }
  .dish-art__plate { width: 82px; border-width: 5px; }
  .dish-art__plate span { font-size: 43px; }
  .dish-art__category { top: 8px; left: 8px; padding: 5px 7px; font-size: 7px; }
  .dish-card__content { padding: 10px; }
  .dish-card__meta { font-size: 7px; }
  .dish-card__title { font-size: 13px; }
  .dish-card__note { min-height: 26px; margin: 4px 0 9px; font-size: 8px; line-height: 1.4; }
  .dish-card__bottom { align-items: start; flex-direction: column; gap: 8px; }
  .dish-card__price { font-size: 13px; }
  .add-button { width: 100%; min-height: 31px; font-size: 9px; }
  .ssr-note { align-items: flex-start; gap: 10px; margin: 20px 0 48px; padding: 13px; }
  .ssr-note__icon { width: 30px; height: 30px; border-radius: 9px; font-size: 15px; }
  .ssr-note strong { font-size: 10px; }
  .ssr-note p { max-width: 190px; font-size: 8px; line-height: 1.5; }
  .ssr-note__badge { align-self: center; padding: 7px; font-size: 0; }
  .ssr-note__badge i { width: 8px; height: 8px; }
  .ssr-note__link { margin-left: auto; font-size: 8px; }
  .site-footer { min-height: 82px; gap: 12px; }
  .site-footer > p { max-width: 120px; font-size: 8px; line-height: 1.5; }
  .footer-status { font-size: 0; }
  .footer-status i { width: 8px; height: 8px; }
  .detail-card { grid-template-columns: 1fr; gap: 16px; padding: 12px; border-radius: 21px; }
  .detail-card__art, .detail-card__art .dish-art { min-height: 260px; border-radius: 15px; }
  .detail-card__art .dish-art__plate { width: 54%; }
  .detail-card__info { padding: 12px 9px 18px; }
  .detail-card__info h1 { font-size: 44px; }
  .detail-card__description { margin: 14px 0 19px; font-size: 12px; }
  .detail-price { font-size: 23px; }
  .availability { padding: 7px; font-size: 8px; }
  .detail-tech { font-size: 9px; }
  .csr-banner { min-height: 0; margin-top: 10px; padding: 28px 22px; border-radius: 23px; }
  .csr-banner h1 { font-size: 38px; }
  .csr-banner__status { width: 83px; height: 83px; }
  .csr-banner__status strong { font-size: 27px; }
  .csr-banner__status span { display: none; }
  .csr-explainer { align-items: flex-start; flex-wrap: wrap; gap: 9px; padding: 12px; }
  .csr-explainer p { width: calc(100% - 42px); font-size: 9px; }
  .loading-inline, .error-inline { margin-left: 42px; font-size: 8px; }
  .loading-hero { height: 280px; }
  .loading-grid { grid-template-columns: 1fr 1fr; gap: 9px; }
  .loading-card__art { height: 125px; }
}
__LAB8_EOF__

write_file "$FRONT/src/app/layout.tsx" <<'__LAB8_EOF__'
import type { Metadata } from "next";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";
import "./globals.css";

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: "Сириус.Еда — витрина",
    template: "%s · Сириус.Еда",
  },
  description: "Меню кампуса «Сириус.Еды»: серверный рендеринг, REST API и блюда рядом.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ru">
      <body>
        <SiteHeader />
        {children}
        <SiteFooter />
      </body>
    </html>
  );
}
__LAB8_EOF__

write_file "$FRONT/src/app/page.tsx" <<'__LAB8_EOF__'
import { redirect } from "next/navigation";

export default function HomePage() {
  redirect("/menu");
}
__LAB8_EOF__

write_file "$FRONT/src/lib/presentation.ts" <<'__LAB8_EOF__'
import type { MenuItem } from "@/lib/api";

/**
 * Детерминированный подбор оформления карточки: одна и та же категория всегда
 * получает один и тот же тон и эмодзи. Работает с любыми данными бэкенда,
 * поэтому кит не зависит от конкретных названий блюд.
 */

const TONES = [
  "tomato", "chili", "cream", "gold", "orange", "rose", "sea", "spice",
  "lime", "butter", "leaf", "mint", "berry", "coffee", "citrus", "latte",
  "espresso", "smoothie", "pastry", "honey", "sage",
];

const EMOJI = [
  "🍕", "🍔", "🍣", "🍜", "🍝", "🥗", "🍰", "☕", "🥐", "🥞",
  "🍽️", "🥪", "🍲", "🧀", "🍤", "🥙", "🍩", "🧃", "🍮", "🥧",
];

function hash(text: string): number {
  let h = 0;
  for (const ch of text) {
    h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  }
  return h;
}

export type DishPresentation = {
  emoji: string;
  tone: string;
};

export function presentDish(item: MenuItem): DishPresentation {
  const key = item.category ?? item.name;
  const h = hash(key);
  return {
    emoji: EMOJI[h % EMOJI.length],
    tone: TONES[h % TONES.length],
  };
}
__LAB8_EOF__

write_file "$FRONT/src/components/AddToCartButton.tsx" <<'__LAB8_EOF__'
"use client";

import { useState } from "react";

export function AddToCartButton({
  available = true,
}: {
  available?: boolean;
}) {
  const [added, setAdded] = useState(false);

  return (
    <button
      className={`add-button${added ? " add-button--added" : ""}`}
      type="button"
      disabled={!available}
      aria-pressed={added}
      onClick={() => setAdded((value) => !value)}
    >
      <span aria-hidden="true">{!available ? "—" : added ? "✓" : "+"}</span>
      {!available ? "Нет в наличии" : added ? "Добавлено" : "В корзину"}
    </button>
  );
}
__LAB8_EOF__

write_file "$FRONT/src/components/DishArtwork.tsx" <<'__LAB8_EOF__'
export function DishArtwork({
  emoji,
  tone,
  category,
  compact = false,
}: {
  emoji: string;
  tone: string;
  category: string;
  compact?: boolean;
}) {
  return (
    <div
      className={`dish-art dish-art--${tone}${compact ? " dish-art--compact" : ""}`}
      aria-hidden="true"
    >
      <span className="dish-art__spark dish-art__spark--one">✳</span>
      <span className="dish-art__spark dish-art__spark--two">✦</span>
      <span className="dish-art__category">{category}</span>
      <span className="dish-art__plate"><span>{emoji}</span></span>
      <span className="dish-art__shadow" />
    </div>
  );
}
__LAB8_EOF__

write_file "$FRONT/src/components/DishCard.tsx" <<'__LAB8_EOF__'
import Link from "next/link";

import { formatPrice, type MenuItem } from "@/lib/api";
import { presentDish } from "@/lib/presentation";
import { AddToCartButton } from "@/components/AddToCartButton";
import { DishArtwork } from "@/components/DishArtwork";

export function DishCard({ item }: { item: MenuItem }) {
  const art = presentDish(item);
  const category = item.category ?? "Меню";

  return (
    <article className="dish-card">
      <Link
        className="dish-card__art-link"
        href={`/menu/${item.id}`}
        aria-label={`Подробнее: ${item.name}`}
      >
        <DishArtwork emoji={art.emoji} tone={art.tone} category={category} />
      </Link>
      <div className="dish-card__content">
        <div className="dish-card__meta">
          <span>{category}</span>
          <span className="dish-card__id">#{item.id}</span>
        </div>
        <Link href={`/menu/${item.id}`} className="dish-card__title-link">
          <h3 className="dish-card__title">{item.name}</h3>
        </Link>
        <div className="dish-card__bottom">
          <strong className="dish-card__price">{formatPrice(item.price)}</strong>
          <AddToCartButton available={item.is_available !== false} />
        </div>
      </div>
    </article>
  );
}
__LAB8_EOF__

write_file "$FRONT/src/components/SiteFooter.tsx" <<'__LAB8_EOF__'
import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <Link className="brand brand--footer" href="/menu">
        <span className="brand-mark" aria-hidden="true">с.</span>
        <span className="brand-copy">
          <strong>Сириус.Еда</strong>
          <small>Кухня рядом</small>
        </span>
      </Link>
      <p>Учебная витрина кампусного сервиса доставки.</p>
      <span className="footer-status"><i /> Next.js · FastAPI</span>
    </footer>
  );
}
__LAB8_EOF__

write_file "$FRONT/.env.example" <<'__LAB8_EOF__'
# Скопируйте файл в .env.local:
#   cp .env.example .env.local
# Если ваш бэкенд на другом порту/хосте — поменяйте значения здесь, код не трогаем.

# Адрес REST API бэкенда. Используют серверные fetch (Server Components).
# Переменные без NEXT_PUBLIC не попадают в клиентский бандл.
API_URL=http://127.0.0.1:8000

# Тот же адрес, но доступный и в браузере. Нужен CSR-странице /menu-csr.
# Origin фронтенда должен быть в ALLOWED_ORIGINS бэкенда (CORS).
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000

# Публичный адрес фронтенда (для metadataBase, canonical и Open Graph).
NEXT_PUBLIC_SITE_URL=http://localhost:3000
__LAB8_EOF__

write_file "$FRONT/src/app/icon.svg" <<'__LAB8_EOF__'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="18" fill="#183a2e"/>
  <text x="32" y="43" text-anchor="middle" font-family="Arial, sans-serif" font-size="34" font-weight="900" fill="#d5f47a">с.</text>
</svg>
__LAB8_EOF__

write_file "$FRONT/src/lib/api.ts" <<'__LAB8_EOF__'
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
__LAB8_EOF__

write_file "$FRONT/src/lib/time.ts" <<'__LAB8_EOF__'
/**
 * Время рендера страницы. Выводится на странице, чтобы наглядно видеть
 * SSR/ISR: при ISR время не меняется до истечения revalidate (60 с).
 */
export function renderTimestamp(): string {
  return new Date().toLocaleTimeString("ru-RU", { timeZone: "Europe/Moscow" }) + " МСК";
}
__LAB8_EOF__

write_file "$FRONT/src/components/SiteHeader.tsx" <<'__LAB8_EOF__'
import Link from "next/link";

import { PUBLIC_API_URL } from "@/lib/api";

export function SiteHeader() {
  return (
    <header className="site-header">
      <Link className="brand" href="/menu" aria-label="Сириус.Еда — к меню">
        <span className="brand-mark" aria-hidden="true">с.</span>
        <span className="brand-copy">
          <strong>Сириус.Еда</strong>
          <small>Кухня рядом</small>
        </span>
      </Link>

      <nav className="main-nav" aria-label="Основная навигация">
        <Link href="/menu#menu">Меню (SSR)</Link>
        <Link href="/menu-csr">Меню (CSR)</Link>
        <a href={`${PUBLIC_API_URL}/docs`} target="_blank" rel="noreferrer">
          API <span aria-hidden="true">↗</span>
        </a>
      </nav>

      <Link className="header-action" href="/menu#menu">
        Выбрать блюдо <span aria-hidden="true">↗</span>
      </Link>
    </header>
  );
}
__LAB8_EOF__

write_file "$FRONT/src/components/MenuCsr.tsx" <<'__LAB8_EOF__'
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
__LAB8_EOF__

write_file "$FRONT/src/app/not-found.tsx" <<'__LAB8_EOF__'
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
__LAB8_EOF__

write_file "$FRONT/src/app/menu/page.tsx" <<'__LAB8_EOF__'
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
  // Запрос к REST API выполняется на сервере Next.js (CORS не нужен).
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
__LAB8_EOF__

write_file "$FRONT/src/app/menu/loading.tsx" <<'__LAB8_EOF__'
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
__LAB8_EOF__

write_file "$FRONT/src/app/menu/error.tsx" <<'__LAB8_EOF__'
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
__LAB8_EOF__

write_file "$FRONT/src/app/menu/[id]/loading.tsx" <<'__LAB8_EOF__'
export default function MenuItemLoading() {
  return (
    <main className="page-shell loading-page" aria-busy="true" aria-live="polite">
      <div className="loading-title shimmer" />
      <div className="loading-hero shimmer" />
    </main>
  );
}
__LAB8_EOF__

write_file "$FRONT/src/app/menu/[id]/page.tsx" <<'__LAB8_EOF__'
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
__LAB8_EOF__

write_file "$FRONT/src/app/menu-csr/page.tsx" <<'__LAB8_EOF__'
import type { Metadata } from "next";

import { MenuCsr } from "@/components/MenuCsr";

// Страница-обёртка серверная (чтобы экспортировать metadata),
// а блюда загружает клиентский компонент MenuCsr уже в браузере.
export const metadata: Metadata = {
  title: "Меню (CSR)",
  description: "Демо клиентского рендеринга для сравнения с SSR.",
  robots: { index: false, follow: false },
};

export default function MenuCsrPage() {
  return <MenuCsr />;
}
__LAB8_EOF__

write_file "$FRONT/check.sh" <<'__LAB8_EOF__'
#!/usr/bin/env bash
# Объективные проверки SSR-витрины «Сириус.Еды».
# Берёт первое блюдо из REST API и ищет его название в HTML страниц фронтенда.
#
# Запуск из папки frontend (бэкенд и `npm run dev` / `npm start` уже запущены):
#   chmod +x check.sh && ./check.sh
#
# Переопределить адреса: FRONT_URL=... API_URL=... ./check.sh

set -u

FRONT="${FRONT_URL:-http://localhost:3000}"
API="${API_URL:-http://127.0.0.1:8000}"

pass=0
fail=0

report() {
  if [ "$1" -eq 0 ]; then
    echo "PASS  $2"
    pass=$((pass + 1))
  else
    echo "FAIL  $2"
    fail=$((fail + 1))
  fi
}

# Первое блюдо из API: id и название (дизайн-независимый маркер SSR).
# Бэкенд отдаёт { "status": "success", "items": [...] }; «голый» массив тоже ок.
read -r FIRST_ID FIRST_NAME <<EOF
$(curl -s "$API/menu/items" | python3 -c 'import sys, json
d = json.load(sys.stdin)
items = d.get("items") if isinstance(d, dict) else d
if isinstance(items, list) and items:
    print(items[0]["id"], items[0]["name"])
else:
    print("", "")' 2>/dev/null)
EOF

if [ -z "${FIRST_NAME:-}" ]; then
  echo "FAIL  REST API $API/menu/items не вернул список блюд (запустите: python seed.py)"
  echo
  echo "Итог: PASS=0 FAIL=1"
  exit 1
fi

echo "Маркер: блюдо #$FIRST_ID «$FIRST_NAME»"
echo

# 1. API отвечает списком.
curl -sf "$API/menu/items" >/dev/null 2>&1
report $? "API: GET $API/menu/items отвечает"

# 2. API отдаёт одно блюдо.
curl -sf "$API/menu/items/$FIRST_ID" >/dev/null 2>&1
report $? "API: GET $API/menu/items/$FIRST_ID отвечает"

# 3. API возвращает 404 для несуществующего блюда.
code=$(curl -s -o /dev/null -w '%{http_code}' "$API/menu/items/999999")
[ "$code" = "404" ]
report $? "API: несуществующее блюдо -> 404 (получено: $code)"

# 4. SSR: блюдо есть в HTML /menu.
MENU_HTML=$(curl -s "$FRONT/menu")
printf '%s' "$MENU_HTML" | grep -qF "$FIRST_NAME"
report $? "SSR: «$FIRST_NAME» присутствует в HTML /menu (Ctrl+U)"

# 5. SSR: блюдо есть в HTML карточки /menu/<id>.
ITEM_HTML=$(curl -s "$FRONT/menu/$FIRST_ID")
printf '%s' "$ITEM_HTML" | grep -qF "$FIRST_NAME"
report $? "SSR: «$FIRST_NAME» присутствует в HTML /menu/$FIRST_ID"

# 6. Метатеги карточки (9 баллов): title, description, Open Graph.
printf '%s' "$ITEM_HTML" | grep -qE '<title>[^<]*'"$FIRST_NAME"
report $? "SEO: <title> содержит название блюда"
printf '%s' "$ITEM_HTML" | grep -qE '<meta name="description"'
report $? "SEO: есть <meta name=\"description\">"
printf '%s' "$ITEM_HTML" | grep -qE '<meta property="og:title"'
report $? "SEO: есть <meta property=\"og:title\">"

# 7. Несуществующее блюдо -> 404 ИЛИ (при потоковой отдаче со loading.tsx)
#    статус 200 с мета-тегом noindex: Next.js уже отправил заголовки до notFound().
NF_HEADERS=$(mktemp)
NF_BODY=$(curl -s -D "$NF_HEADERS" "$FRONT/menu/999999")
nf_code=$(head -1 "$NF_HEADERS" | awk '{print $2}')
rm -f "$NF_HEADERS"
if [ "$nf_code" = "404" ] || printf '%s' "$NF_BODY" | grep -qE 'name="robots" content="noindex'; then
  report 0 "Фронтенд: /menu/999999 -> not found (HTTP $nf_code)"
else
  report 1 "Фронтенд: /menu/999999 должен давать 404/noindex (HTTP $nf_code)"
fi

# 8. (10 баллов) CSR-страница не содержит блюд в HTML.
if curl -sf -o /dev/null "$FRONT/menu-csr" 2>/dev/null; then
  if curl -s "$FRONT/menu-csr" | grep -qF "$FIRST_NAME"; then
    report 1 "CSR: в HTML /menu-csr не должно быть блюд (они есть)"
  else
    report 0 "CSR: в HTML /menu-csr нет блюд (данные грузит браузер)"
  fi
else
  echo "SKIP  /menu-csr недоступна"
fi

echo
echo "Итог: PASS=$pass FAIL=$fail"
[ "$fail" -eq 0 ]
__LAB8_EOF__

write_file "$FRONT/measure.sh" <<'__LAB8_EOF__'
#!/usr/bin/env bash
# Грубые замеры curl для SSR и CSR (дополнение к замерам в Chrome DevTools).
# curl НЕ выполняет JavaScript: для /menu-csr он покажет время получения только
# каркаса без блюд — это и есть наглядная разница с SSR.
#
#   ./measure.sh            # 3 замера на страницу
#   RUNS=5 ./measure.sh

set -u
FRONT="${FRONT_URL:-http://localhost:3000}"
RUNS="${RUNS:-3}"

for path in /menu /menu-csr; do
  echo "== $path"
  for i in $(seq 1 "$RUNS"); do
    curl -s -o /dev/null -H 'Cache-Control: no-cache' \
      -w "  замер $i: TTFB=%{time_starttransfer}s  total=%{time_total}s  размер=%{size_download}B\n" \
      "$FRONT$path"
  done
done
__LAB8_EOF__

write_file "$FRONT/README.md" <<'__LAB8_EOF__'
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
__LAB8_EOF__

chmod +x "$FRONT/check.sh" "$FRONT/measure.sh"

if [ ! -f "$FRONT/.env.local" ]; then
  cp "$FRONT/.env.example" "$FRONT/.env.local"
  echo "  + $FRONT/.env.local (из .env.example)"
else
  echo "  = $FRONT/.env.local уже существует — не трогаю"
fi

echo "== 3/4  Дописки в существующие файлы проекта"
python3 - <<'__LAB8_PY__'
from pathlib import Path

def backup(p: Path) -> None:
    b = Path(".lab8_backup") / p
    if p.exists() and not b.exists():
        b.parent.mkdir(parents=True, exist_ok=True)
        b.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")

# ---- README.md ---------------------------------------------------------------
MARK = "<!-- lab8-frontend -->"
p = Path("README.md")
section = MARK + """
## Практическая работа № 8 — SSR-витрина на Next.js

Фронтенд лежит в `frontend/` (Next.js 16, App Router, TypeScript, Tailwind).
Страницы `/menu` и `/menu/[id]` рендерятся на сервере Next.js и получают данные
по REST (`GET /menu/items`, `GET /menu/items/{id}`); есть `loading.tsx`,
`error.tsx`, SEO-метатеги, ISR (`revalidate = 60`) и CSR-версия `/menu-csr`
для сравнения. Подробности, проверки и сравнение SSR/CSR — `frontend/README.md`.

```bash
python seed.py                       # наполнить меню (идемпотентно)
uvicorn app.main:app --reload        # бэкенд, http://127.0.0.1:8000
cd frontend && npm install && cp -n .env.example .env.local && npm run dev
```

Изменения бэкенда: добавлен `GET /menu/items/{item_id}` (404, если блюда нет),
тесты — `tests/test_menu_item_endpoint.py`.
"""
if p.exists():
    s = p.read_text(encoding="utf-8")
    if MARK in s:
        print("  = README.md: раздел уже есть")
    else:
        backup(p)
        p.write_text(s.rstrip("\n") + "\n\n" + section, encoding="utf-8")
        print("  ~ README.md: добавлен раздел про ЛР № 8")
else:
    p.write_text(section, encoding="utf-8")
    print("  + README.md")

# ---- start.txt ---------------------------------------------------------------
p = Path("start.txt")
line = "Фронтенд (ЛР № 8): cd frontend && npm run dev   # http://localhost:3000"
if p.exists():
    s = p.read_text(encoding="utf-8")
    if "cd frontend && npm run dev" in s:
        print("  = start.txt: строка уже есть")
    else:
        backup(p)
        p.write_text(s.rstrip("\n") + "\n\n====================\n\n" + line + "\n", encoding="utf-8")
        print("  ~ start.txt: добавлена команда запуска фронтенда")

# ---- do_project.txt.sh: не тащить node_modules/.next в дамп ----------------
p = Path("do_project.txt.sh")
if p.exists():
    s = p.read_text(encoding="utf-8")
    needle = "-not -path './.git/*' \\"
    if "node_modules" in s:
        print("  = do_project.txt.sh: исключения уже есть")
    elif needle in s:
        backup(p)
        indent = s[: s.index(needle)].rsplit("\n", 1)[-1]
        extra = "".join(
            f"\n{indent}{x} \\"
            for x in ("-not -path '*/node_modules/*'",
                      "-not -path '*/.next/*'",
                      "-not -path './.lab8_backup/*'",
                      "-not -name 'package-lock.json'")
        )
        p.write_text(s.replace(needle, needle + extra, 1), encoding="utf-8")
        print("  ~ do_project.txt.sh: исключены node_modules, .next, package-lock.json, .lab8_backup")
    else:
        print("  ! do_project.txt.sh: не найдено место вставки — пропуск")
__LAB8_PY__

echo "== 4/4  Проверка синтаксиса изменённых Python-файлов"
python3 -m py_compile app/modules/menu/service.py app/modules/menu/router.py seed.py tests/test_menu_item_endpoint.py
echo "  OK"

cat <<'__LAB8_DONE__'

Готово. Дальше:

  1) Бэкенд (после правки .env и роутера uvicorn нужно перезапустить):
       docker compose up -d db redis
       source .venv/bin/activate
       pytest -q tests/test_menu_item_endpoint.py     # новые тесты
       python seed.py                                  # наполнить меню
       uvicorn app.main:app --reload
       curl -s http://127.0.0.1:8000/menu/items/1

  2) Фронтенд (нужны Node.js 20+ и npm 10+):
       cd frontend
       npm install
       npm run dev                                     # http://localhost:3000
       ./check.sh                                      # PASS/FAIL по пунктам

  3) ISR (production):      npm run build && npm start
  4) 10 баллов: откройте frontend/README.md и впишите свои замеры из Chrome DevTools
     в таблицу SSR vs CSR (строки со значениями ___).

Резервные копии изменённых файлов: .lab8_backup/
__LAB8_DONE__