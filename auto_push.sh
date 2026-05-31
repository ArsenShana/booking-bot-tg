#!/bin/bash

cd "/root/Zaman vot/telegram_zaman" || exit 1

git add api.py database.py config.py bot.py webapp_server.py \
        setup.sh tunnel.sh requirements.txt \
        webapp/index.html webapp/admin.html webapp/css/style.css webapp/js/app.js 2>/dev/null

if git diff --cached --quiet; then
    echo "[$(date '+%Y-%m-%d %H:%M')] No changes to commit"
    exit 0
fi

git commit -m "Auto-save: $(date '+%Y-%m-%d %H:%M')"
git push origin master && echo "[$(date '+%Y-%m-%d %H:%M')] Pushed successfully" \
                       || echo "[$(date '+%Y-%m-%d %H:%M')] Push failed"
