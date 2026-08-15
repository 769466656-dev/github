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

if ! python3 - <<'PY'
import re
import subprocess
import sys
from pathlib import Path

files = subprocess.check_output(
    ["git", "-c", "core.quotePath=false", "diff", "--cached", "--name-only"],
    text=True,
).splitlines()
literal_assignment = re.compile(
    r'(?i)\b(api[_-]?key|secret|token|password|passwd|access[_-]?key|private[_-]?key)\b'
    r'\s*[:=]\s*["\'](?!<)[^"\']{12,}["\']'
)
known_secret = re.compile(
    r'(?i)(gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|'
    r'sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})'
)

findings = []
for filename in files:
    if filename == "scripts/check-staged-files.sh":
        continue
    path = Path(filename)
    if path.suffix.lower() not in {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"}:
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        continue
    for line_no, line in enumerate(text.splitlines(), 1):
        if literal_assignment.search(line) or known_secret.search(line):
            findings.append(f"{filename}:{line_no}")

if findings:
    print("错误：暂存文本可能包含真实凭据：", ", ".join(findings), file=sys.stderr)
    sys.exit(1)
PY
then
  exit 1
fi

echo "通过：暂存文件未触发基础安全规则。"
