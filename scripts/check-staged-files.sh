#!/usr/bin/env bash
set -euo pipefail

staged_files="$(git -c core.quotePath=false diff --cached --name-only)"

while IFS= read -r file; do
  case "$file" in
    .env.example|*/.env.example) ;;
    .env|*/.env|.env.*|*/.env.*)
      echo "错误：暂存区包含 ${file}。请取消暂存并仅提交 .env.example。" >&2
      exit 1
      ;;
  esac
done <<< "$staged_files"

if printf '%s\n' "$staged_files" | grep -E '(^|/)(\.venv|venv|__pycache__|data/raw|backups)(/|$)|\.(pyc|sql\.gz|dump|sqlite3?|db)$' >/dev/null; then
  echo "错误：暂存区包含本地环境、缓存、原始数据或数据库备份。" >&2
  exit 1
fi

if git diff --cached -- . ':!scripts/check-staged-files.sh' ':!*.png' ':!*.jpg' ':!*.jpeg' | grep -E -i '(api[_-]?key|secret|token|password)[[:space:]]*=[[:space:]]*[^<[:space:]][^[:space:]]+' >/dev/null; then
  echo "错误：暂存文本可能包含真实凭据。请改用 .env 和环境变量。" >&2
  exit 1
fi

echo "通过：暂存文件未触发基础安全规则。"
