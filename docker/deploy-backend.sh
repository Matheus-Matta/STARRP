#!/usr/bin/env bash
# Troca a versão do backend SEM tirar do ar (blue/green):
#
#   bash deploy-backend.sh 1.0.2
#
# 1. baixa a imagem nova e roda as migrations com ela;
# 2. sobe o GREEN na versão nova e espera ficar saudável (o BLUE segue atendendo; o nginx divide entre os dois);
# 3. grava a versão no .env e sobe o BLUE, o worker e o beat na nova.
# Se algo falhar, volta sozinho: o .env e os containers trocados voltam à versão anterior (as migrations ficam).
#
# Migrations precisam ser compatíveis com a versão anterior por alguns minutos (as duas rodam juntas):
# adicionar coluna/tabela é seguro; remover ou renomear, faça em duas versões.
set -euo pipefail
cd "$(dirname "$0")"

version="${1:?uso: bash deploy-backend.sh <versão> (ex.: 1.0.2)}"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || { echo "Versão inválida: $version"; exit 1; }
[[ -f .env ]] || { echo "Falta o .env (copie de .env.example)."; exit 1; }

wait_healthy() {
  local service="$1" id status
  id="$(docker compose ps -q "$service")"
  for _ in $(seq 1 60); do
    status="$(docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || echo starting)"
    [[ "$status" == healthy ]] && { echo "✓ $service saudável"; return 0; }
    sleep 3
  done
  echo "✗ $service não ficou saudável em 3 minutos (docker compose logs $service)."
  return 1
}

echo "→ Baixando o backend $version"
BACKEND_VERSION="$version" BACKEND_GREEN_VERSION="$version" docker compose pull migrate backend-green

echo "→ Migrations ($version)"
BACKEND_VERSION="$version" docker compose run --rm migrate

cp .env .env.rollback
changed=()
rollback() {
  local code=$?
  trap - EXIT
  if [[ $code -ne 0 && ${#changed[@]} -gt 0 ]]; then
    echo "✗ Falhou: voltando ${changed[*]} à versão anterior"
    cp .env.rollback .env
    docker compose up -d --no-deps "${changed[@]}" || true
  fi
  rm -f .env.rollback
  exit "$code"
}
trap rollback EXIT

changed=(backend-green)
echo "→ Green na $version (blue segue atendendo)"
BACKEND_GREEN_VERSION="$version" docker compose up -d --no-deps backend-green
wait_healthy backend-green

echo "→ Blue, worker e beat na $version"
sed -i.bak -E "s/^BACKEND_VERSION=.*/BACKEND_VERSION=${version}/; s/^BACKEND_GREEN_VERSION=.*/BACKEND_GREEN_VERSION=/" .env
rm -f .env.bak
changed=(backend-blue worker beat backend-green)
docker compose up -d --no-deps backend-blue worker beat
wait_healthy backend-blue
# Green já está na versão do .env: o compose normalmente não recria. Se recriar, o blue (saudável) atende.
docker compose up -d --no-deps backend-green
wait_healthy backend-green

echo "✓ Backend $version no ar (blue e green)."
