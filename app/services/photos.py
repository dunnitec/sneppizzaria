"""Fotos dos sabores.

Os arquivos ficam em UPLOAD_FOLDER (em produção, no volume do Fly: /data/uploads),
fora do código, para sobreviverem a deploys. Toda foto é reduzida e convertida
para WebP; o nome leva um trecho aleatório, então pode ficar em cache para sempre.
"""

import re
import secrets
import unicodedata
from pathlib import Path

from flask import current_app, url_for
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SIDE = 800
MAX_PIXELS = 30_000_000  # PNG/WebP acima disso: recusado (JPEG é reduzido na leitura)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class PhotoError(ValueError):
    """Arquivo que não é uma imagem válida; a mensagem é mostrada no painel."""


def upload_folder():
    folder = Path(current_app.config["UPLOAD_FOLDER"])
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def photo_url(name):
    return url_for("public.uploaded_file", name=name) if name else None


def save_photo(stream, slug, max_side=MAX_SIDE):
    """Lê a imagem enviada, ajusta a orientação, reduz e grava como WebP. Devolve o nome do arquivo."""
    try:
        with Image.open(stream) as im:
            # foto de celular de 50-108 MP aberta inteira estoura a memória do servidor (512 MB):
            # JPEG é lido já reduzido (draft); outros formatos muito grandes são recusados
            if im.format == "JPEG":
                im.draft("RGB", (max_side * 2, max_side * 2))
            elif im.width * im.height > MAX_PIXELS:
                raise PhotoError("Foto grande demais. Mande em JPG, ou tire um print da foto e envie o print.")
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((max_side, max_side))
            name = f"{slug}-{secrets.token_hex(6)}.webp"
            im.save(upload_folder() / name, "WEBP", quality=82, method=6)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise PhotoError("O arquivo enviado não é uma imagem válida (use JPG, PNG ou WebP).") from None
    return name


def delete_photo(name):
    if name:
        (upload_folder() / name).unlink(missing_ok=True)


def normalize(text):
    """'Milho c/ Catupiry' e 'milho com catupiry' -> 'milho com catupiry' (sem acento, minúsculo)."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"\bc/", "com ", text)
    words = re.sub(r"[^a-z0-9]+", " ", text).split()
    return " ".join("com" if w == "c" else w for w in words)


def match_product(filename, products):
    """Acha o sabor pelo nome do arquivo: 'Paulista.jpg' ou 'Premium - Paulista.jpg'.

    Devolve o produto, ou None se não achar ou se o nome existir em mais de uma linha
    sem a categoria no nome do arquivo.
    """
    stem = Path(filename).stem
    category, _, name = stem.rpartition(" - ")
    wanted = normalize(name)
    found = [p for p in products if normalize(p.name) == wanted]
    if category:
        found = [p for p in found if normalize(category) in normalize(p.category.name)]
    return found[0] if len(found) == 1 else None
