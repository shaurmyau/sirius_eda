#!/usr/bin/env bash
set -euo pipefail

# Куда писать: по умолчанию в stdout, можно передать файл аргументом:
#   ./dump.sh              -> в консоль
#   ./dump.sh out.txt      -> в файл out.txt
OUTPUT="${1:-/dev/stdout}"

# Собираем список файлов заранее, чтобы не поймать сам файл-результат
mapfile -t files < <(
    find . -type f \
        -not -path '*/__pycache__/*' \
        -not -path '*/.venv/*' \
        -not -path '*/.pytest_cache/*' \
        -not -path './.git/*' \
        -not -path '*/node_modules/*' \
        -not -path '*/.next/*' \
        -not -path './.lab8_backup/*' \
        -not -name 'package-lock.json' \
        -not -name 'celerybeat-schedule*' \
        | sort
)

{
    for file in "${files[@]}"; do
        # Пропускаем сам файл с выводом, если он лежит в проекте
        [[ "$file" == "./$OUTPUT" ]] && continue

        echo "${file#./} ->"
        cat -- "$file" 2>/dev/null || echo "(не удалось прочитать файл)"
        echo "============="
    done
} > "$OUTPUT"