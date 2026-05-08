#!/bin/bash
# Zaman cloudflared tunnel — auto-start + auto-update

LOG_PREFIX="[zaman-tunnel]"
ENV_FILE="/root/telegram_zaman/.env"
URL_FILE="/root/telegram_zaman/.tunnel_url"
CF_BIN="/usr/bin/cloudflared"

echo "$LOG_PREFIX Starting..."

# ─── Auto-update cloudflared ─────────────────────────────────────────────────
update_cloudflared() {
    CURRENT=$($CF_BIN --version 2>&1 | grep -oP '\d{4}\.\d+\.\d+' | head -1)
    LATEST=$(curl -sf "https://api.github.com/repos/cloudflare/cloudflared/releases/latest" \
        | grep '"tag_name"' | grep -oP '[\d.]+' | head -1)

    if [ -z "$LATEST" ]; then
        echo "$LOG_PREFIX Could not fetch latest version, skipping update"
        return
    fi

    if [ "$CURRENT" = "$LATEST" ]; then
        echo "$LOG_PREFIX cloudflared is up to date ($CURRENT)"
        return
    fi

    echo "$LOG_PREFIX Updating cloudflared $CURRENT → $LATEST"
    TMP=$(mktemp)
    if curl -sfL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" \
        -o "$TMP"; then
        chmod +x "$TMP"
        mv "$TMP" "$CF_BIN"
        echo "$LOG_PREFIX Updated to $LATEST"
    else
        echo "$LOG_PREFIX Update failed, keeping $CURRENT"
        rm -f "$TMP"
    fi
}

update_cloudflared

# ─── Update WEBAPP_URL in .env when tunnel URL is known ──────────────────────
on_url_found() {
    local URL="$1"
    echo "$LOG_PREFIX Tunnel URL: $URL"
    echo "$URL" > "$URL_FILE"

    # Update WEBAPP_URL= line in .env
    if grep -q "^WEBAPP_URL=" "$ENV_FILE" 2>/dev/null; then
        sed -i "s|^WEBAPP_URL=.*|WEBAPP_URL=${URL}|" "$ENV_FILE"
    else
        echo "WEBAPP_URL=${URL}/zaman" >> "$ENV_FILE"
    fi

    # Restart bot so it picks up the new URL
    echo "$LOG_PREFIX Restarting zaman-bot with new URL..."
    systemctl restart zaman-bot
}

# ─── Run tunnel ───────────────────────────────────────────────────────────────
URL_FOUND=0

$CF_BIN tunnel --url http://localhost:8088 \
    --no-autoupdate \
    --protocol http2 \
    2>&1 | while IFS= read -r line; do
    echo "$line"

    if [ "$URL_FOUND" = "0" ] && echo "$line" | grep -q "trycloudflare.com"; then
        TUNNEL_URL=$(echo "$line" | grep -oP 'https://[^\s]+\.trycloudflare\.com')
        if [ -n "$TUNNEL_URL" ]; then
            URL_FOUND=1
            on_url_found "$TUNNEL_URL"
        fi
    fi
done
