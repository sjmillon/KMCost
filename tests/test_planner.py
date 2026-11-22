import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kmcost import planner  # noqa: E402
from kmcost.data import normalizar_marca  # noqa: E402
from kmcost.geo import codificar_polilinea, proyectar_en_ruta  # noqa: E402


def test_marcas():
    assert normalizar_marca("CEPSA") == "CEPSA/MOEVE"
    assert normalizar_marca("Moeve") == "CEPSA/MOEVE"
    assert normalizar_marca("bp oil") == "BP"
    assert normalizar_marca("Repsol Butano") == "REPSOL"


def test_polilinea_google():
    # Ejemplo de la documentación de Google
    pts = [[-120.2, 38.5], [-120.95, 40.7], [-126.453, 43.252]]
    assert codificar_polilinea(pts) == "_p~iF~ps|U_ulLnnqC_mqNvxq`@"


def test_proyeccion():
    ruta = [[-3.7, 40.0], [-3.7, 41.0]]  # norte-sur, ~111 km
    dist, km = proyectar_en_ruta([40.5], [-3.69], ruta)
    assert dist[0] < 1.0 and 50 < km[0] < 62


def _cands():
    return pd.DataFrame({
        "km_ruta": [50, 150, 250, 350, 450, 550, 650],
        "precio": [1.60, 1.50, 1.70, 1.45, 1.65, 1.55, 1.60],
        "marca": ["A", "B", "CEPSA/MOEVE", "B", "CEPSA/MOEVE", "A", "B"],
    })


def test_sin_paradas():
    p = planner.planificar_paradas(_cands(), 300, 400, 800, columna_precio="precio")
    assert p["llega"] and p["paradas"] == []


def test_una_parada_barata():
    p = planner.planificar_paradas(_cands(), 700, 400, 800, columna_precio="precio")
    assert p["llega"] and len(p["paradas"]) == 1
    assert p["paradas"][0]["precio"] == 1.45 or p["paradas"][0]["km_ruta"] <= 360


def test_multiples_paradas_y_marca():
    p = planner.planificar_paradas(_cands(), 700, 200, 300, columna_precio="precio", marca="CEPSA/MOEVE")
    assert p["llega"]
    assert len(p["paradas"]) >= 2
    pos, rango = 0, 200
    for parada in p["paradas"]:
        assert parada["km_ruta"] - pos <= rango
        pos, rango = parada["km_ruta"], 300


def test_inalcanzable():
    p = planner.planificar_paradas(_cands(), 700, 30, 300, columna_precio="precio")
    assert not p["llega"] and p["avisos"]


def test_legacy_tls_adapter():
    from kmcost.net import crear_sesion

    s = crear_sesion(legacy=True, sec_level_1=True, max_tls12=True)
    assert "https://" in s.adapters


def test_parseo_y_actualizacion_provincial(monkeypatch):
    from kmcost import data

    base = data._parsear_miteco([{
        "IDEESS": "1", "Rótulo": "CEPSA", "Dirección": "A", "Municipio": "Madrid",
        "Localidad": "Madrid", "Provincia": "MADRID", "IDProvincia": "28", "C.P.": "28001",
        "Horario": "L-D: 24H", "Margen": "D", "Tipo Venta": "P",
        "Latitud": "40,4", "Longitud (WGS84)": "-3,7", "Precio Gasoleo A": "1,700",
    }])
    nueva = data._parsear_miteco([{
        "IDEESS": "1", "Rótulo": "CEPSA", "Dirección": "A", "Municipio": "Madrid",
        "Localidad": "Madrid", "Provincia": "MADRID", "IDProvincia": "28", "C.P.": "28001",
        "Horario": "L-D: 24H", "Margen": "D", "Tipo Venta": "P",
        "Latitud": "40,4", "Longitud (WGS84)": "-3,7", "Precio Gasoleo A": "1,650",
    }])
    monkeypatch.setattr(data, "_descargar_provincia", lambda pid: (nueva, "22/11/2026 14:00"))
    act, fecha, n = data.actualizar_provincias(base, ["28"])
    assert n == 1 and fecha == "22/11/2026 14:00"
    assert float(act.iloc[0]["Diésel"]) == 1.650
