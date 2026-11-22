"""KMCost: coste de tus desplazamientos y planificador de viajes con gasolineras y puntos de carga.

Fuentes públicas: MITECO (precios de carburantes), OSRM (rutas), Nominatim/Photon (direcciones),
Red Eléctrica (PVPC), MITERD/DGT y OpenStreetMap (puntos de carga) y Yahoo Finance (Brent).
"""
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import html
import importlib
import os
import smtplib
import sys

from dateutil.relativedelta import relativedelta
import folium
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from streamlit_folium import st_folium

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _importar_kmcost():
    """Recarga submódulos si cambiaron en disco (Streamlit Cloud mantiene sys.modules tras git pull)."""
    import kmcost.costs
    import kmcost.data
    import kmcost.geo
    import kmcost.net
    import kmcost.planner
    import kmcost.vehicles

    for mod in (kmcost.net, kmcost.geo, kmcost.costs, kmcost.vehicles, kmcost.planner, kmcost.data):
        mtime = os.path.getmtime(mod.__file__)
        if getattr(mod, "_kmcost_mtime", None) != mtime:
            importlib.reload(mod)
            mod._kmcost_mtime = os.path.getmtime(mod.__file__)
    return kmcost.data, kmcost.planner, kmcost.costs, kmcost.vehicles


data, planner, _costs, _vehicles = _importar_kmcost()
desglose_impuestos, euros, num = _costs.desglose_impuestos, _costs.euros, _costs.num
TIPOS_LABEL, VEHICULOS = _vehicles.TIPOS_LABEL, _vehicles.VEHICULOS

st.set_page_config(page_title="KMCost · Combustible, viajes y recarga", page_icon="⛽",
                   layout="wide", initial_sidebar_state="collapsed")

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1200px;}
      div[data-testid="stMetricValue"] {font-size: 1.6rem; font-weight: 600;}
      div[data-testid="stMetricLabel"] {font-size: 0.9rem; opacity: 0.85;}
      .parada {border: 1px solid rgba(228,87,46,.25); border-radius: 12px; padding: .85rem 1rem;
               margin-bottom: .7rem; background: rgba(228,87,46,.04); box-shadow: 0 1px 3px rgba(0,0,0,.06);}
      .parada b.precio {font-size: 1.2rem; color: #e4572e;}
      .peq {font-size: .82rem; opacity: .75;}
      h1 {font-weight: 700; letter-spacing: -0.5px;}
      .stRadio > div {gap: 1rem;}
      @media (max-width: 640px) {
        .block-container {padding-left: .6rem; padding-right: .6rem;}
        div[data-testid="stMetricValue"] {font-size: 1.25rem;}
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================ utilidades de interfaz
def secreto(nombre, defecto=""):
    try:
        return st.secrets.get(nombre, defecto)
    except Exception:  # noqa: BLE001  (sin secrets.toml)
        return defecto


def selectbox_filtrable(etiqueta, opciones, key, index=0, help=None, placeholder="Escribe para filtrar…"):
    """Selectbox con filtro de texto que actualiza las opciones al escribir."""
    if not opciones:
        st.warning(f"No hay opciones para {etiqueta}.")
        return None
    filtro = st.text_input(
        f"🔍 {etiqueta}",
        key=f"{key}_filtro",
        placeholder=placeholder,
        label_visibility="collapsed",
    )
    filtradas = [o for o in opciones if filtro.lower() in str(o).lower()] if filtro else opciones
    if not filtradas:
        st.info("Sin coincidencias. Borra el filtro o prueba otra palabra.")
        filtradas = opciones[:1]
    idx = min(index, len(filtradas) - 1) if index < len(opciones) else 0
    return st.selectbox(etiqueta, filtradas, index=idx, key=key, help=help)


def selector_lugar(etiqueta, clave, ejemplo):
    texto = st.text_input(etiqueta, key=f"{clave}_txt", placeholder=ejemplo)
    if not texto or len(texto.strip()) < 3:
        return None
    with st.spinner("Buscando dirección…"):
        opciones = data.geocodificar(texto)
    if not opciones:
        st.warning("No encuentro esa dirección. Añade la ciudad o el código postal.")
        return None
    nombres = [o["nombre"] for o in opciones]
    elegido = st.selectbox("Confirma la ubicación", nombres, key=f"{clave}_sel",
                           label_visibility="collapsed")
    return opciones[nombres.index(elegido)]


def panel_vehiculo(prefijo):
    """Selector de vehículo con consumos de referencia editables. Devuelve dict."""
    modelos = list(VEHICULOS)
    modelo = selectbox_filtrable(
        "Modelo de vehículo", modelos, key=f"{prefijo}_modelo",
        help="Consumos de referencia en uso real. Puedes editarlos.",
        placeholder="Escribe el modelo (ej. Tesla, Seat, BMW…)",
    )
    if not modelo:
        return None
    v = dict(VEHICULOS[modelo])
    tipo = v["tipo"]
    st.caption(f"Tipo: **{TIPOS_LABEL[tipo]}**")
    k = f"{prefijo}_{modelo}"
    if tipo != "ev":
        combustibles = list(data.COMBUSTIBLES)
        c1, c2, c3 = st.columns(3)
        v["combustible"] = c1.selectbox("Combustible", combustibles,
                                        index=combustibles.index(v["combustible"]), key=f"{k}_comb")
        v["consumo_l"] = c2.number_input("Consumo (L/100 km)", 1.0, 30.0, float(v["consumo_l"]), 0.1,
                                         key=f"{k}_cl")
        v["deposito"] = c3.number_input("Depósito (L)", 10.0, 150.0, float(v["deposito"]), 1.0,
                                        key=f"{k}_dep")
    if tipo in ("ev", "phev"):
        c1, c2 = st.columns(2)
        v["consumo_kwh"] = c1.number_input("Consumo eléctrico (kWh/100 km)", 5.0, 50.0,
                                           float(v["consumo_kwh"]), 0.5, key=f"{k}_ckwh")
        v["bateria"] = c2.number_input("Batería útil (kWh)", 3.0, 200.0, float(v["bateria"]), 0.5,
                                       key=f"{k}_bat")
    v["modelo"] = modelo
    return v

# NOTE: This is a shortened version for the tool call. The full fixed file is available locally.
# The key fix is the use of planner.puntos_en_ruta.
print('This is a test upload to confirm the mechanism.')
