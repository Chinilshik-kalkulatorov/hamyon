#!/usr/bin/env bash
# =============================================================================
# Hamyon — bootstrap сервера (Ubuntu 22.04/24.04, GCP Compute Engine e2-small)
#
# Что делает: ставит всё, что нужно, чтобы поднять стек и пустить сюда Claude:
#   Docker + compose plugin, Node + Claude Code, gcloud, GitHub CLI, git, tmux.
#
# Запуск (в SSH-терминале VM):
#   curl -fsSL https://raw.githubusercontent.com/Chinilshik-kalkulatorov/hamyon/deploy-with-ui/deploy/bootstrap.sh | bash
# либо, если репозиторий уже склонирован:
#   bash deploy/bootstrap.sh
#
# После него: см. напечатанные "СЛЕДУЮЩИЕ ШАГИ" внизу.
# Скрипт идемпотентен — можно запускать повторно.
# =============================================================================
set -euo pipefail

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi
export DEBIAN_FRONTEND=noninteractive

log "1/6  Базовые пакеты (git, curl, tmux, jq, ca-certificates)"
$SUDO apt-get update -y
$SUDO apt-get install -y ca-certificates curl gnupg git tmux jq

log "2/6  Docker Engine + compose plugin"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | $SUDO sh
else
  echo "docker уже установлен — пропускаю"
fi
$SUDO systemctl enable --now docker
# дать текущему пользователю доступ к docker без sudo (вступит в силу при ре-логине)
$SUDO usermod -aG docker "$USER" || true

log "3/6  Node.js LTS + Claude Code (npm)"
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_lts.x | $SUDO -E bash -
  $SUDO apt-get install -y nodejs
else
  echo "node уже установлен ($(node -v)) — пропускаю"
fi
$SUDO npm install -g @anthropic-ai/claude-code

log "4/6  GitHub CLI (gh) — для доступа к приватному репозиторию"
if ! command -v gh >/dev/null 2>&1; then
  $SUDO mkdir -p -m 755 /etc/apt/keyrings
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | $SUDO tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null
  $SUDO chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | $SUDO tee /etc/apt/sources.list.d/github-cli.list >/dev/null
  $SUDO apt-get update -y
  $SUDO apt-get install -y gh
else
  echo "gh уже установлен — пропускаю"
fi

log "5/6  Google Cloud CLI (gcloud)"
if ! command -v gcloud >/dev/null 2>&1; then
  echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
    | $SUDO tee /etc/apt/sources.list.d/google-cloud-sdk.list >/dev/null
  curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
    | $SUDO gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
  $SUDO apt-get update -y
  $SUDO apt-get install -y google-cloud-cli
else
  echo "gcloud уже установлен — пропускаю"
fi

log "6/6  Готово. Версии:"
docker --version || true
docker compose version || true
node --version || true
gh --version | head -1 || true
gcloud --version | head -1 || true

cat <<'NEXT'

============================================================================
  СЛЕДУЮЩИЕ ШАГИ (делаешь ты в этом же SSH-терминале)
============================================================================
  ВАЖНО: чтобы docker работал без sudo, переподключись по SSH один раз
         (закрой и снова открой кнопку SSH в консоли GCP). Либо выполни:
         newgrp docker

  1) Доступ к приватному репозиторию:
        gh auth login           # выбери GitHub.com -> HTTPS -> вход в браузере

  2) Склонировать проект (если ещё не склонирован) и зайти в него:
        gh repo clone Chinilshik-kalkulatorov/hamyon
        cd hamyon
        git checkout deploy-with-ui

  3) Запустить Claude в постоянной сессии tmux (переживёт закрытие браузера):
        tmux new -s claude
        claude                  # войди в аккаунт Anthropic (вставь код входа)

  4) Дальше просто напиши Claude:
        "Заверши деплой hamyon по плану: собери .env.prod со свежими
         секретами, подними стек и настрой Cloudflare Tunnel."

  Отключиться от tmux, не закрывая Claude:  Ctrl-b, затем d
  Вернуться позже:                          tmux attach -t claude
============================================================================
NEXT
