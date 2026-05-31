#!/bin/bash

cd "/root/Zaman vot/telegram_zaman" || exit 1

# Nothing to commit — exit silently
if git diff --quiet && git diff --cached --quiet; then
    exit 0
fi

git add -A
git commit -m "Авто-бэкап: $(date '+%d.%m.%Y %H:%M')"
git push origin main
