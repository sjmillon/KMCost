"""Descarga instantáneas de MITECO, REE (PVPC) y MITERD/DGT para la rama `data`."""
from datetime import datetime
import gzip
import json
import os
import sys
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kmcost.net import USER_AGENT, get_resiliente  # noqa: E402

TZ = ZoneInfo("Europe/Madrid")

MITECO_URL = (
    "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/"
    "PreciosCarburantes/EstacionesTerrestres/"
)
MITECO_PROV_URL = MITECO_URL + "FiltroProvincia/"
REE_PVPC_URL = "https://apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real"
ESIOS_PVPC_URL = "https://api.esios.ree.es/indicators/1001"
DGT_NAP_URL = (
    "https://nap.dgt.es/datex2/v3/miterd/EnergyInfrastructureTablePublication/electrolineras.xml"
)

CONECTORES_DATEX = {
    "iec62196T2COMBO": "CCS2", "iec62196T2": "Tipo 2", "chademo": "CHAdeMO",
    "iec62196T1": "Tipo 1", "iec62196T1COMBO": "CCS1", "domesticF": "Schuko",
    "domesticE": "Schuko", "iec60309x2three32": "CEE 32A", "iec60309x2single16": "CEE 16A",
    "iec62196T3A": "Tipo 3A", "iec62196T3C": "Tipo 3C", "domesticA": "Doméstico A",
    "domesticL": "Doméstico L",
}


def descargar_miteco(out_dir):
    try:
        r = get_resiliente(MITECO_URL, timeout=(8, 45), intentos_por_perfil=2, http_fallback=True)
        data = r.json()
        if data.get("ListaEESSPrecio"):
            ruta = os.path.join(out_dir, "estaciones.json.gz")
            with gzip.open(ruta, "wt", encoding="utf-8") as f:
                json.dump({"Fecha": data.get("Fecha"), "ListaEESSPrecio": data["ListaEESSPrecio"]},
                          f, ensure_ascii=False, separators=(",", ":"))
            print(f"MITECO nacional OK: {len(data['ListaEESSPrecio'])} ({data.get('Fecha')})")
            return data.get("Fecha"), len(data["ListaEESSPrecio"])
    except Exception as exc:  # noqa: BLE001
        print(f"MITECO nacional falló ({exc}); pruebo por provincias…")

    lista = []
    fecha = None
    for i in range(1, 53):
        pid = f"{i:02d}"
        try:
            r = get_resiliente(f"{MITECO_PROV_URL}{pid}", timeout=(6, 18), intentos_por_perfil=2,
                               http_fallback=True)
            d = r.json()
            if not fecha:
                fecha = d.get("Fecha")
            lista.extend(d.get("ListaEESSPrecio") or [])
        except Exception as exc:  # noqa: BLE001
            print(f"  Provincia {pid} falló: {exc}")
    if len(lista) < 5000:
        raise RuntimeError(f"MITECO por provincias incompleto ({len(lista)} estaciones)")
    ruta = os.path.join(out_dir, "estaciones.json.gz")
    with gzip.open(ruta, "wt", encoding="utf-8") as f:
        json.dump({"Fecha": fecha, "ListaEESSPrecio": lista}, f, ensure_ascii=False,
                  separators=(",", ":"))
    print(f"MITECO provincial OK: {len(lista)} ({fecha})")
    return fecha, len(lista)


def descargar_pvpc(out_dir):
    hoy = datetime.now(TZ).date()
    valores = []
    fuente = None
    try:
        r = get_resiliente(
            REE_PVPC_URL,
            params={"start_date": f"{hoy}T00:00", "end_date": f"{hoy}T23:59",
                    "time_trunc": "hour", "geo_trunc": "electric_system",
                    "geo_limit": "peninsular", "geo_ids": "8741"},
            timeout=(8, 25), intentos_por_perfil=2,
        )
        for serie in r.json().get("included", []):
            if serie.get("type") == "PVPC" or (serie.get("attributes", {}).get("title") == "PVPC"):
                valores = [[v["datetime"], v["value"]] for v in serie["attributes"]["values"]]
                fuente = "Red Eléctrica (REData)"
                break
    except Exception as exc:  # noqa: BLE001
        print(f"REData PVPC falló ({exc}); pruebo ESIOS…")

    if not valores:
        r = get_resiliente(
            ESIOS_PVPC_URL,
            params={"start_date": f"{hoy}T00:00", "end_date": f"{hoy}T23:59"},
            timeout=(8, 25), intentos_por_perfil=2,
        )
        valores = [[v["datetime"], v["value"]] for v in r.json()["indicator"]["values"]
                   if v.get("geo_id") in (8741, None)]
        fuente = "Red Eléctrica (ESIOS)"

    if not valores:
        raise RuntimeError("PVPC sin valores")

    ruta = os.path.join(out_dir, "pvpc.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"fecha": str(hoy), "fuente": fuente, "valores": valores},
                  f, ensure_ascii=False, separators=(",", ":"))
    print(f"PVPC OK ({fuente}): {len(valores)} horas")
    return str(hoy), fuente


def descargar_cargadores(out_dir):
    r = get_resiliente(DGT_NAP_URL, timeout=(10, 120), intentos_por_perfil=2,
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
                conectores.add(CONECTORES_DATEX.get(hijo.text.strip(), hijo.text.strip()))
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
                "nombre": site_nombre or "Punto de carga",
                "operador": operador or "",
                "lat": float(lat),
                "lon": float(lon),
                "potencia_kw": potencia or None,
                "conectores": ", ".join(sorted(conectores)),
                "plazas": puntos or "",
                "acceso": "",
                "coste": "",
                "municipio": municipio or "",
            })
        except (TypeError, ValueError):
            pass
        elem.clear()

    if not filas:
        raise RuntimeError("el inventario de la DGT llegó vacío")
    ruta = os.path.join(out_dir, "cargadores.json.gz")
    with gzip.open(ruta, "wt", encoding="utf-8") as f:
        json.dump({"publicacion": publicacion, "estaciones": filas}, f, ensure_ascii=False,
                  separators=(",", ":"))
    print(f"DGT cargadores OK: {len(filas)} ({publicacion})")
    return publicacion, len(filas)


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kmcost_snapshot"
    os.makedirs(out_dir, exist_ok=True)
    meta_path = os.path.join(out_dir, "meta.json")
    meta = {}
    if os.path.exists(meta_path):
        try:
            meta = json.load(open(meta_path, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            meta = {}

    errores = []
    try:
        m_fecha, m_n = descargar_miteco(out_dir)
        meta["miteco_fecha"] = m_fecha
        meta["n_estaciones"] = m_n
    except Exception as exc:  # noqa: BLE001
        errores.append(f"MITECO: {exc}")

    try:
        p_fecha, p_fuente = descargar_pvpc(out_dir)
        meta["pvpc_fecha"] = p_fecha
        meta["pvpc_fuente"] = p_fuente
    except Exception as exc:  # noqa: BLE001
        errores.append(f"PVPC: {exc}")

    try:
        d_pub, d_n = descargar_cargadores(out_dir)
        meta["dgt_publicacion"] = d_pub
        meta["n_cargadores"] = d_n
    except Exception as exc:  # noqa: BLE001
        errores.append(f"DGT: {exc}")

    ahora_m = datetime.now(TZ)
    meta["actualizado_madrid"] = ahora_m.strftime("%d/%m/%Y %H:%M")
    meta["actualizado_iso"] = ahora_m.isoformat()
    meta["errores"] = errores
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    if len(errores) == 3:
        raise SystemExit("Fallaron las tres fuentes: " + "; ".join(errores))
    if errores:
        print("Avisos parciales:", "; ".join(errores))


if __name__ == "__main__":
    main()
