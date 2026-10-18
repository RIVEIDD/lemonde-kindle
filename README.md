# Le Monde → Kindle

Partager un article depuis l'appli Android Le Monde, et le retrouver quelques instants plus tard sur la Kindle, en EPUB lisible, texte complet (abonné).

Fonctionnement : le menu Partager d'Android déclenche un raccourci (appli **HTTP Shortcuts**), qui lance une tâche **GitHub Actions** sur ce dépôt. La tâche télécharge l'article avec ton cookie d'abonné, le met en page en EPUB et l'envoie par mail à ton adresse `@kindle.com`. Amazon le livre sur la liseuse au prochain passage en Wi‑Fi. Tout est gratuit.

Les autres sites marchent aussi (extraction générique), mais sans contournement de paywall.

## Mise en place (une seule fois)

### 1. Amazon : adresse Kindle et expéditeur autorisé
Sur amazon.fr : **Compte → Gérer votre contenu et vos appareils → Préférences → Paramètres des documents personnels**.
- Note l'adresse e‑mail de ta Kindle (`xxxx@kindle.com`).
- Dans « Liste des adresses e‑mail approuvées », ajoute l'adresse Gmail qui enverra les articles.

### 2. Gmail : mot de passe d'application
Sur https://myaccount.google.com/apppasswords (la validation en deux étapes doit être active), crée un mot de passe d'application « Kindle ». Garde les 16 caractères.

### 3. Le Monde : cookie d'abonné
Sur un ordinateur, connecte‑toi sur lemonde.fr, ouvre un article, puis **F12 → onglet Réseau → recharge la page → clique sur la première requête → En‑têtes de requête → `Cookie`**. Copie toute la valeur.
Ce cookie expire de temps en temps : quand un envoi échoue avec « cookie absent ou expiré », recommence cette étape.

### 4. GitHub : les secrets du dépôt
Dans le dépôt : **Settings → Secrets and variables → Actions → New repository secret**, crée :

| Secret | Valeur |
|---|---|
| `LEMONDE_COOKIE` | la valeur copiée à l'étape 3 |
| `SMTP_USER` | ton adresse Gmail |
| `SMTP_PASSWORD` | le mot de passe d'application de l'étape 2 |
| `KINDLE_EMAIL` | l'adresse `@kindle.com` de l'étape 1 |

Test : onglet **Actions → Envoyer sur Kindle → Run workflow**, colle l'URL d'un article.

### 5. GitHub : un jeton pour le téléphone
**Settings (de ton compte) → Developer settings → Personal access tokens → Fine‑grained tokens → Generate new token** :
- Repository access : *Only select repositories* → ce dépôt uniquement.
- Permissions : **Actions → Read and write**.
- Expiration : la plus longue proposée (à renouveler ensuite).

### 6. Android : le raccourci de partage
Installe **HTTP Shortcuts** (Play Store ou F‑Droid, gratuit et open source).

1. **Variables** → nouvelle variable de type *Texte*, nommée `partage`, et coche l'option qui permet de **recevoir la valeur depuis le menu Partager**.
2. Nouveau raccourci → *Requête HTTP* :
   - Nom : `Kindle`
   - Méthode : `POST`
   - URL : `https://api.github.com/repos/RIVEIDD/lemonde-kindle/actions/workflows/kindle.yml/dispatches`
   - En‑têtes : `Authorization: Bearer <jeton de l'étape 5>` et `Accept: application/vnd.github+json`
   - Corps (JSON) : `{"ref": "main", "inputs": {"texte": "{url}"}}` où `{url}` est une variable texte `url` (crée‑la, vide).
   - **Scripting → Avant l'exécution** :
     ```js
     const m = getVariable('partage').match(/https?:\/\/\S+/);
     if (!m) { showToast('Pas de lien Le Monde'); abort(); }
     setVariable('url', m[0]);
     ```
   - Réponse : afficher un simple toast (« Envoyé sur la Kindle »).

## Utilisation
- **Envoyer** : dans l'appli Le Monde, **Partager → HTTP Shortcuts → Kindle**. L'article arrive dans la bibliothèque (filtre *Documents*) en général en moins de deux minutes, dès que la Kindle est en Wi‑Fi.
- **Supprimer après lecture** : sur la Kindle, appui long sur l'article → **Supprimer ce téléchargement** (et **Supprimer définitivement** si ta Kindle le propose, pour le retirer aussi du cloud ; sinon amazon.fr → Gérer votre contenu → Documents).
- **En cas d'échec** : GitHub t'envoie un e‑mail ; le détail est dans l'onglet Actions du dépôt.

## Tester en local
```bash
pip install -r requirements.txt
python lemonde_kindle.py "https://www.lemonde.fr/..." --epub test.epub   # crée l'EPUB sans l'envoyer
```
