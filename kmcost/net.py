"""Utilidades HTTP/TLS endurecidas para servidores públicos españoles (MITECO, REE, DGT)."""
import ssl
import time

import requests
from requests.adapters import HTTPAdapter

USER_AGENT = "KMCost/2.1 (+https://github.com/sjmillon/KMCost)"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Connection": "close",
}


class LegacyTLSAdapter(HTTPAdapter):
    """HTTPAdapter con contexto TLS tolerante para servidores heredados bajo OpenSSL 3.

    Activa OP_LEGACY_SERVER_CONNECT, opcionalmente baja SECLEVEL=1 y limita a TLS 1.2.
    """

    def __init__(self, sec_level_1=True, max_tls12=True, **kwargs):
        self.sec_level_1 = sec_level_1
        self.max_tls12 = max_tls12
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
        if self.sec_level_1:
            try:
                ctx.set_ciphers("DEFAULT@SECLEVEL=1")
            except ssl.SSLError:
                pass
        if self.max_tls12 and hasattr(ssl, "TLSVersion"):
            try:
                ctx.maximum_version = ssl.TLSVersion.TLSv1_2
            except (ssl.SSLError, ValueError):
                pass
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def crear_sesion(legacy=True, sec_level_1=True, max_tls12=True):
    s = requests.Session()
    s.headers.update(HEADERS)
    if legacy:
        s.mount("https://", LegacyTLSAdapter(sec_level_1=sec_level_1, max_tls12=max_tls12))
    return s


def get_resiliente(url, timeout=(6, 18), intentos_por_perfil=1, http_fallback=False, **kwargs):
    """Ejecuta GET probando varios perfiles TLS (estándar y legado) y opcionalmente HTTP.

    Lanza la última excepción si todos fallan.
    """
    perfiles = [
        ("legacy_t12_sec1", crear_sesion(legacy=True, sec_level_1=True, max_tls12=True), url),
        ("legacy_default", crear_sesion(legacy=True, sec_level_1=False, max_tls12=False), url),
        ("std", crear_sesion(legacy=False), url),
    ]
    if http_fallback and url.startswith("https://"):
        perfiles.append(("http", crear_sesion(legacy=False), "http://" + url[len("https://"):]))

    ultimo = None
    headers = dict(HEADERS)
    if "headers" in kwargs:
        headers.update(kwargs.pop("headers"))

    for _, sesion, target in perfiles:
        for i in range(intentos_por_perfil):
            try:
                r = sesion.get(target, headers=headers, timeout=timeout, **kwargs)
                r.raise_for_status()
                return r
            except Exception as exc:  # noqa: BLE001
                ultimo = exc
                if i + 1 < intentos_por_perfil:
                    time.sleep(0.8 * (i + 1))
        sesion.close()
    raise ultimo
