#!/data/data/com.termux/files/usr/bin/bash
# Reçoit un partage Android : un lien (termux-url-opener) ou un fichier texte (termux-file-editor).
set -a
. "$HOME/.config/lemonde-kindle.env"
set +a

if [ -f "$1" ]; then
  TEXTE="$(cat "$1")"
else
  TEXTE="$1"
fi

cd "$(dirname "$(readlink -f "$0")")/.."
python lemonde_kindle.py "$TEXTE"
echo
read -r -n1 -p "Appuie sur une touche pour fermer… "
