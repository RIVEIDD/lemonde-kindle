#!/data/data/com.termux/files/usr/bin/bash
# Installe lemonde-kindle dans Termux et branche le menu Partager d'Android.
set -euo pipefail

CONF="$HOME/.config/lemonde-kindle.env"

pkg update -y
pkg install -y python libxml2 libxslt
pkg install -y python-lxml || pip install lxml
pip install requests beautifulsoup4 EbookLib

# Le menu Partager de Termux appelle termux-url-opener pour un lien seul,
# termux-file-editor pour un texte (titre + lien) : les deux pointent sur partager.sh.
SRC="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$HOME/bin" "$(dirname "$CONF")"
chmod +x "$SRC/termux/partager.sh"
ln -sf "$SRC/termux/partager.sh" "$HOME/bin/termux-url-opener"
ln -sf "$SRC/termux/partager.sh" "$HOME/bin/termux-file-editor"

if [ ! -f "$CONF" ]; then
  echo
  echo "Configuration (laisse vide pour remplir plus tard dans $CONF)"
  read -r -p "Adresse @kindle.com : " KINDLE_EMAIL
  read -r -p "Adresse Gmail d'envoi : " SMTP_USER
  read -r -p "Mot de passe d'application Gmail : " SMTP_PASSWORD
  read -r -p "Cookie Le Monde (colle toute la valeur) : " LEMONDE_COOKIE
  read -r -p "Cookie Monde diplomatique (facultatif) : " DIPLO_COOKIE
  {
    printf 'KINDLE_EMAIL=%q\n' "$KINDLE_EMAIL"
    printf 'SMTP_USER=%q\n' "$SMTP_USER"
    printf 'SMTP_PASSWORD=%q\n' "$SMTP_PASSWORD"
    printf 'LEMONDE_COOKIE=%q\n' "$LEMONDE_COOKIE"
    printf 'DIPLO_COOKIE=%q\n' "$DIPLO_COOKIE"
  } > "$CONF"
  chmod 600 "$CONF"
elif ! grep -q '^DIPLO_COOKIE=' "$CONF"; then
  # Configuration d'avant le Monde diplomatique : on ajoute seulement son cookie.
  echo
  read -r -p "Cookie Monde diplomatique (facultatif, Entrée pour passer) : " DIPLO_COOKIE
  printf 'DIPLO_COOKIE=%q\n' "$DIPLO_COOKIE" >> "$CONF"
fi

echo
echo "Installé. Dans l'appli Le Monde ou le navigateur : Partager → Termux."
