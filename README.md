# Le Monde → Kindle

Partager un article depuis l'appli Android Le Monde, et le retrouver quelques instants plus tard sur la Kindle, en EPUB lisible, texte complet (abonné).

Le script tourne **sur le téléphone, dans Termux** : Le Monde bloque les serveurs (GitHub Actions, hébergeurs cloud) comme « trafic automatisé », alors qu'une connexion de téléphone passe comme celle d'un lecteur normal.

Fonctionnement : Partager → Termux → le script télécharge l'article avec ton cookie d'abonné, le met en page en EPUB et l'envoie par mail à ton adresse `@kindle.com`. Amazon le livre sur la liseuse au prochain passage en Wi‑Fi.

## Ce qu'il faut préparer

1. **Adresse Kindle et expéditeur autorisé** — sur amazon.fr : **Compte → Gérer votre contenu et vos appareils → Préférences → Paramètres des documents personnels**. Note l'adresse `xxxx@kindle.com`, et ajoute ton adresse Gmail dans « Liste des adresses e‑mail approuvées ».
2. **Mot de passe d'application Gmail** — sur https://myaccount.google.com/apppasswords (validation en deux étapes active), crée un mot de passe « Kindle ». Garde les 16 caractères.
3. **Cookie Le Monde** — sur un ordinateur connecté à lemonde.fr : ouvre un article, **F12 → Réseau → F5 → première requête → En‑têtes de requête → `Cookie`**, copie toute la valeur. Envoie‑la‑toi (mail à toi‑même, note) pour pouvoir la coller sur le téléphone.

## Installation sur le téléphone

1. Installe **Termux** depuis **F‑Droid** (https://f-droid.org/packages/com.termux/). La version du Play Store est ancienne et ne convient pas.
2. Ouvre Termux et récupère le code :
   ```bash
   pkg install -y git
   git clone https://github.com/RIVEIDD/lemonde-kindle
   ```
   Le dépôt étant privé, `git` demande un identifiant : ton login GitHub, et comme mot de passe un jeton (GitHub → Settings → Developer settings → Personal access tokens → Fine‑grained, accès en lecture « Contents » à ce dépôt). Autre solution : passer le dépôt en public, il ne contient aucun secret.
3. Lance l'installation et réponds aux 4 questions (adresse Kindle, Gmail, mot de passe d'application, cookie) :
   ```bash
   bash lemonde-kindle/termux/install.sh
   ```
   Les réponses sont enregistrées dans `~/.config/lemonde-kindle.env` (lisible par toi seul). Tu peux les modifier plus tard avec `nano ~/.config/lemonde-kindle.env`.

## Utilisation
- **Envoyer** : dans l'appli Le Monde, **Partager → Termux**. Une fenêtre s'ouvre, affiche « EPUB créé… » puis « Envoyé à …@kindle.com ». L'article arrive dans la bibliothèque de la Kindle (filtre *Documents*) dès qu'elle est en Wi‑Fi.
- **Supprimer après lecture** : sur la Kindle, appui long sur l'article → **Supprimer ce téléchargement** (et **Supprimer définitivement** si ta Kindle le propose, pour le retirer aussi du cloud ; sinon amazon.fr → Gérer votre contenu → Documents).
- **« Article abonné tronqué… cookie absent ou expiré »** : refais l'étape 3 et remplace `LEMONDE_COOKIE` dans `~/.config/lemonde-kindle.env` (garde les guillemets ou l'échappement autour de la valeur).
- **Mettre à jour le script** : dans Termux, `cd ~/lemonde-kindle && git pull`.

## Tester sur un ordinateur
```bash
pip install -r requirements.txt
python lemonde_kindle.py "https://www.lemonde.fr/..." --epub test.epub   # crée l'EPUB sans l'envoyer
```

## GitHub Actions (abandonné)
Le workflow `.github/workflows/kindle.yml` fonctionne techniquement, mais Le Monde renvoie une page « Accès restreint » (HTTP 402, « traffic identified as automated ») aux adresses IP de GitHub. Il reste utilisable pour d'autres sites.
