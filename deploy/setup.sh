#!/usr/bin/env sh
# First-time setup on a Linux host: a livekit-server key pair, livekit.yaml at
# the repo root, backend/.env. After this the backend is plain compose:
#
#   deploy/setup.sh lab|home        once per machine; never overwrites a file that exists
#   cd backend && docker compose up -d --build
#   docker compose logs -f agent    (look for "registered worker" and "session for user=")
#   docker compose down
#
# `lab` is a private LAN: ws:// on 7880, media UDP 50000-60000, AUTH_MODE=dev.
# `home` is the Caddy shape in deploy/livekit.home.yaml; its .env still needs
# LIVEKIT_PUBLIC_URL and AUTH_MODE set by hand, see the README.
#
# Needs docker (the key pair is generated with the livekit-server image) and a
# user in the docker group. Nothing here needs root; the ufw rules it prints
# at the end do.
set -eu

shape=${1:-}
case "$shape" in
    lab|home) ;;
    *) echo "usage: deploy/setup.sh lab|home" >&2; exit 2 ;;
esac

root=$(cd "$(dirname "$0")/.." && pwd)
yaml="$root/livekit.yaml"
env="$root/backend/.env"
image=livekit/livekit-server:v1.13.6

if [ -f "$yaml" ]; then
    echo "keeping existing $yaml"
    key=$(sed -n 's/^  \(API[A-Za-z0-9]*\): *\([^ ]*\)$/\1 \2/p' "$yaml" | head -1)
else
    # generate-keys prints "API Key:  APIxxx" / "API Secret:  xxx"
    out=$(docker run --rm "$image" generate-keys)
    api_key=$(printf '%s\n' "$out" | sed -n 's/^API Key: *//p')
    api_secret=$(printf '%s\n' "$out" | sed -n 's/^API Secret: *//p')
    sed "s/^  APIx*:.*$/  $api_key: $api_secret/" "$root/deploy/livekit.$shape.yaml" > "$yaml"
    key="$api_key $api_secret"
    echo "wrote $yaml with a fresh key pair"
fi
api_key=${key% *}
api_secret=${key#* }

if [ -f "$env" ]; then
    echo "keeping existing $env"
else
    ip=$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.*src \([0-9.]*\).*/\1/p')
    # The Gemini key is asked for at a terminal, taken from the environment
    # otherwise, and left blank when neither has it, so the script can run over
    # a plain ssh command and the key be pasted into .env by hand afterwards.
    google=${GOOGLE_API_KEY:-}
    if [ -z "$google" ] && [ -t 0 ]; then
        printf 'GOOGLE_API_KEY (https://aistudio.google.com/apikey): '
        read -r google
    fi
    [ -n "$google" ] || echo "GOOGLE_API_KEY left blank; put it in $env before compose up" >&2
    sed -e "s|^LIVEKIT_PUBLIC_URL=.*|LIVEKIT_PUBLIC_URL=ws://$ip:7880|" \
        -e "s|^LIVEKIT_API_KEY=.*|LIVEKIT_API_KEY=$api_key|" \
        -e "s|^LIVEKIT_API_SECRET=.*|LIVEKIT_API_SECRET=$api_secret|" \
        -e "s|^GOOGLE_API_KEY=.*|GOOGLE_API_KEY=$google|" \
        "$root/backend/.env.example" > "$env"
    echo "wrote $env (AUTH_MODE=dev, LIVEKIT_PUBLIC_URL=ws://$ip:7880)"
fi

port=$(sed -n 's/^API_PORT=//p' "$env")
cat <<EOF

next: cd backend && docker compose up -d --build

if ufw is active, the glasses need these (root, once; adjust the subnet):
  sudo ufw allow from 192.168.50.0/24 to any port 7880,7881 proto tcp comment 'livekit signaling'
  sudo ufw allow from 192.168.50.0/24 to any port 50000:60000 proto udp comment 'livekit media'
  sudo ufw allow from 192.168.50.0/24 to any port ${port:-3000} proto tcp comment 'rayneo api'
EOF
