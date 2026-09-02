#!/usr/bin/env bash
# 发布静态站到公开产物仓(双仓模式:源仓可私有,产物仓公开托管 GitHub Pages)
# 用法:
#   SITE_REPO=yourname/your-site-repo deploy/publish_site.sh [--passcode 你的口令] [--no-archive]
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="${SITE_REPO:?请设置 SITE_REPO 环境变量,例如 SITE_REPO=yourname/your-site-repo}"
GIT_NAME="${SITE_COMMIT_NAME:-$(git config user.name || echo publisher)}"
GIT_EMAIL="${SITE_COMMIT_EMAIL:-$(git config user.email || echo publisher@users.noreply.github.com)}"

.venv/bin/python scripts/export_static.py "$@"

cd dist
rm -rf .git
git init -q -b main
git add -A
git -c user.name="$GIT_NAME" -c user.email="$GIT_EMAIL" commit -qm "publish $(date +%F_%H%M)"
git push -q --force "https://github.com/${REPO}.git" main
echo "已发布 → https://github.com/${REPO}"
