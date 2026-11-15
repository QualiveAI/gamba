#!/usr/bin/env node
/**
 * Сборка статики Mini App для Cloudflare Pages.
 *
 * Зачем отдельный build-шаг: в frontend/ лежат node_modules, скриншоты и
 * 300 МБ экспериментальных ассетов, а Pages принимает только то, что нужно
 * сайту. Собираем тонкий dist/ из реально используемых файлов.
 *
 * Запуск: node build-pages.mjs (из каталога frontend/).
 */
import { cp, mkdir, rm, readdir, stat } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const out = path.join(root, 'dist');

// Файлы верхнего уровня: страницы и стили.
const FILES = ['index.html', 'styles.css', 'admin.html', 'admin.js'];
// Каталоги, которые нужны целиком.
const DIRS = ['js', 'admin', 'assets/demo'];
// Отдельные ассеты, на которые ссылается разметка.
const ASSETS = ['assets/logo-mark.webp', 'assets/windrop-symbol.webp'];

async function copyFile(relative) {
  const from = path.join(root, relative);
  if (!existsSync(from)) {
    console.warn(`[build-pages] пропущено (нет файла): ${relative}`);
    return false;
  }
  const to = path.join(out, relative);
  await mkdir(path.dirname(to), { recursive: true });
  await cp(from, to);
  return true;
}

async function copyDir(relative) {
  const from = path.join(root, relative);
  if (!existsSync(from)) {
    console.warn(`[build-pages] пропущено (нет каталога): ${relative}`);
    return false;
  }
  const to = path.join(out, relative);
  await mkdir(path.dirname(to), { recursive: true });
  await cp(from, to, { recursive: true });
  return true;
}

await rm(out, { recursive: true, force: true });
await mkdir(out, { recursive: true });

for (const file of FILES) await copyFile(file);
for (const dir of DIRS) await copyDir(dir);
for (const asset of ASSETS) await copyFile(asset);

// Функция /api/* компилируется Pages отдельно, в статику не попадает.
const functionsSrc = path.join(root, 'functions');
if (existsSync(functionsSrc)) {
  console.log('[build-pages] функции Pages: frontend/functions (собираются платформой)');
}

let files = 0;
let bytes = 0;
async function walk(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      await walk(full);
      continue;
    }
    files += 1;
    bytes += (await stat(full)).size;
  }
}
await walk(out);
console.log(
  `[build-pages] готово: ${files} файлов, ${(bytes / 1024 / 1024).toFixed(1)} МБ → ${path.relative(process.cwd(), out)}`,
);
