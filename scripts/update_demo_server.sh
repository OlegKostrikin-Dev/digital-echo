#!/usr/bin/env bash
# Обновление демо-стека (docker-compose.prod.yml) на сервере.
# Запускать из корня репозитория на машине, где крутится compose, например:
#   cd ~/digital-echo-core && bash scripts/update_demo_server.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f docker-compose.prod.yml ]]; then
  echo "Ожидается docker-compose.prod.yml в $ROOT" >&2
  exit 1
fi

echo "[1/3] git pull"
git pull origin main

echo "[2/3] Сборка и перезапуск контейнеров"
docker compose -f docker-compose.prod.yml up -d --build

echo "[3/4] Перезапуск web (Vite подхватывает bind-mount)"
docker compose -f docker-compose.prod.yml restart web

echo "[4/4] Перезапуск docs (MkDocs читает mkdocs.yml при старте — без рестарта навигация может не обновиться)"
docker compose -f docker-compose.prod.yml restart docs

echo "Готово."
echo "  API:  curl -s http://127.0.0.1:8001/api/health"
echo "  Docs: откройте :8080 с принудительным обновлением в браузере (Ctrl+F5), при необходимости очистите кэш."
