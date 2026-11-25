"""Fuentes de datos externas con endurecimiento TLS, múltiples espejos e instantáneas en GitHub."""
from datetime import datetime, timedelta
import gzip
import io
import json
import os
import re
import unicodedata
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import streamlit as st

from .geo import codificar_polilinea, simplificar
from .net import HEADERS, USER_AGENT, get_resiliente

TZ = ZoneInfo("Europe/Madrid")

MITECO_URL = (
    "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/"
    "PreciosCarburantes/EstacionesTerrestres/"
)
MITECO_PROV_URL = MITECO_URL + "FiltroProvincia/"
OSRM_URLS = [
    "https://router.project-osrm.org/route/v1/driving/",
    "https://routing.openstreetmap.de/routed-car/route/v1/driving/",
]
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
PHOTON_URL = "https://photon.komoot.io/api/"
REE_PVPC_URL = "https://apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real"
ESIOS_PVPC_URL = "https://api.esios.ree.es/indicators/1001"
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
OCM_URL = "https://api.openchargemap.io/v3/poi/"
DGT_NAP_URL = (
    "https://nap.dgt.es/datex2/v3/miterd/EnergyInfrastructureTablePublication/electrolineras.xml"
)
SNAPSHOT_BASE = "https://raw.githubusercontent.com/sjmillon/KMCost/data"

COMBUSTIBLES = {
    "Gasolina 95": "Precio Gasolina 95 E5",
    "Gasolina 98": "Precio Gasolina 98 E5",
    "Diésel": "Precio Gasoleo A",
    "Diésel Premium": "Precio Gasoleo Premium",
    "GLP (autogás)": "Precio Gases licuados del petróleo",
}

PROVINCIAS = {
    "Álava": "01", "Albacete": "02", "Alicante": "03", "Almería": "04", "Ávila": "05",
    "Badajoz": "06", "Balears (Illes)": "07", "Barcelona": "08", "Burgos": "09", "Cáceres": "10",
    "Cádiz": "11", "Castellón": "12", "Ciudad Real": "13", "Córdoba": "14", "A Coruña": "15",
    "Cuenca": "16", "Girona": "17", "Granada": "18", "Guadalajara": "19", "Gipuzkoa": "20",
    "Huelva": "21", "Huesca": "22", "Jaén": "23", "León": "24", "Lleida": "25",
    "La Rioja": "26", "Lugo": "27", "Madrid": "28", "Málaga": "29", "Murcia": "30",
    "Navarra": "31", "Ourense": "32", "Asturias": "33", "Palencia": "34", "Las Palmas": "35",
    "Pontevedra": "36", "Salamanca": "37", "Santa Cruz de Tenerife": "38", "Cantabria": "39",
    "Segovia": "40", "Sevilla": "41", "Soria": "42", "Tarragona": "43", "Teruel": "44",
    "Toledo": "45", "Valencia": "46", "Valladolid": "47", "Bizkaia": "48", "Zamora": "49",
    "Zaragoza": "50", "Ceuta": "51", "Melilla": "52",
}

_MARCAS = [
    ("CEPSA/MOEVE", ("CEPSA", "MOEVE")),
    ("REPSOL", ("REPSOL",)),
    ("GALP", ("GALP",)),
    ("BP", ("BP ",)),
    ("SHELL", ("SHELL",)),
    ("PLENERGY", ("PLENERGY", "PLENOIL")),
    ("BALLENOIL", ("BALLENOIL",)),
    ("PETROPRIX", ("PETROPRIX",)),
    ("PETRONOR", ("PETRONOR",)),
    ("CARREFOUR", ("CARREFOUR",)),
    ("ALCAMPO", ("ALCAMPO",)),
    ("EROSKI", ("EROSKI",)),
    ("AVIA", ("AVIA",)),
    ("Q8", ("Q8",)),
    ("DISA", ("DISA",)),
    ("AGLA", ("AGLA",)),
    ("TAMOIL", ("TAMOIL",)),
    ("ESCLATOIL", ("ESCLATOIL",)),
    ("VALCARCE", ("VALCARCE",)),
    ("GASEXPRESS", ("GASEXPRESS", "GAS EXPRESS")),
    ("EASYGAS", ("EASYGAS",)),
    ("BONAREA", ("BONAREA", "BON AREA")),
    ("PETROCAT", ("PETROCAT",)),
    ("MEROIL", ("MEROIL",)),
    ("CAMPSA", ("CAMPSA",)),
]


def _sin_acentos(texto):
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def normalizar_marca(rotulo):
    r = " " + _sin_acentos(str(rotulo or "")).upper().strip() + " "
    r = re.sub(r"\s+", " ", r)
    for marca, claves in _MARCAS:
        for clave in claves:
            if clave == "BP ":
                if re.search(r"(^|\W)BP(\W|$)", r):
                    return marca
            elif clave in r:
                return marca
    limpio = r.strip()
    return limpio if limpio else "SIN RÓTULO"


def _num(valor):
    if valor is None:
        return np.nan
    s = str(valor).strip().replace(",", ".")
    if not s:
        return np.nan
    try:
        return float(s)
    except ValueError:
        return np.nan


def ahora_madrid():
    return datetime.now(TZ)


def _simular_fallo_directo():
    return os.environ.get("KMCOST_SIMULAR_FALLO_DIRECTO") == "1"


def _leer_snapshot_json(nombre, gzipped=False):
    # Parámetro de 10 min para evitar caché vieja de CDN
    ts = int(ahora_madrid().timestamp() // 600)
    r = requests.get(f"{SNAPSHOT_BASE}/{nombre}?t={ts}", headers=HEADERS, timeout=(6, 20))
    r.raise_for_status()
    if gzipped:
        with gzip.GzipFile(fileobj=io.BytesIO(r.content)) as gz:
            return json.load(gz)
    return r.json()


def _parsear_miteco(lista):
    filas = []
    for e in lista:
        fila = {
            "id": e.get("IDEESS"),
            "rotulo": (e.get("Rótulo") or "").strip(),
            "direccion": (e.get("Dirección") or "").strip(),
            "municipio": (e.get("Municipio") or "").strip(),
            "localidad": (e.get("Localidad") or "").strip(),
            "provincia": (e.get("Provincia") or "").strip(),
            "id_provincia": e.get("IDProvincia"),
            "cp": e.get("C.P."),
            "horario": (e.get("Horario") or "").strip(),
            "margen": e.get("Margen"),
            "tipo_venta": e.get("Tipo Venta"),
            "lat": _num(e.get("Latitud")),
            "lon": _num(e.get("Longitud (WGS84)")),
        }
        for nombre, campo in COMBUSTIBLES.items():
            fila[nombre] = _num(e.get(campo))
        filas.append(fila)
    df = pd.DataFrame(filas)
    if df.empty:
        return df
    df = df.dropna(subset=["lat", "lon"])
    df["marca"] = df["rotulo"].map(normalizar_marca)
    df["24h"] = df["horario"].str.contains("24H", case=False, na=False)
    df["publica"] = df["tipo_venta"].eq("P")
    return df.reset_index(drop=True)


# ---------------------------------------------------------------- Carburantes
def cargar_estaciones():
    """Gasolineras de España (precios oficiales del MITECO).

    Intenta primero la descarga en directo (TLS endurecido); si falla, usa la instantánea
    automática de GitHub (`rama data`). Devuelve `(DataFrame, fecha_texto, origen, error)`.
    `origen` vale `'directo'`, `'snapshot'` o `None`.
    """
    error_live = None
    try:
        df, fecha = _descargar_estaciones_directo()
        return df, fecha, "directo", None
    except Exception as exc:  # noqa: BLE001
        error_live = str(exc)

    try:
        df, fecha = _descargar_estaciones_snapshot()
        return df, fecha, "snapshot", None
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(), None, None, (
            f"No se pudieron cargar precios ni en directo ({error_live}) ni desde la instantánea ({exc})."
        )


@st.cache_data(ttl=40 * 60, show_spinner=False)
def _descargar_estaciones_directo():
    if _simular_fallo_directo():
        raise RuntimeError("fallo directo simulado")
    r = get_resiliente(MITECO_URL, timeout=(5, 16), intentos_por_perfil=1, http_fallback=True)
    data = r.json()
    df = _parsear_miteco(data.get("ListaEESSPrecio", []))
    if df.empty:
        raise RuntimeError("la API del Ministerio no devolvió estaciones")
    return df, data.get("Fecha")


@st.cache_data(ttl=20 * 60, show_spinner=False)
def _descargar_estaciones_snapshot():
    data = _leer_snapshot_json("estaciones.json.gz", gzipped=True)
    df = _parsear_miteco(data.get("ListaEESSPrecio", []))
    if df.empty:
        raise RuntimeError("la instantánea llegó vacía")
    return df, data.get("Fecha")


@st.cache_data(ttl=20 * 60, show_spinner=False)
def _descargar_provincia(id_provincia):
    if _simular_fallo_directo():
        return pd.DataFrame(), None
    try:
        r = get_resiliente(f"{MITECO_PROV_URL}{id_provincia}", timeout=(4, 9),
                           intentos_por_perfil=1, http_fallback=True)
        d = r.json()
        df = _parsear_miteco(d.get("ListaEESSPrecio", []))
        return df, d.get("Fecha")
    except Exception:  # noqa: BLE001
        return pd.DataFrame(), None


def actualizar_provincias(df_base, ids_provincia):
    """Si el servidor permite FiltroProvincia en directo, actualiza esas provincias sobre df_base.

    Devuelve `(df_actualizado, fecha_directo_o_None, n_provincias_actualizadas)`.
    """
    ids = [p for p in dict.fromkeys(ids_provincia) if p]
    if not ids:
        return df_base, None, 0
    trozos = []
    fecha = None
    actualizadas = []
    for pid in ids:
        df_p, f_p = _descargar_provincia(pid)
        if not df_p.empty:
            trozos.append(df_p)
            actualizadas.append(pid)
            fecha = fecha or f_p
        elif not actualizadas:
            # Si falla la primera provincia (bloqueo de IP en la nube), no insiste con el resto.
            return df_base, None, 0
    if not actualizadas:
        return df_base, None, 0
    resto = df_base[~df_base["id_provincia"].isin(actualizadas)] if not df_base.empty else df_base
    nuevo = pd.concat([resto, *trozos], ignore_index=True)
    return nuevo, fecha, len(actualizadas)


def media_provincial(df, id_provincia, combustible):
    if df.empty or combustible not in df:
        return None
    sub = df[(df["id_provincia"] == id_provincia) & df["publica"]][combustible].dropna()
    return float(sub.mean()) if len(sub) else None


# ---------------------------------------------------------------- Geocodificación y rutas
def geocodificar(texto):
    """Devuelve lista de dicts {nombre, lat, lon}. Nominatim y, si falla, Photon."""
    texto = (texto or "").strip()
    if len(texto) < 3:
        return []
    try:
        return _geocodificar(texto)
    except Exception:  # noqa: BLE001
        return []


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _geocodificar(texto):
    try:
        r = requests.get(
            NOMINATIM_URL,
            params={"q": texto, "format": "jsonv2", "limit": 5, "countrycodes": "es",
                    "accept-language": "es"},
            headers=HEADERS, timeout=10,
        )
        r.raise_for_status()
        res = [{"nombre": x["display_name"], "lat": float(x["lat"]), "lon": float(x["lon"])}
               for x in r.json()]
        if res:
            return res
    except Exception:  # noqa: BLE001
        pass
    try:
        r = requests.get(PHOTON_URL, params={"q": texto, "limit": 5, "lang": "es",
                                             "bbox": "-18.5,27.5,4.6,44.0"},
                         headers=HEADERS, timeout=10)
        r.raise_for_status()
        res = []
        for f in r.json().get("features", []):
            p = f.get("properties", {})
            lon, lat = f["geometry"]["coordinates"]
            partes = [p.get(k) for k in ("name", "street", "housenumber", "city", "state") if p.get(k)]
            res.append({"nombre": ", ".join(dict.fromkeys(partes)) or texto, "lat": lat, "lon": lon})
        return res
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("geocodificación no disponible") from exc


def calcular_ruta(lon1, lat1, lon2, lat2):
    """Ruta por carretera con OSRM (HTTPS, dos servidores). Devuelve dict o None."""
    try:
        return _ruta_osrm(round(lon1, 6), round(lat1, 6), round(lon2, 6), round(lat2, 6))
    except Exception:  # noqa: BLE001
        return None


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _ruta_osrm(lon1, lat1, lon2, lat2):
    ultimo = None
    for base in OSRM_URLS:
        url = f"{base}{lon1:.6f},{lat1:.6f};{lon2:.6f},{lat2:.6f}"
        try:
            r = requests.get(url, params={"overview": "full", "geometries": "geojson"},
                             headers=HEADERS, timeout=(6, 18))
            r.raise_for_status()
            data = r.json()
            if data.get("code") == "Ok" and data.get("routes"):
                ruta = data["routes"][0]
                return {
                    "distancia_km": ruta["distance"] / 1000.0,
                    "duracion_min": (ruta["duration"] / 60.0) * 0.82,  # factor de corrección vs Google/Waze,
                    "coords": ruta["geometry"]["coordinates"],
                }
        except Exception as exc:  # noqa: BLE001
            ultimo = exc
    raise RuntimeError(f"sin ruta OSRM: {ultimo}")


# ---------------------------------------------------------------- Electricidad
def precio_pvpc():
    """PVPC 2.0TD (término de energía, €/kWh, sin impuestos) de hoy, Península."""
    hoy = ahora_madrid().date()
    try:
        return _pvpc(str(hoy), ahora_madrid().hour)
    except Exception:  # noqa: BLE001
        pass
    try:
        return _pvpc_snapshot(ahora_madrid().hour)
    except Exception:  # noqa: BLE001
        return {"media": 0.15, "actual": 0.15, "min": None, "max": None, "fuente": None,
                "origen": "referencia", "fecha": str(hoy),
                "error": "No se pudo leer el PVPC; uso 0,15 €/kWh de referencia."}


def _resumen_pvpc(valores, hora, fuente, fecha, origen):
    serie = pd.DataFrame(valores, columns=["hora", "eur_mwh"])
    serie["hora"] = pd.to_datetime(serie["hora"], utc=True).dt.tz_convert(TZ)
    serie["eur_kwh"] = serie["eur_mwh"] / 1000.0
    fila = serie[serie["hora"].dt.hour == hora]
    actual = float(fila["eur_kwh"].iloc[0]) if len(fila) else float(serie["eur_kwh"].mean())
    return {
        "media": float(serie["eur_kwh"].mean()),
        "actual": actual,
        "min": float(serie["eur_kwh"].min()),
        "max": float(serie["eur_kwh"].max()),
        "fuente": fuente,
        "origen": origen,
        "fecha": fecha,
        "error": None,
    }


@st.cache_data(ttl=3600, show_spinner=False)
def _pvpc(hoy, hora):
    if _simular_fallo_directo():
        raise RuntimeError("fallo directo simulado")
    hoy_d = datetime.fromisoformat(hoy).date()
    valores = []
    fuente = None
    try:
        r = get_resiliente(
            REE_PVPC_URL,
            params={"start_date": f"{hoy_d}T00:00", "end_date": f"{hoy_d}T23:59",
                    "time_trunc": "hour", "geo_trunc": "electric_system",
                    "geo_limit": "peninsular", "geo_ids": "8741"},
            timeout=(5, 14), intentos_por_perfil=1,
        )
        for serie in r.json().get("included", []):
            if serie.get("type") == "PVPC" or (serie.get("attributes", {}).get("title") == "PVPC"):
                valores = [(v["datetime"], v["value"]) for v in serie["attributes"]["values"]]
                fuente = "Red Eléctrica (REData)"
                break
    except Exception:  # noqa: BLE001
        valores = []
    if not valores:
        r = get_resiliente(ESIOS_PVPC_URL, params={"start_date": f"{hoy_d}T00:00",
                                                   "end_date": f"{hoy_d}T23:59"},
                           timeout=(5, 14), intentos_por_perfil=1)
        valores = [(v["datetime"], v["value"]) for v in r.json()["indicator"]["values"]
                   if v.get("geo_id") in (8741, None)]
        fuente = "Red Eléctrica (ESIOS)"
    if not valores:
        raise RuntimeError("PVPC no disponible")
    return _resumen_pvpc(valores, hora, fuente, str(hoy_d), "directo")


@st.cache_data(ttl=1800, show_spinner=False)
def _pvpc_snapshot(hora):
    d = _leer_snapshot_json("pvpc.json")
    return _resumen_pvpc(d["valores"], hora, d.get("fuente") or "Red Eléctrica",
                         d.get("fecha") or "", "snapshot")


IEE = 0.0511269632
IVA = 0.21


def electricidad_con_impuestos(precio_energia):
    return precio_energia * (1 + IEE) * (1 + IVA)


# ---------------------------------------------------------------- Puntos de carga
_CONECTORES_DATEX = {
    "iec62196T2COMBO": "CCS2", "iec62196T2": "Tipo 2", "chademo": "CHAdeMO",
    "iec62196T1": "Tipo 1", "iec62196T1COMBO": "CCS1", "domesticF": "Schuko",
    "domesticE": "Schuko", "iec60309x2three32": "CEE 32A", "iec60309x2single16": "CEE 16A",
    "iec62196T3A": "Tipo 3A", "iec62196T3C": "Tipo 3C", "domesticA": "Doméstico A",
    "domesticL": "Doméstico L",
}


def _formatear_fecha_dgt(publicacion):
    if not publicacion:
        return ""
    try:
        return datetime.fromisoformat(publicacion).astimezone(TZ).strftime(" · %d/%m/%Y %H:%M")
    except ValueError:
        return ""


@st.cache_data(ttl=12 * 3600, show_spinner=False, max_entries=1)
def _cargadores_dgt_directo():
    import xml.etree.ElementTree as ET

    if _simular_fallo_directo():
        raise RuntimeError("fallo directo simulado")
    r = get_resiliente(DGT_NAP_URL, timeout=(6, 25), intentos_por_perfil=1,
                       headers={"User-Agent": USER_AGENT, "Accept": "*/*"}, stream=True)
    r.raw.decode_content = True

    def local(tag):
        return tag.rsplit("}", 1)[-1]

    filas = []
    publicacion = None
    for _, elem in ET.iterparse(r.raw, events=("end",)):
        nombre = local(elem.tag)
        if nombre == "publicationTime" and publicacion is None:
            publicacion = (elem.text or "").strip()
        if nombre != "energyInfrastructureSite":
            continue
        site_nombre = operador = municipio = None
        lat = lon = None
        potencia = 0.0
        conectores = set()
        puntos = 0
        for hijo in elem.iter():
            n = local(hijo.tag)
            if n == "latitude" and lat is None:
                lat = hijo.text
            elif n == "longitude" and lon is None:
                lon = hijo.text
            elif n == "maxPowerAtSocket":
                try:
                    potencia = max(potencia, float(hijo.text) / 1000.0)
                except (TypeError, ValueError):
                    pass
            elif n == "connectorType" and hijo.text:
                conectores.add(_CONECTORES_DATEX.get(hijo.text.strip(), hijo.text.strip()))
            elif n == "refillPoint":
                puntos += 1
        for hijo in elem:
            n = local(hijo.tag)
            if n == "name" and site_nombre is None:
                v = next((x.text for x in hijo.iter() if local(x.tag) == "value"), None)
                site_nombre = (v or "").strip()
            elif n == "operator":
                v = next((x.text for x in hijo.iter() if local(x.tag) == "value"), None)
                operador = (v or "").strip()
        for x in elem.iter():
            if local(x.tag) == "value" and x.text and x.text.startswith("Municipio:"):
                municipio = x.text.split(":", 1)[1].strip()
                break
        try:
            filas.append({
                "nombre": site_nombre or "Punto de carga", "operador": operador or "",
                "lat": float(lat), "lon": float(lon), "potencia_kw": potencia or None,
                "conectores": ", ".join(sorted(conectores)), "plazas": puntos or "",
                "acceso": "", "coste": "", "municipio": municipio or "",
            })
        except (TypeError, ValueError):
            pass
        elem.clear()
    if not filas:
        raise RuntimeError("el inventario de la DGT llegó vacío")
    return pd.DataFrame(filas), publicacion


@st.cache_data(ttl=6 * 3600, show_spinner=False, max_entries=1)
def _cargadores_dgt_snapshot():
    d = _leer_snapshot_json("cargadores.json.gz", gzipped=True)
    df = pd.DataFrame(d.get("estaciones", []))
    if df.empty:
        raise RuntimeError("instantánea de cargadores vacía")
    return df, d.get("publicacion")


def cargadores_dgt():
    """Puntos de carga públicos de España (DGT directo y, si falla, instantánea GitHub)."""
    err_live = None
    try:
        df, pub = _cargadores_dgt_directo()
        return df, f"Inventario oficial MITERD/DGT{_formatear_fecha_dgt(pub)}", None
    except Exception as exc:  # noqa: BLE001
        err_live = exc
    try:
        df, pub = _cargadores_dgt_snapshot()
        return df, f"Inventario MITERD/DGT (instantánea){_formatear_fecha_dgt(pub)}", None
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(), None, f"Inventario DGT no disponible ({err_live}; {exc})"


def _potencia_max(tags):
    maximo = 0.0
    for k, v in tags.items():
        if k.endswith(":output") or k == "charging_station:output":
            m = re.search(r"([\d.,]+)\s*(kw|w)?", str(v).lower())
            if m:
                try:
                    val = float(m.group(1).replace(",", "."))
                except ValueError:
                    continue
                if m.group(2) == "w" and val > 1000:
                    val = val / 1000
                maximo = max(maximo, val)
    return maximo or None


def _conectores(tags):
    nombres = {"type2": "Tipo 2", "type2_combo": "CCS2", "chademo": "CHAdeMO",
               "schuko": "Schuko", "tesla_supercharger": "Tesla", "type1": "Tipo 1",
               "type2_cable": "Tipo 2 (cable)", "tesla_supercharger_ccs": "Tesla CCS"}
    res = []
    for k in tags:
        if k.startswith("socket:") and k.count(":") == 1:
            tipo = k.split(":")[1]
            res.append(nombres.get(tipo, tipo))
    return ", ".join(sorted(set(res)))


def _cajas_ruta(puntos, radio_km, tramo_km=40.0):
    import math

    from .geo import km_acumulados

    acum = km_acumulados([list(p) for p in puntos])
    cajas = []
    inicio = 0
    for i in range(1, len(puntos)):
        if acum[i] - acum[inicio] >= tramo_km or i == len(puntos) - 1:
            tramo = puntos[inicio:i + 1]
            lats = [p[1] for p in tramo]
            lons = [p[0] for p in tramo]
            dlat = radio_km / 110.574
            dlon = radio_km / (111.320 * max(math.cos(math.radians(sum(lats) / len(lats))), 0.1))
            cajas.append((min(lats) - dlat, min(lons) - dlon, max(lats) + dlat, max(lons) + dlon))
            inicio = i
    return cajas


def cargadores_osm(coords_ruta, radio_km=5.0):
    puntos = tuple((round(lon, 4), round(lat, 4)) for lon, lat in simplificar(coords_ruta, 220))
    try:
        return _overpass(puntos, float(radio_km))
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(), None, f"No se pudo consultar Overpass (OpenStreetMap): {exc}"


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _overpass(puntos, radio_km):
    import time

    cajas = _cajas_ruta(puntos, radio_km)
    partes = "".join(
        f'nwr["amenity"="charging_station"]({s:.4f},{w:.4f},{n:.4f},{e:.4f});' for s, w, n, e in cajas
    )
    consulta = f"[out:json][timeout:60];({partes});out center tags;"
    errores = []
    limite = time.monotonic() + 60
    for url in OVERPASS_MIRRORS:
        restante = limite - time.monotonic()
        if restante < 10:
            errores.append("tiempo agotado")
            break
        host = url.split("/")[2]
        try:
            r = requests.post(url, data={"data": consulta}, headers=HEADERS,
                              timeout=(6, min(40, restante)))
            if r.status_code != 200:
                errores.append(f"{host}: HTTP {r.status_code}")
                continue
            elementos = r.json().get("elements", [])
        except Exception as exc:  # noqa: BLE001
            errores.append(f"{host}: {type(exc).__name__}")
            continue
        filas = []
        for e in elementos:
            tags = e.get("tags", {}) or {}
            lat = e.get("lat") or (e.get("center") or {}).get("lat")
            lon = e.get("lon") or (e.get("center") or {}).get("lon")
            if lat is None or lon is None:
                continue
            filas.append({
                "nombre": tags.get("name") or tags.get("brand") or tags.get("operator") or "Punto de carga",
                "operador": tags.get("operator") or tags.get("network") or tags.get("brand") or "",
                "lat": float(lat), "lon": float(lon),
                "potencia_kw": _potencia_max(tags),
                "conectores": _conectores(tags),
                "plazas": tags.get("capacity", ""),
                "acceso": tags.get("access", ""),
                "coste": tags.get("fee", ""),
            })
        df = pd.DataFrame(filas).drop_duplicates(subset=["lat", "lon"]) if filas else pd.DataFrame(
            columns=["nombre", "operador", "lat", "lon", "potencia_kw", "conectores", "plazas",
                     "acceso", "coste"])
        return df.reset_index(drop=True), f"OpenStreetMap ({host})", None
    raise RuntimeError("; ".join(errores))


def cargadores_ocm(coords_ruta, api_key, radio_km=5.0):
    puntos = tuple((round(lon, 4), round(lat, 4)) for lon, lat in simplificar(coords_ruta, 150))
    try:
        return _ocm(puntos, api_key, float(radio_km))
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(), None, f"OpenChargeMap no respondió: {exc}"


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _ocm(puntos, api_key, radio_km):
    r = requests.get(
        OCM_URL,
        params={"key": api_key, "output": "json", "polyline": codificar_polilinea(puntos),
                "distance": radio_km, "distanceunit": "KM", "maxresults": 2000,
                "compact": "true", "verbose": "false"},
        headers=HEADERS, timeout=40,
    )
    r.raise_for_status()
    datos = r.json()
    filas = []
    for p in datos:
        a = p.get("AddressInfo") or {}
        conns = p.get("Connections") or []
        potencias = [c.get("PowerKW") for c in conns if c.get("PowerKW")]
        filas.append({
            "nombre": a.get("Title") or "Punto de carga",
            "operador": ((p.get("OperatorInfo") or {}).get("Title")) or "",
            "lat": a.get("Latitude"), "lon": a.get("Longitude"),
            "potencia_kw": max(potencias) if potencias else None,
            "conectores": "",
            "plazas": p.get("NumberOfPoints") or "",
            "acceso": "",
            "coste": p.get("UsageCost") or "",
        })
    return pd.DataFrame(filas), "OpenChargeMap", None


# ---------------------------------------------------------------- Brent
@st.cache_data(ttl=6 * 3600, show_spinner=False)
def historico_brent(dias=365):
    try:
        import yfinance as yf
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    for simbolo in ("BZ=F", "BRNT.L"):
        try:
            hist = yf.Ticker(simbolo).history(period=f"{int(dias)}d")
            if not hist.empty and "Close" in hist.columns:
                df = hist[["Close"]].reset_index()
                df.columns = ["Fecha", "Precio_Brent"]
                df["Fecha"] = pd.to_datetime(df["Fecha"]).dt.tz_localize(None).dt.normalize()
                return df
        except Exception:  # noqa: BLE001
            continue
    return pd.DataFrame()


def enlaces_navegacion(lat, lon):
    return (
        f"https://www.google.com/maps/dir/?api=1&destination={lat:.6f},{lon:.6f}&travelmode=driving",
        f"https://waze.com/ul?ll={lat:.6f},{lon:.6f}&navigate=yes",
    )


__all__ = [
    "COMBUSTIBLES", "PROVINCIAS", "cargar_estaciones", "actualizar_provincias",
    "media_provincial", "geocodificar", "calcular_ruta", "precio_pvpc",
    "electricidad_con_impuestos", "cargadores_dgt", "cargadores_osm", "cargadores_ocm",
    "historico_brent", "enlaces_navegacion", "normalizar_marca", "ahora_madrid", "timedelta",
]
