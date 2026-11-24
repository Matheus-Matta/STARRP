#!/usr/bin/env bash
# Valida a tag da entidade e prepara a versão e as notas da release.
#
#   release-info.sh <entidade> <caminho> [<caminho>...]
#
# Tag: <entidade>-v<versão>, ex.: backend-v1.0.1, desktop-v2.3.0, mobile-v1.4.0-beta.1 (sufixo = pré-release).
# Saídas (GITHUB_OUTPUT): version, prerelease (true/false), previous (tag anterior da MESMA entidade).
# Notas (release-notes.md): só os commits desde a tag anterior que mexeram nos caminhos da entidade.
set -euo pipefail

entity="$1"; shift
tag="${GITHUB_REF_NAME:?GITHUB_REF_NAME vazio}"

if [[ ! "$tag" =~ ^${entity}-v([0-9]+\.[0-9]+\.[0-9]+)(-[0-9A-Za-z.-]+)?$ ]]; then
  echo "::error::Tag '$tag' fora do padrão ${entity}-v<maior>.<menor>.<correção> (ex.: ${entity}-v1.0.0)."
  exit 1
fi
version="${tag#"${entity}-v"}"
prerelease=false
[[ -n "${BASH_REMATCH[2]}" ]] && prerelease=true

# Tag anterior da mesma entidade: a última versão MENOR que a atual (ordem de versão). Versão final compara
# com a última final (as notas do 1.1.0 incluem o que já saiu nos betas dele); pré-release, com qualquer uma.
candidates="$(git tag --list "${entity}-v*" | grep -E "^${entity}-v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$" || true)"
if [[ "$prerelease" == false ]]; then
  candidates="$(grep -E -- '-v[0-9]+\.[0-9]+\.[0-9]+$' <<< "$candidates" || true)"
fi
# Ordem de versão com o pré-release ANTES da final (1.1.0-beta.1 < 1.1.0): o "-" do sufixo vira "~" só para ordenar.
previous="$( (printf '%s\n' "$candidates"; echo "$tag") | grep -v '^$' | sort -u \
  | sed -E 's/^(.*-v[0-9]+\.[0-9]+\.[0-9]+)-(.*)$/\1~\2\t&/; t; s/^(.*)$/\1\t\1/' \
  | sort -V -k1,1 | cut -f2 | grep -B1 -x "$tag" | grep -vx "$tag" || true)"

{
  echo "## ${entity} ${version}"
  echo
  if [[ -n "$previous" ]]; then
    echo "Mudanças em \`$*\` desde **${previous}**:"
    echo
    log="$(git log --no-merges --pretty='- %s (%h)' "${previous}..${tag}" -- "$@")"
  else
    echo "Primeira versão publicada. Mudanças em \`$*\`:"
    echo
    log="$(git log --no-merges --pretty='- %s (%h)' -n 50 "${tag}" -- "$@")"
  fi
  echo "${log:-- (nenhum commit nesses caminhos)}"
} > release-notes.md

{
  echo "version=${version}"
  echo "prerelease=${prerelease}"
  echo "previous=${previous}"
} >> "$GITHUB_OUTPUT"

echo "Versão ${version} (pré-release: ${prerelease}; anterior: ${previous:-nenhuma})"
cat release-notes.md
