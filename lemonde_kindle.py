"""Envoie un article du Monde ou du Monde diplomatique (ou d'un autre site) sur une Kindle, en EPUB.

Usage :
    python lemonde_kindle.py "<texte partagé contenant l'URL>"
    python lemonde_kindle.py numero.epub                # envoie un EPUB ou un PDF tel quel
    python lemonde_kindle.py https://www.monde-diplomatique.fr/2026/10/   # numéro complet du Diplo
    python lemonde_kindle.py URL --epub article.epub   # crée l'EPUB sans l'envoyer
    python lemonde_kindle.py URL --html page.html      # utilise une page déjà téléchargée

Variables d'environnement :
    LEMONDE_COOKIE  en-tête Cookie d'une session abonné sur lemonde.fr
    DIPLO_COOKIE    en-tête Cookie d'une session abonné sur monde-diplomatique.fr
    SMTP_USER       adresse qui envoie (doit être autorisée sur Amazon)
    SMTP_PASSWORD   mot de passe d'application de cette adresse
    KINDLE_EMAIL    adresse @kindle.com de la liseuse
    SMTP_HOST       facultatif, smtp.gmail.com par défaut
    SMTP_PORT       facultatif, 465 par défaut (SSL)
"""

from __future__ import annotations

import argparse
import html
import os
import re
import smtplib
import sys
import uuid
from dataclasses import dataclass, field
from email.message import EmailMessage
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from ebooklib import epub

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)
INLINE_TAGS = {"em", "i", "strong", "b", "sup", "sub", "br"}
CSS = """
body { font-family: serif; line-height: 1.45; }
h1 { font-size: 1.5em; margin-bottom: 0.3em; }
h2 { font-size: 1.15em; margin-top: 1.2em; }
.chapo { font-style: italic; margin-bottom: 1em; }
.meta { font-size: 0.85em; color: #555; margin-bottom: 1.2em; }
figure { margin: 1em 0; text-align: center; }
figure img { max-width: 100%; }
figcaption { font-size: 0.8em; color: #555; }
blockquote { margin: 1em 1.5em; font-style: italic; }
.source { font-size: 0.8em; margin-top: 2em; color: #555; }
"""


class ArticleError(Exception):
    """L'article n'a pas pu être récupéré correctement."""


@dataclass
class Article:
    url: str
    title: str
    description: str = ""
    author: str = ""
    date: str = ""
    blocks: list[str] = field(default_factory=list)  # fragments XHTML
    images: dict[str, str] = field(default_factory=dict)  # nom de fichier -> URL


def find_url(text: str) -> str:
    """Extrait la première URL du texte partagé par l'appli (titre + lien)."""
    match = re.search(r"https?://\S+", text)
    if not match:
        raise ArticleError(f"Aucune URL trouvée dans : {text!r}")
    return match.group(0).rstrip(").,;»\"'")


# Domaine -> variable d'environnement qui porte le cookie abonné de ce site.
COOKIES = {"monde-diplomatique.fr": "DIPLO_COOKIE", "lemonde.fr": "LEMONDE_COOKIE"}
MAX_ATTACHMENT = 24 * 1024 * 1024  # Gmail refuse les pièces jointes de plus de 25 Mo


def is_diplo(url: str) -> bool:
    return (urlparse(url).hostname or "").endswith("monde-diplomatique.fr")


def cookie_var(url: str) -> str | None:
    host = urlparse(url).hostname or ""
    # « monde-diplomatique.fr » se termine aussi par « lemonde.fr » : on teste le Diplo d'abord.
    return next((var for domain, var in COOKIES.items() if host.endswith(domain)), None)


def session_for(url: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"})
    var = cookie_var(url)
    cookie = os.environ.get(var, "").strip() if var else ""
    # Tolère un copier-coller qui inclut le nom de l'en-tête ou des retours à la ligne.
    cookie = re.sub(r"^cookie\s*:\s*", "", cookie, flags=re.IGNORECASE).replace("\n", "").replace("\r", "")
    if cookie:
        session.headers["Cookie"] = cookie
    return session


def inline_html(node: Tag) -> str:
    """Rend le contenu d'un paragraphe en ne gardant que la mise en forme simple."""
    return re.sub(r"\s+", " ", _inline(node)).strip()


def _inline(node: Tag) -> str:
    parts = []
    for child in node.children:
        if isinstance(child, NavigableString):
            parts.append(html.escape(str(child), quote=False))
        elif isinstance(child, Tag):
            if child.name == "br":
                parts.append("<br/>")
            elif child.name in INLINE_TAGS:
                parts.append(f"<{child.name}>{_inline(child)}</{child.name}>")
            else:
                parts.append(_inline(child))
    return "".join(parts)


def meta(soup: BeautifulSoup, key: str) -> str:
    tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
    return (tag.get("content") or "").strip() if tag else ""


def figure_block(fig: Tag, article: Article) -> str | None:
    img = fig.find("img")
    src = img and (img.get("src") or img.get("data-src"))
    if not src or not src.startswith("http"):
        return None
    name = f"img{len(article.images) + 1}.jpg"
    article.images[name] = src
    caption = fig.find("figcaption")
    cap = f"<figcaption>{inline_html(caption)}</figcaption>" if caption else ""
    return f'<figure><img src="{name}" alt=""/>{cap}</figure>'


def parse_lemonde(soup: BeautifulSoup, url: str) -> Article:
    # Article classique : <article class="article__content"> ; format long (« longform ») :
    # <section class="article__content">. On prend le conteneur qui porte les paragraphes.
    first = soup.select_one(".article__content p.article__paragraph") or soup.select_one("p.article__paragraph")
    body = first.find_parent(class_="article__content") or first.parent if first else None
    if body is None:
        raise ArticleError("Structure d'article Le Monde introuvable.")
    article = Article(
        url=url,
        title=meta(soup, "og:title") or soup.title.get_text(strip=True),
        description=meta(soup, "og:description"),
    )
    author = soup.select_one(".meta__author")
    date = soup.select_one(".meta__date")
    article.author = author.get_text(" ", strip=True) if author else meta(soup, "og:article:author")
    article.date = date.get_text(" ", strip=True) if date else meta(soup, "og:article:published_time")[:10]

    cover = soup.select_one("figure.article__cover-figure")
    if cover is not None and not body.find(lambda tag: tag is cover):
        block = figure_block(cover, article)
        if block:
            article.blocks.append(block)

    block_tags = ["p", "h2", "h3", "blockquote", "figure", "ul", "ol"]
    for node in body.find_all(block_tags):
        # Un bloc imbriqué dans un autre (légende, citation…) est rendu par son parent.
        if node.find_parent(block_tags) or node.find_parent(class_=["catcher", "dfp-slot"]) or node.find_parent("aside"):
            continue
        classes = node.get("class") or []
        if node.name == "p" and "article__paragraph" not in classes:
            continue
        if node.name == "figure":
            block = figure_block(node, article)
        elif node.name in ("h2", "h3"):
            block = f"<h2>{inline_html(node)}</h2>"
        elif node.name == "blockquote":
            block = f"<blockquote><p>{inline_html(node)}</p></blockquote>"
        elif node.name in ("ul", "ol"):
            items = "".join(f"<li>{inline_html(li)}</li>" for li in node.find_all("li"))
            block = f"<{node.name}>{items}</{node.name}>" if items else None
        else:
            text = inline_html(node)
            block = f"<p>{text}</p>" if text else None
        if block:
            article.blocks.append(block)

    paragraphs = sum(b.startswith("<p>") for b in article.blocks)
    locked = meta(soup, "og:article:content_tier") == "locked"
    still_paywalled = soup.select_one(".paywall, .js-paywall, .lmd-paywall") is not None
    if locked and still_paywalled and paragraphs <= 4:
        raise ArticleError(
            "Article abonné tronqué : le cookie Le Monde est absent ou expiré. "
            "Recopie un cookie frais dans ~/.config/lemonde-kindle.env (LEMONDE_COOKIE)."
        )
    if paragraphs == 0:
        raise ArticleError("Aucun paragraphe trouvé dans l'article.")
    return article


def parse_diplo(soup: BeautifulSoup, url: str) -> Article:
    """Article du Monde diplomatique (site SPIP) : le texte est dans div.texte."""
    body = soup.select_one(".contenu-principal div.texte") or soup.select_one("div.texte")
    if body is None:
        raise ArticleError("Structure d'article du Monde diplomatique introuvable.")
    title = soup.select_one("h1.crayon")
    chapo = soup.select_one(".contenu-principal .chapo")
    article = Article(
        url=url,
        title=title.get_text(" ", strip=True) if title else meta(soup, "og:title"),
        description=chapo.get_text(" ", strip=True) if chapo else meta(soup, "description"),
        author=meta(soup, "article:author"),
        date=meta(soup, "article:published_time")[:10],
    )

    # Les images sont en chemin relatif à la balise <base> de la page.
    base = soup.find("base", href=True)
    base_url = urljoin(url, base["href"]) if base else url
    block_tags = ["p", "h2", "h3", "h4", "blockquote", "figure", "ul", "ol"]
    for node in body.find_all(block_tags):
        if node.find_parent(block_tags) or node.find_parent(class_=["nombremots", "promo_dispo_article"]):
            continue
        if node.name == "figure":
            img = node.find("img")
            src = img and (img.get("src") or img.get("data-src"))
            block = None
            if src:
                name = f"img{len(article.images) + 1}.jpg"
                article.images[name] = urljoin(base_url, src)
                caption = node.find("figcaption")
                text = caption.get_text(" ", strip=True) if caption else ""
                cap = f"<figcaption>{html.escape(text, quote=False)}</figcaption>" if text else ""
                block = f'<figure><img src="{name}" alt=""/>{cap}</figure>'
        elif node.name in ("h2", "h3", "h4"):
            block = f"<h2>{inline_html(node)}</h2>"
        elif node.name == "blockquote":
            block = f"<blockquote><p>{inline_html(node)}</p></blockquote>"
        elif node.name in ("ul", "ol"):
            items = "".join(f"<li>{inline_html(li)}</li>" for li in node.find_all("li"))
            block = f"<{node.name}>{items}</{node.name}>" if items else None
        else:
            text = inline_html(node)
            block = f"<p>{text}</p>" if text else None
        if block:
            article.blocks.append(block)

    # Les notes de bas de page sont à part, après le texte.
    notes = soup.select_one(".contenu-principal .notes")
    if notes is not None:
        article.blocks.append("<h2>Notes</h2>")
        article.blocks.extend(f"<p>{inline_html(p)}</p>" for p in notes.find_all("p") if inline_html(p))

    principal = soup.select_one(".contenu-principal")
    if principal is not None and "ferme" in (principal.get("class") or []):
        raise ArticleError(
            "Article abonné tronqué : le cookie du Monde diplomatique est absent ou expiré. "
            "Recopie un cookie frais dans ~/.config/lemonde-kindle.env (DIPLO_COOKIE)."
        )
    if not any(b.startswith("<p>") for b in article.blocks):
        raise ArticleError("Aucun paragraphe trouvé dans l'article.")
    return article


def parse_generic(page: str, url: str) -> Article:
    """Autres sites : extraction générique avec trafilatura (facultatif)."""
    try:
        import trafilatura
    except ImportError:
        raise ArticleError("Seul Le Monde est pris en charge sans le module trafilatura.") from None

    data = trafilatura.bare_extraction(page, url=url, include_images=False, with_metadata=True)
    if not data or not getattr(data, "text", None):
        raise ArticleError("Impossible d'extraire le texte de cette page.")
    article = Article(
        url=url,
        title=data.title or url,
        description=data.description or "",
        author=data.author or "",
        date=data.date or "",
    )
    article.blocks = [f"<p>{html.escape(p.strip(), quote=False)}</p>" for p in data.text.split("\n") if p.strip()]
    return article


def fetch_article(url: str, page: str | None = None) -> tuple[Article, requests.Session]:
    session = session_for(url)
    if page is None:
        resp = session.get(url, timeout=30)
        has_cookie = "Cookie" in session.headers
        print(f"HTTP {resp.status_code} — cookie abonné {'présent' if has_cookie else 'absent'}", flush=True)
        if resp.status_code >= 400:
            # Aide au diagnostic : quelle protection a répondu, et avec quelle page.
            print("En-têtes :", ", ".join(sorted(resp.headers.keys())), flush=True)
            title = BeautifulSoup(resp.text, "lxml").title
            print(f"Titre : {title.get_text(strip=True) if title else '—'} ({len(resp.text)} caractères)", flush=True)
            text = BeautifulSoup(resp.text, "lxml").body
            print("Texte :", text.get_text(" ", strip=True)[:800] if text else resp.text[:600], flush=True)
        # Le Monde répond 402 sur un article abonné vu sans session valide, mais renvoie
        # quand même la page tronquée : on laisse l'analyse expliquer le problème.
        if resp.status_code != 402:
            resp.raise_for_status()
        page = resp.text
    host = urlparse(url).hostname or ""
    if is_diplo(url):
        article = parse_diplo(BeautifulSoup(page, "lxml"), url)
    elif host.endswith("lemonde.fr"):
        article = parse_lemonde(BeautifulSoup(page, "lxml"), url)
    else:
        article = parse_generic(page, url)
    return article, session


def diplo_issue(url: str) -> tuple[str, str] | None:
    """Reconnaît la page d'un numéro du Diplo (…/2026/10/) et renvoie (année, mois)."""
    match = re.fullmatch(r"/(?:telechargements/)?(\d{4})/(\d{2})/?", urlparse(url).path)
    return match.groups() if is_diplo(url) and match else None


def download_diplo_issue(year: str, month: str, path: str) -> str:
    """Télécharge l'EPUB du numéro mensuel proposé aux abonnés sur la page de téléchargement."""
    page_url = f"https://www.monde-diplomatique.fr/telechargements/{year}/{month}"
    session = session_for(page_url)
    if "Cookie" not in session.headers:
        raise ArticleError("DIPLO_COOKIE manquant dans ~/.config/lemonde-kindle.env.")
    resp = session.get(page_url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    # Lien du bloc « Télécharger ce numéro » ; sans session valide il pointe vers /connexion.
    link = next(
        (a for a in soup.select("#telecharger a[href], .format.epub a[href]")
         if "epub" in (a.get("title", "") + a.get_text() + a["href"]).lower()),
        None,
    )
    if link is None or "/connexion" in link["href"]:
        raise ArticleError(
            "Le Monde diplomatique ne reconnaît pas l'abonnement : cookie absent ou expiré "
            "(DIPLO_COOKIE). Tu peux aussi télécharger l'EPUB dans le navigateur et le partager vers Termux."
        )
    resp = session.get(urljoin(page_url, link["href"]), timeout=120)
    resp.raise_for_status()
    if not resp.content.startswith(b"PK"):
        raise ArticleError(f"Le fichier reçu n'est pas un EPUB ({resp.headers.get('Content-Type', '?')}).")
    with open(path, "wb") as fh:
        fh.write(resp.content)
    return path


def build_epub(article: Article, session: requests.Session, path: str) -> str:
    book = epub.EpubBook()
    book.set_identifier(str(uuid.uuid4()))
    book.set_title(article.title)
    book.set_language("fr")
    book.add_author(article.author.removeprefix("Par ").strip() or ("Le Monde diplomatique" if is_diplo(article.url) else "Le Monde"))

    css = epub.EpubItem(uid="style", file_name="style.css", media_type="text/css", content=CSS)
    book.add_item(css)

    blocks = []
    for block in article.blocks:
        name = re.search(r'<img src="([^"]+)"', block)
        if name:
            try:
                resp = session.get(article.images[name.group(1)], timeout=30)
                resp.raise_for_status()
                media_type = resp.headers.get("Content-Type", "").split(";")[0].strip()
                if media_type not in ("image/jpeg", "image/png", "image/gif"):
                    continue  # format (webp, avif…) refusé par Amazon : on saute l'image
                book.add_item(epub.EpubItem(file_name=name.group(1), media_type=media_type, content=resp.content))
            except requests.RequestException:
                continue  # une image manquante ne doit pas bloquer l'envoi
        blocks.append(block)

    meta_line = " · ".join(html.escape(x) for x in (article.author, article.date) if x)
    chapo = f'<p class="chapo">{html.escape(article.description)}</p>' if article.description else ""
    content = (
        f"<h1>{html.escape(article.title)}</h1>{chapo}"
        f'<p class="meta">{meta_line}</p>' + "".join(blocks) +
        f'<p class="source">Source : {html.escape(article.url)}</p>'
    )
    chapter = epub.EpubHtml(title=article.title, file_name="article.xhtml", lang="fr")
    chapter.content = content
    chapter.add_item(css)
    book.add_item(chapter)
    book.toc = [chapter]
    book.spine = [chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(path, book)
    return path


def safe_filename(title: str) -> str:
    name = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE).strip()
    return (re.sub(r"\s+", " ", name)[:80] or "article") + ".epub"


def send_to_kindle(path: str, title: str, filename: str | None = None) -> None:
    if os.path.getsize(path) > MAX_ATTACHMENT:
        raise ArticleError(
            f"Fichier trop gros pour Gmail ({os.path.getsize(path) // 2**20} Mo, 25 Mo au plus). "
            "Partage-le plutôt vers l'appli Kindle (Partager → Kindle)."
        )
    user = os.environ["SMTP_USER"].strip()
    # Le mot de passe d'application Google s'affiche par groupes de 4 : les espaces ne comptent pas.
    password = re.sub(r"\s+", "", os.environ["SMTP_PASSWORD"])
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = os.environ["KINDLE_EMAIL"].strip()
    msg["Subject"] = title
    msg.set_content("Article envoyé par lemonde_kindle.")
    filename = filename or safe_filename(title)
    subtype = "pdf" if filename.lower().endswith(".pdf") else "epub+zip"
    with open(path, "rb") as fh:
        msg.add_attachment(fh.read(), maintype="application", subtype=subtype, filename=filename)
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    try:
        if port == 465:
            smtp = smtplib.SMTP_SSL(host, port, timeout=60)
        else:
            smtp = smtplib.SMTP(host, port, timeout=60)
            smtp.starttls()
        with smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise ArticleError(
            f"Gmail refuse l'identification ({exc.smtp_code}). Vérifie SMTP_USER (adresse complète) "
            "et SMTP_PASSWORD (mot de passe d'application à 16 lettres, pas ton mot de passe Gmail)."
        ) from None
    except (smtplib.SMTPException, OSError) as exc:
        raise ArticleError(
            f"Envoi du mail impossible ({type(exc).__name__}: {exc}). "
            "Si le mot de passe est bon, essaie SMTP_PORT=587 dans le fichier de configuration."
        ) from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("texte", help="URL de l'article, texte partagé qui la contient, ou fichier partagé")
    parser.add_argument("--epub", help="écrit l'EPUB à ce chemin sans l'envoyer")
    parser.add_argument("--html", help="lit la page depuis ce fichier au lieu de la télécharger")
    args = parser.parse_args()

    try:
        texte = args.texte
        if os.path.isfile(texte):
            with open(texte, "rb") as fh:
                head = fh.read(4)
            if head.startswith(b"PK") or head == b"%PDF":
                # Un EPUB ou un PDF partagé (numéro du Diplo téléchargé…) part tel quel.
                send_document(texte)
                return 0
            texte = open(texte, encoding="utf-8", errors="replace").read()
        url = find_url(texte)
        issue = diplo_issue(url)
        if issue:
            path = download_diplo_issue(*issue, args.epub or f"Le-Monde-diplomatique-{issue[0]}-{issue[1]}.epub")
            print(f"Numéro téléchargé : {path}")
            if not args.epub:
                send_document(path, f"Le Monde diplomatique — {issue[1]}/{issue[0]}")
            return 0
        page = open(args.html, encoding="utf-8").read() if args.html else None
        article, session = fetch_article(url, page)
        path = args.epub or "article.epub"
        build_epub(article, session, path)
        print(f"EPUB créé : {path} ({len(article.blocks)} blocs) — {article.title}")
        if not args.epub:
            send_to_kindle(path, article.title)
            print(f"Envoyé à {os.environ['KINDLE_EMAIL']}")
    except (ArticleError, requests.RequestException) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    return 0


def send_document(path: str, title: str | None = None) -> None:
    """Envoie un EPUB ou un PDF déjà prêt, sous son nom de fichier."""
    name = os.path.basename(path)
    if not name.lower().endswith((".epub", ".pdf")):
        with open(path, "rb") as fh:
            name += ".pdf" if fh.read(4) == b"%PDF" else ".epub"
    title = title or os.path.splitext(name)[0].replace("-", " ").replace("_", " ")
    send_to_kindle(path, title, name)
    print(f"{name} envoyé à {os.environ['KINDLE_EMAIL']}")


if __name__ == "__main__":
    sys.exit(main())
