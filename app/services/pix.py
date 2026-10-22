"""Pix “copia e cola” e QR Code com o valor do pedido (BR Code estático do Banco Central).

Não passa por banco nem por empresa de pagamento: o código leva a chave Pix da
loja, o valor e o número do pedido. A confirmação é manual — o dono confere no
app do banco e marca “Pix recebido” no painel.
"""

import base64
import io
import re
import unicodedata

import qrcode
import qrcode.image.svg

KEY_TYPES = {"email": "E-mail", "celular": "Celular", "cpf": "CPF ou CNPJ", "aleatoria": "Chave aleatória"}


class PixKeyError(ValueError):
    pass


def normalize_key(kind, text):
    """Deixa a chave no formato que o Pix exige; levanta PixKeyError com mensagem para o painel."""
    text = (text or "").strip()
    if kind == "email":
        key = text.lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", key) or len(key) > 77:
            raise PixKeyError("Chave Pix: e-mail inválido.")
        return key
    digits = re.sub(r"\D", "", text)
    if kind == "celular":
        if digits.startswith("55") and len(digits) in (12, 13):
            digits = digits[2:]
        if len(digits) not in (10, 11):
            raise PixKeyError("Chave Pix: celular com DDD, ex.: (11) 99999-0000.")
        return "+55" + digits
    if kind == "cpf":
        if len(digits) not in (11, 14):
            raise PixKeyError("Chave Pix: CPF tem 11 números e CNPJ tem 14.")
        return digits
    if kind == "aleatoria":
        key = text.lower()
        if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", key):
            raise PixKeyError("Chave Pix aleatória inválida (ex.: 123e4567-e89b-12d3-a456-426614174000).")
        return key
    raise PixKeyError("Escolha o tipo da chave Pix.")


def _ascii(text, size):
    """O BR Code só aceita letras sem acento; nome até 25 e cidade até 15 caracteres."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9 ]", "", text).strip().upper()[:size] or "LOJA"


def _field(tag, value):
    return f"{tag}{len(value):02d}{value}"


def crc16(data):
    """CRC16-CCITT (polinômio 0x1021, início 0xFFFF), exigido no fim do BR Code."""
    crc = 0xFFFF
    for byte in data.encode():
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return f"{crc:04X}"


def payload(key, name, city, amount, txid):
    """Texto do “Pix copia e cola” (o mesmo que vai dentro do QR Code)."""
    account = _field("00", "br.gov.bcb.pix") + _field("01", key)
    ref = re.sub(r"[^A-Za-z0-9]", "", str(txid))[:25] or "***"
    body = (
        _field("00", "01")
        + _field("26", account)
        + _field("52", "0000")
        + _field("53", "986")
        + _field("54", f"{float(amount):.2f}")
        + _field("58", "BR")
        + _field("59", _ascii(name, 25))
        + _field("60", _ascii(city, 15))
        + _field("62", _field("05", ref))
        + "6304"
    )
    return body + crc16(body)


def qr_svg_data_uri(text):
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathFillImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


def for_order(tenant, order):
    """Dados do Pix para a tela de pedido feito; None se a loja não configurou a chave."""
    if not tenant.pix_key:
        return None
    code = payload(tenant.pix_key, tenant.pix_name or tenant.name, tenant.pix_city or "", order.total, f"PEDIDO{order.id}")
    return {"code": code, "qr": qr_svg_data_uri(code), "amount": float(order.total)}
