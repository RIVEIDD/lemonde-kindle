#!/data/data/com.termux/files/usr/bin/bash
# Reçoit un partage Android : un lien (termux-url-opener) ou un fichier (termux-file-editor) :
# texte contenant un lien, ou EPUB/PDF à envoyer tel quel. Le script Python fait le tri.
set -a
. "$HOME/.config/lemonde-kindle.env"
set +a

cd "$(dirname "$(readlink -f "$0")")/.."
python lemonde_kindle.py "$1"
echo
read -r -n1 -p "Appuie sur une touche pour fermer… "
