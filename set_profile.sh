#!/bin/bash
# set_profile.sh — Ganti profil trading bot: aggressive | selective
# Usage: bash set_profile.sh [aggressive|selective]
#
#   aggressive  — entry SERING. threshold 0.50, skor confluence 2.0 (default v14 PRO+)
#   selective   — entry SEDIKIT tapi berkualitas. threshold 0.58, skor 3.0
#
# Setelah ganti profil, WAJIB restart bot biar .env baru kebaca.

cd "$(dirname "$0")"
ENV=".env"
[ -f "$ENV" ] || { echo "❌ .env tidak ada. Jalankan dulu: cp .env.example .env"; exit 1; }

setenv() {  # setenv KEY VALUE
  local k="$1" v="$2"
  if grep -qE "^${k}=" "$ENV"; then
    sed -i "s|^${k}=.*|${k}=${v}|" "$ENV"
  else
    echo "${k}=${v}" >> "$ENV"
  fi
  printf '  %-32s = %s\n' "$k" "$v"
}

case "${1:-}" in
  selective)
    echo "🎯 Menerapkan profil SELEKTIF (entry lebih sedikit, kualitas tinggi):"
    setenv ML_PROBA_THRESHOLD         0.58
    setenv MIN_PROBA                  0.58
    setenv CONFLUENCE_MIN_SCORE       3.0
    setenv ML_VOL_MULT_MIN            1.8
    setenv ML_EMA_DIST_MIN            0.0015
    setenv MAX_DAILY_TRADES           20
    setenv COOLDOWN_AFTER_TRADE_SECONDS  90
    setenv COOLDOWN_AFTER_LOSS_SECONDS   300
    ;;
  aggressive)
    echo "⚡ Menerapkan profil AGRESIF (entry lebih sering, default v14 PRO+):"
    setenv ML_PROBA_THRESHOLD         0.50
    setenv MIN_PROBA                  0.50
    setenv CONFLUENCE_MIN_SCORE       2.0
    setenv ML_VOL_MULT_MIN            1.5
    setenv ML_EMA_DIST_MIN            0.001
    setenv MAX_DAILY_TRADES           30
    setenv COOLDOWN_AFTER_TRADE_SECONDS  60
    setenv COOLDOWN_AFTER_LOSS_SECONDS   180
    ;;
  *)
    echo "Usage: bash set_profile.sh [aggressive|selective]"
    echo ""
    echo "  aggressive — entry sering   | threshold 0.50 | skor 2.0 (default v14 PRO+)"
    echo "  selective  — entry selektif | threshold 0.58 | skor 3.0"
    echo ""
    cur=$(grep -E '^ML_PROBA_THRESHOLD=' "$ENV" | head -1 | cut -d= -f2)
    sc=$(grep -E '^CONFLUENCE_MIN_SCORE=' "$ENV" | head -1 | cut -d= -f2)
    echo "📍 Profil aktif sekarang: threshold=${cur:-?} | skor=${sc:-?}"
    exit 0
    ;;
esac

echo ""
echo "✅ Profil '${1}' diterapkan ke .env"
echo "🔄 Restart bot sekarang:"
echo "   pkill -f 'bot.main'; nohup python3 -m bot.main >> logs/bot.log 2>&1 &"
