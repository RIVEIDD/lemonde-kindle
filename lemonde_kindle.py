"""Envoie un article du Monde (ou d'un autre site) sur une Kindle, en EPUB.

Usage :
    python lemonde_kindle.py "<texte partagé contenant l'URL>"
    python lemonde_kindle.py URL --epub article.epub   # crée l'EPUB sans l'envoyer
    python lemonde_kindle.py URL --html page.html      # utilise une page déjà téléchargée

Variables d'environnement :
    LEMONDE_COOKIE  en-tête Cookie d'une session abonné sur lemonde.fr
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
from urllib.parse import urlparse

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


def session_for(url: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"})
    cookie = os.environ.get("LEMONDE_COOKIE", "").strip()
    # Tolère un copier-coller qui inclut le nom de l'en-tête ou des retours à la ligne.
    cookie = re.sub(r"^cookie\s*:\s*", "", cookie, flags=re.IGNORECASE).replace("\n", "").replace("\r", "")
    if cookie and urlparse(url).hostname.endswith("lemonde.fr"):
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
        print(f"HTTP {resp.status_code} — cookie Le Monde {'présent' if has_cookie else 'absent'}", flush=True)
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
    if host.endswith("lemonde.fr"):
        article = parse_lemonde(BeautifulSoup(page, "lxml"), url)
    else:
        article = parse_generic(page, url)
    return article, session


def build_epub(article: Article, session: requests.Session, path: str) -> str:
    book = epub.EpubBook()
    book.set_identifier(str(uuid.uuid4()))
    book.set_title(article.title)
    book.set_language("fr")
    book.add_author(article.author.removeprefix("Par ").strip() or "Le Monde")

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


def send_to_kindle(path: str, title: str) -> None:
    user = os.environ["SMTP_USER"].strip()
    # Le mot de passe d'application Google s'affiche par groupes de 4 : les espaces ne comptent pas.
    password = re.sub(r"\s+", "", os.environ["SMTP_PASSWORD"])
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = os.environ["KINDLE_EMAIL"].strip()
    msg["Subject"] = title
    msg.set_content("Article envoyé par lemonde_kindle.")
    with open(path, "rb") as fh:
        msg.add_attachment(fh.read(), maintype="application", subtype="epub+zip", filename=safe_filename(title))
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
    parser.add_argument("texte", help="URL de l'article, ou texte partagé qui la contient")
    parser.add_argument("--epub", help="écrit l'EPUB à ce chemin sans l'envoyer")
    parser.add_argument("--html", help="lit la page depuis ce fichier au lieu de la télécharger")
    args = parser.parse_args()

    try:
        url = find_url(args.texte)
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


if __name__ == "__main__":
    sys.exit(main())
