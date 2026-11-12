#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$(realpath "$0")")"

if [[ ! -f .env ]]; then
  echo "错误：项目根目录缺少 .env" >&2
  exit 1
fi

echo '拉取最新代码...'
git pull --ff-only

echo '构建新镜像（构建失败不会停止当前容器）...'
docker build -t smsbot:local .

if docker container inspect smsbot >/dev/null 2>&1; then
  echo '停止并删除旧应用容器...'
  docker stop -t 30 smsbot
  docker rm smsbot
fi

echo '启动新应用容器...'
docker run -d \
  --name smsbot \
  --env-file .env \
  --restart unless-stopped \
  -p 3434:8080 \
  -p 3444:8000 \
  smsbot:local

echo '等待应用健康检查...'
for ((attempt = 1; attempt <= 40; attempt++)); do
  health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}' smsbot)
  if [[ "$health" == healthy ]]; then
    echo '更新完成：应用已就绪。'
    exit 0
  fi
  if [[ "$health" == unhealthy ]] || [[ "$(docker inspect --format '{{.State.Running}}' smsbot)" != true ]]; then
    break
  fi
  sleep 3
done

echo '应用未通过健康检查，请查看日志：docker logs --tail 100 smsbot' >&2
docker logs --tail 30 smsbot >&2 || true
exit 1
