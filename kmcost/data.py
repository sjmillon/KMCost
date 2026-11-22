"""Fuentes de datos externas (todas públicas). Las llamadas se cachean con st.cache_data."""
from datetime import datetime, timedelta
import re
import unicodedata
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import streamlit as st

from .geo import codificar_polilinea, simplificar

TZ = ZoneInfo("Europe/Madrid")
USER_AGENT = "KMCost/2.0 (+https://github.com/sjmillon/KMCost)"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}

MITECO_URL = (
    "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/"
    "PreciosCarburantes/EstacionesTerrestres/"
)
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/"
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

# Nombre en la app -> campo de la API del Ministerio
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

# Marcas agrupadas (el rótulo de la API es texto libre)
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


def _get_json_reintentos(url, intentos=3, timeout=30, **kwargs):
    """GET con reintentos y espera creciente (la API del Ministerio corta conexiones a veces)."""
    import time

    ultimo = None
    for i in range(intentos):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout, **kwargs)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            ultimo = exc
            time.sleep(1.5 * (i + 1))
    raise ultimo


def ahora_madrid():
    return datetime.now(TZ)


# ---------------------------------------------------------------- Carburantes
def cargar_estaciones():
    """Todas las gasolineras de España con precios oficiales del MITECO.

    Devuelve (DataFrame, fecha_texto, error). Caché de 45 minutos (los errores no se cachean).
    """
    try:
        return _descargar_estaciones()
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(), None, f"No se pudieron descargar los precios del Ministerio: {exc}"


@st.cache_data(ttl=45 * 60, show_spinner=False)
def _descargar_estaciones():
    data = _get_json_reintentos(MITECO_URL, intentos=3, timeout=60)

    filas = []
    for e in data.get("ListaEESSPrecio", []):
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
        raise RuntimeError("la API del Ministerio no devolvió estaciones")
    df = df.dropna(subset=["lat", "lon"])
    df["marca"] = df["rotulo"].map(normalizar_marca)
    df["24h"] = df["horario"].str.contains("24H", case=False, na=False)
    df["publica"] = df["tipo_venta"].eq("P")
    return df.reset_index(drop=True), data.get("Fecha"), None


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
    """Ruta por carretera con OSRM (HTTPS). Devuelve dict o None."""
    try:
        return _ruta_osrm(round(lon1, 6), round(lat1, 6), round(lon2, 6), round(lat2, 6))
    except Exception:  # noqa: BLE001
        return None


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _ruta_osrm(lon1, lat1, lon2, lat2):
    url = f"{OSRM_URL}{lon1:.6f},{lat1:.6f};{lon2:.6f},{lat2:.6f}"
    r = requests.get(url, params={"overview": "full", "geometries": "geojson"},
                     headers=HEADERS, timeout=25)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        raise RuntimeError(data.get("message") or "sin ruta")
    ruta = data["routes"][0]
    return {
        "distancia_km": ruta["distance"] / 1000.0,
        "duracion_min": ruta["duration"] / 60.0,
        "coords": ruta["geometry"]["coordinates"],  # [[lon, lat], ...]
    }


# ---------------------------------------------------------------- Electricidad
def precio_pvpc():
    """PVPC 2.0TD (término de energía, €/kWh, sin impuestos) de hoy, Península.

    Fuente principal: REData (apidatos.ree.es). Respaldo: indicador 1001 de ESIOS.
    """
    hoy = ahora_madrid().date()
    try:
        return _pvpc(str(hoy), ahora_madrid().hour)
    except Exception:  # noqa: BLE001
        return {"media": 0.15, "actual": 0.15, "min": None, "max": None, "fuente": None,
                "fecha": str(hoy), "error": "No se pudo leer el PVPC; uso 0,15 €/kWh de referencia."}


@st.cache_data(ttl=3600, show_spinner=False)
def _pvpc(hoy, hora):
    hoy = datetime.fromisoformat(hoy).date()
    valores = []
    fuente = None
    try:
        r = requests.get(
            REE_PVPC_URL,
            params={"start_date": f"{hoy}T00:00", "end_date": f"{hoy}T23:59", "time_trunc": "hour",
                    "geo_trunc": "electric_system", "geo_limit": "peninsular", "geo_ids": "8741"},
            headers=HEADERS, timeout=20,
        )
        r.raise_for_status()
        for serie in r.json().get("included", []):
            if serie.get("type") == "PVPC" or (serie.get("attributes", {}).get("title") == "PVPC"):
                valores = [(v["datetime"], v["value"]) for v in serie["attributes"]["values"]]
                fuente = "Red Eléctrica (REData)"
                break
    except Exception:  # noqa: BLE001
        valores = []
    if not valores:
        try:
            r = requests.get(ESIOS_PVPC_URL, params={"start_date": f"{hoy}T00:00",
                                                     "end_date": f"{hoy}T23:59"},
                             headers=HEADERS, timeout=20)
            r.raise_for_status()
            valores = [(v["datetime"], v["value"]) for v in r.json()["indicator"]["values"]
                       if v.get("geo_id") in (8741, None)]
            fuente = "Red Eléctrica (ESIOS)"
        except Exception:  # noqa: BLE001
            valores = []
    if not valores:
        raise RuntimeError("PVPC no disponible")

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
        "fecha": str(hoy),
        "error": None,
    }


IEE = 0.0511269632  # Impuesto Especial sobre la Electricidad
IVA = 0.21


def electricidad_con_impuestos(precio_energia):
    """Aplica IEE y después IVA a un precio de energía en €/kWh."""
    return precio_energia * (1 + IEE) * (1 + IVA)


# ---------------------------------------------------------------- Puntos de carga
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


def cargadores_osm(coords_ruta, radio_km=5.0):
    """Puntos de carga de OpenStreetMap a lo largo de la ruta (Overpass, con espejos).

    Devuelve (DataFrame, fuente, error).
    """
    puntos = tuple((round(lon, 4), round(lat, 4)) for lon, lat in simplificar(coords_ruta, 220))
    try:
        return _overpass(puntos, float(radio_km))
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(), None, f"No se pudo consultar Overpass (OpenStreetMap): {exc}"


_CONECTORES_DATEX = {
    "iec62196T2COMBO": "CCS2", "iec62196T2": "Tipo 2", "chademo": "CHAdeMO",
    "iec62196T1": "Tipo 1", "iec62196T1COMBO": "CCS1", "domesticF": "Schuko",
    "domesticE": "Schuko", "iec60309x2three32": "CEE 32A", "iec60309x2single16": "CEE 16A",
    "iec62196T3A": "Tipo 3A", "iec62196T3C": "Tipo 3C", "domesticA": "Doméstico A",
    "domesticL": "Doméstico L",
}


@st.cache_data(ttl=12 * 3600, show_spinner=False, max_entries=1)
def _cargadores_dgt():
    """Inventario oficial de puntos de recarga (MITERD vía Punto de Acceso Nacional de la DGT)."""
    import xml.etree.ElementTree as ET

    r = requests.get(DGT_NAP_URL, headers={"User-Agent": USER_AGENT}, timeout=(10, 120), stream=True)
    r.raise_for_status()
    r.raw.decode_content = True

    def local(tag):
        return tag.rsplit("}", 1)[-1]

    filas = []
    publicacion = None
    for evento, elem in ET.iterparse(r.raw, events=("end",)):
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
        # nombre del sitio = primer fac:name directo; operador = fac:operator/fac:name
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


def cargadores_dgt():
    """Devuelve (DataFrame, fuente, error) con todos los puntos de recarga públicos de España."""
    try:
        df, publicacion = _cargadores_dgt()
        fecha = ""
        if publicacion:
            try:
                fecha = datetime.fromisoformat(publicacion).astimezone(TZ).strftime(" · %d/%m/%Y %H:%M")
            except ValueError:
                fecha = ""
        return df, f"Inventario oficial MITERD/DGT{fecha}", None
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(), None, f"Inventario oficial de la DGT no disponible: {exc}"


def _cajas_ruta(puntos, radio_km, tramo_km=40.0):
    """Divide la ruta en tramos y devuelve una caja (s, w, n, e) por tramo, ampliada en radio_km."""
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


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _overpass(puntos, radio_km):
    import time

    cajas = _cajas_ruta(puntos, radio_km)
    partes = "".join(
        f'nwr["amenity"="charging_station"]({s:.4f},{w:.4f},{n:.4f},{e:.4f});' for s, w, n, e in cajas
    )
    consulta = f"[out:json][timeout:60];({partes});out center tags;"
    errores = []
    limite = time.monotonic() + 60  # presupuesto total para no bloquear la app
    for url in OVERPASS_MIRRORS:
        restante = limite - time.monotonic()
        if restante < 10:
            errores.append("tiempo agotado")
            break
        host = url.split("/")[2]
        try:
            r = requests.post(url, data={"data": consulta}, headers=HEADERS,
                              timeout=(6, min(60, restante)))
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


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _ocm(puntos, api_key, radio_km):
    if True:
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


# ---------------------------------------------------------------- Brent (modo casa-trabajo)
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
    "COMBUSTIBLES", "PROVINCIAS", "cargar_estaciones", "media_provincial", "geocodificar",
    "calcular_ruta", "precio_pvpc", "electricidad_con_impuestos", "cargadores_osm",
    "cargadores_ocm", "historico_brent", "enlaces_navegacion", "normalizar_marca",
    "ahora_madrid", "timedelta",
]
