#!/usr/bin/env bash
set -euo pipefail

# WARNING:
# - Jalankan hanya setelah backup repo.
# - Semua kolaborator harus re-clone setelah force push.
# - Script ini TIDAK dijalankan otomatis oleh aplikasi.

if ! command -v git-filter-repo >/dev/null 2>&1; then
  echo "git-filter-repo belum terpasang. Install dulu: https://github.com/newren/git-filter-repo"
  exit 1
fi

echo "Membersihkan histori file sensitif..."

git filter-repo --force \
  --path auth_session \
  --path wa-engine/auth_session \
  --path .env \
  --path token.json \
  --path credentials.json \
  --path client_secret.json \
  --path jadwal_meeting.json \
  --invert-paths

echo "Selesai. Lanjutkan dengan verifikasi lalu force-push terkoordinasi."
