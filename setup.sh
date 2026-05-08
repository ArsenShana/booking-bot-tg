#!/bin/bash
set -e

echo "=== Zaman Bot Setup ==="
cd /root/telegram_zaman

# 1. Check .env
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "⚠️  Создан файл .env — заполните BOT_TOKEN и WEBAPP_URL:"
    echo "    nano /root/telegram_zaman/.env"
    echo ""
    echo "Затем запустите setup.sh снова."
    exit 1
fi

source .env
if [ -z "$BOT_TOKEN" ] || [ "$BOT_TOKEN" = "your_bot_token_here" ]; then
    echo "❌ Укажите BOT_TOKEN в файле .env"
    exit 1
fi

# 2. Init DB and seed data
echo "→ Инициализация базы данных..."
python3 seed_demo.py

# 3. Enable nginx
echo "→ Настройка nginx..."
ln -sf /etc/nginx/sites-available/zaman /etc/nginx/sites-enabled/zaman
nginx -t && systemctl reload nginx

# 4. Enable & start services
echo "→ Запуск сервисов..."
systemctl daemon-reload
systemctl enable zaman-api zaman-bot
systemctl restart zaman-api
sleep 2
systemctl restart zaman-bot

echo ""
echo "✅ Бот запущен!"
echo ""
echo "Статус:"
systemctl is-active zaman-api && echo "  API: ✅ работает" || echo "  API: ❌ ошибка"
systemctl is-active zaman-bot && echo "  Bot: ✅ работает" || echo "  Bot: ❌ ошибка"
echo ""
echo "Логи бота:  journalctl -u zaman-bot -f"
echo "Логи API:   journalctl -u zaman-api -f"
echo ""
if [ -n "$WEBAPP_URL" ] && [ "$WEBAPP_URL" != "https://yourdomain.com/zaman" ]; then
    echo "WebApp URL: $WEBAPP_URL"
else
    echo "⚠️  Для WebApp нужен HTTPS домен."
    echo "   Укажите WEBAPP_URL в .env и настройте cloudflared или nginx с SSL."
fi
