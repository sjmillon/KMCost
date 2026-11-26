"""NAVSIQ: coste de tus desplazamientos y planificador de viajes con gasolineras y puntos de carga.

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

st.set_page_config(page_title="NAVSIQ · Combustible, viajes y recarga", page_icon="⛽",
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
    """Pide solo los datos que el usuario conoce de su coche. Sin catálogo."""
    tipo = st.selectbox(
        "Tipo de vehículo",
        ["combustion", "hev", "phev", "ev"],
        format_func=lambda x: TIPOS_LABEL[x],
        key=f"{prefijo}_tipo",
        help="Combustión, híbrido, híbrido enchufable o eléctrico puro.",
    )
    v = {"tipo": tipo, "modelo": "Personalizado"}

    if tipo != "ev":
        combustibles = list(data.COMBUSTIBLES)
        c1, c2, c3 = st.columns(3)
        v["combustible"] = c1.selectbox("Combustible", combustibles, key=f"{prefijo}_comb")
        v["consumo_l"] = c2.number_input(
            "Consumo medio (L/100 km)", 1.0, 30.0, 6.5, 0.1, key=f"{prefijo}_cl",
            help="El que te marca el coche o el que sueles ver en tus viajes.",
        )
        v["deposito"] = c3.number_input(
            "Depósito (L)", 10.0, 150.0, 50.0, 1.0, key=f"{prefijo}_dep"
        )
    if tipo in ("ev", "phev"):
        c1, c2 = st.columns(2)
        v["consumo_kwh"] = c1.number_input(
            "Consumo eléctrico (kWh/100 km)", 5.0, 50.0, 17.0, 0.5, key=f"{prefijo}_ckwh"
        )
        v["bateria"] = c2.number_input(
            "Batería útil (kWh)", 3.0, 200.0, 60.0, 0.5, key=f"{prefijo}_bat"
        )
    return v


def enlaces_html(lat, lon):
    g, w = data.enlaces_navegacion(lat, lon)
    return (f'<a href="{g}" target="_blank" rel="noopener">Google Maps</a> · '
            f'<a href="{w}" target="_blank" rel="noopener">Waze</a>')


def tabla_estaciones(df, columna_precio, max_filas=None):
    if df is None or df.empty:
        st.info("No hay gasolineras que cumplan los filtros.")
        return
    t = df.copy()
    if max_filas:
        t = t.head(max_filas)
    t["Google Maps"] = [data.enlaces_navegacion(a, b)[0] for a, b in zip(t["lat"], t["lon"])]
    t["Waze"] = [data.enlaces_navegacion(a, b)[1] for a, b in zip(t["lat"], t["lon"])]
    t = t.rename(columns={"marca": "Marca", "rotulo": "Rótulo", "municipio": "Municipio",
                          "provincia": "Provincia", columna_precio: "€/L", "km_ruta": "Km en ruta",
                          "desvio_km": "Desvío (km)", "horario": "Horario", "direccion": "Dirección"})
    cols = ["Marca", "€/L", "Km en ruta", "Desvío (km)", "Municipio", "Google Maps", "Waze",
            "Rótulo", "Provincia", "Dirección", "Horario"]
    st.dataframe(
        t[[c for c in cols if c in t]], hide_index=True, width="stretch",
        column_config={
            "€/L": st.column_config.NumberColumn(format="%.3f"),
            "Km en ruta": st.column_config.NumberColumn(format="%.0f"),
            "Desvío (km)": st.column_config.NumberColumn(format="%.1f"),
            "Google Maps": st.column_config.LinkColumn(display_text="Abrir"),
            "Waze": st.column_config.LinkColumn(display_text="Abrir"),
        },
    )


def tabla_cargadores(df, max_filas=None):
    if df is None or df.empty:
        st.info("No hay puntos de carga que cumplan los filtros.")
        return
    t = df.copy()
    if max_filas:
        t = t.head(max_filas)
    t["Google Maps"] = [data.enlaces_navegacion(a, b)[0] for a, b in zip(t["lat"], t["lon"])]
    t["Waze"] = [data.enlaces_navegacion(a, b)[1] for a, b in zip(t["lat"], t["lon"])]
    t = t.rename(columns={"nombre": "Nombre", "operador": "Operador", "potencia_kw": "Potencia (kW)",
                          "conectores": "Conectores", "plazas": "Puntos", "km_ruta": "Km en ruta",
                          "desvio_km": "Desvío (km)", "municipio": "Municipio"})
    cols = ["Nombre", "Potencia (kW)", "Km en ruta", "Desvío (km)", "Google Maps", "Waze", "Operador",
            "Conectores", "Puntos", "Municipio"]
    st.dataframe(
        t[[c for c in cols if c in t]], hide_index=True, width="stretch",
        column_config={
            "Potencia (kW)": st.column_config.NumberColumn(format="%.0f"),
            "Km en ruta": st.column_config.NumberColumn(format="%.0f"),
            "Desvío (km)": st.column_config.NumberColumn(format="%.1f"),
            "Google Maps": st.column_config.LinkColumn(display_text="Abrir"),
            "Waze": st.column_config.LinkColumn(display_text="Abrir"),
        },
    )


def color_precio(precio, p_bajo, p_alto):
    if precio <= p_bajo:
        return "#1a9850"
    if precio >= p_alto:
        return "#d73027"
    return "#fc8d59"


def mapa(ruta, origen, destino, estaciones=None, columna_precio=None, paradas=None,
         cargadores=None, paradas_carga=None, max_estaciones=300, clave="mapa"):
    coords = [[lat, lon] for lon, lat in ruta["coords"]]
    m = folium.Map(location=coords[len(coords) // 2], zoom_start=7, tiles="OpenStreetMap",
                   control_scale=True)
    # Simplificar más la polilínea para render más rápido
    folium.PolyLine(coords[::5] + [coords[-1]], color="#2b6cb0", weight=5, opacity=.8).add_to(m)
    folium.Marker([origen["lat"], origen["lon"]], tooltip="Origen",
                  icon=folium.Icon(color="blue", icon="home", prefix="fa")).add_to(m)
    folium.Marker([destino["lat"], destino["lon"]], tooltip="Destino",
                  icon=folium.Icon(color="darkblue", icon="flag-checkered", prefix="fa")).add_to(m)

    if estaciones is not None and not estaciones.empty and columna_precio:
        capa = folium.FeatureGroup(name="Gasolineras")
        est = estaciones.nsmallest(max_estaciones, columna_precio)
        p_bajo = est[columna_precio].quantile(.25)
        p_alto = est[columna_precio].quantile(.75)
        for _, e in est.iterrows():
            popup = (f"<b>{html.escape(e['rotulo'] or e['marca'])}</b><br>"
                     f"{html.escape(e['direccion'])}, {html.escape(e['municipio'])}<br>"
                     f"<b>{num(e[columna_precio], 3)} €/L</b> · km {e['km_ruta']:.0f} · desvío "
                     f"{num(e['desvio_km'], 1)} km<br>{html.escape(e['horario'])}<br>"
                     f"{enlaces_html(e['lat'], e['lon'])}")
            folium.CircleMarker(
                [e["lat"], e["lon"]], radius=6, weight=1, color="#333",
                fill=True, fill_opacity=.9, fill_color=color_precio(e[columna_precio], p_bajo, p_alto),
                tooltip=f"{e['marca']} · {num(e[columna_precio], 3)} €/L",
                popup=folium.Popup(popup, max_width=280),
            ).add_to(capa)
        capa.add_to(m)

    if cargadores is not None and not cargadores.empty:
        capa = folium.FeatureGroup(name="Puntos de carga")
        for _, c in cargadores.head(300).iterrows():
            pot = c.get("potencia_kw")
            pot_txt = f"{pot:.0f} kW" if pd.notna(pot) and pot else "potencia s/d"
            popup = (f"<b>{html.escape(str(c['nombre']))}</b><br>{html.escape(str(c['operador']))}<br>"
                     f"{pot_txt} · {html.escape(str(c.get('conectores') or ''))}<br>"
                     f"km {c['km_ruta']:.0f} · desvío {num(c['desvio_km'], 1)} km<br>"
                     f"{enlaces_html(c['lat'], c['lon'])}")
            rapido = pd.notna(pot) and pot and pot >= 50
            folium.CircleMarker(
                [c["lat"], c["lon"]], radius=7 if rapido else 4, weight=1, color="#222",
                fill=True, fill_opacity=.85, fill_color="#6a3d9a" if rapido else "#a6cee3",
                tooltip=f"⚡ {c['nombre']} · {pot_txt}", popup=folium.Popup(popup, max_width=280),
            ).add_to(capa)
        capa.add_to(m)

    for i, p in enumerate(paradas or [], 1):
        folium.Marker(
            [p["lat"], p["lon"]], tooltip=f"Parada {i}: {p['marca']} {num(p[columna_precio], 3)} €/L",
            popup=folium.Popup(f"<b>Parada {i}</b><br>{html.escape(p['rotulo'])}<br>"
                               f"{num(p[columna_precio], 3)} €/L<br>{enlaces_html(p['lat'], p['lon'])}",
                               max_width=260),
            icon=folium.Icon(color="green", icon="gas-pump", prefix="fa"),
        ).add_to(m)
    for i, p in enumerate(paradas_carga or [], 1):
        folium.Marker(
            [p["lat"], p["lon"]], tooltip=f"Recarga {i}: {p['nombre']}",
            popup=folium.Popup(f"<b>Recarga {i}</b><br>{html.escape(str(p['nombre']))}<br>"
                               f"{enlaces_html(p['lat'], p['lon'])}", max_width=260),
            icon=folium.Icon(color="purple", icon="bolt", prefix="fa"),
        ).add_to(m)

    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])
    if estaciones is not None and cargadores is not None and not cargadores.empty:
        folium.LayerControl(collapsed=True).add_to(m)
    st_folium(m, height=520, use_container_width=True, returned_objects=[], key=clave)
    leyenda = []
    if estaciones is not None and not estaciones.empty:
        leyenda.append("🟢 25 % más baratas · 🟠 intermedias · 🔴 25 % más caras · ⛽ parada recomendada")
    if cargadores is not None and not cargadores.empty:
        leyenda.append("🟣 carga rápida (≥ 50 kW) · 🔵 carga lenta · ⚡ recarga recomendada")
    if leyenda:
        st.caption(" · ".join(leyenda) + ". Pulsa un punto para abrirlo en Google Maps o Waze.")


def tarjeta_parada(i, p, columna_precio, consumo_l, etiqueta="Parada"):
    litros_lleno = p["km_a_recargar_lleno"] * consumo_l / 100
    litros_min = p["km_minimos"] * consumo_l / 100
    st.markdown(
        f"""<div class="parada">⛽ <b>{etiqueta} {i} · km {p['km_ruta']:.0f}</b> —
        <b>{html.escape(p['marca'])}</b> ({html.escape(p['rotulo'])}), {html.escape(p['municipio'])}
        ({html.escape(p['provincia'])})<br>
        <b class="precio">{num(p[columna_precio], 3)} €/L</b> · desvío {num(p['desvio_km'], 1)} km ·
        {html.escape(p['horario'])}<br>
        <span class="peq">Llegas con ~{p['autonomia_llegada']:.0f} km de autonomía. Llena el depósito
        (~{litros_lleno:.0f} L, {euros(litros_lleno * p[columna_precio])}) o, como mínimo,
        ~{litros_min:.0f} L para llegar con margen.</span><br>
        {enlaces_html(p['lat'], p['lon'])}</div>""",
        unsafe_allow_html=True,
    )


def tarjeta_recarga(i, p, consumo_kwh, precio_kwh):
    kwh = p["km_a_recargar_lleno"] * consumo_kwh / 100
    pot = p.get("potencia_kw")
    pot_txt = f"{pot:.0f} kW" if pd.notna(pot) and pot else "potencia s/d"
    minutos = (kwh / (pot * 0.7) * 60) if pd.notna(pot) and pot else None
    t_txt = f" · ~{minutos:.0f} min" if minutos else ""
    st.markdown(
        f"""<div class="parada">⚡ <b>Recarga {i} · km {p['km_ruta']:.0f}</b> —
        <b>{html.escape(str(p['nombre']))}</b> · {html.escape(str(p['operador']))}<br>
        {pot_txt} · {html.escape(str(p.get('conectores') or ''))} · desvío {num(p['desvio_km'], 1)} km<br>
        <span class="peq">Llegas con ~{p['autonomia_llegada']:.0f} km. Recarga ~{kwh:.0f} kWh
        (~{euros(kwh * precio_kwh)} a {num(precio_kwh, 2)} €/kWh){t_txt}.</span><br>
        {enlaces_html(p['lat'], p['lon'])}</div>""",
        unsafe_allow_html=True,
    )


def precio_luz_panel(prefijo):
    pv = data.precio_pvpc()
    casa_media = data.electricidad_con_impuestos(pv["media"])
    c1, c2 = st.columns(2)
    p_casa = c1.number_input(
        "Luz en casa (€/kWh, con IEE e IVA)", 0.01, 1.5, round(casa_media, 3), 0.005,
        key=f"{prefijo}_pcasa",
        help="Por defecto, el PVPC medio de hoy (Red Eléctrica) más el impuesto eléctrico y el IVA.")
    p_pub = c2.number_input("Cargador público (€/kWh)", 0.05, 2.0, 0.45, 0.01, key=f"{prefijo}_ppub",
                            help="Precio típico de carga rápida en España; edítalo según tu operador.")
    if pv["error"]:
        st.caption(f"⚠️ {pv['error']}")
    else:
        etq = "en directo" if pv.get("origen") == "directo" else "instantánea automática"
        st.caption(
            f"PVPC hoy ({pv['fecha']}, {pv['fuente']}, {etq}): media {num(pv['media'], 3)} €/kWh sin "
            f"impuestos (mín. {num(pv['min'], 3)}, máx. {num(pv['max'], 3)}; ahora "
            f"{num(pv['actual'], 3)}). Con impuestos: {num(casa_media, 3)} €/kWh.")
    return p_casa, p_pub


def provincia_cercana(lat, lon):
    """Provincia (id, nombre) de las gasolineras más cercanas a un punto."""
    if estaciones.empty:
        return None, None
    from kmcost.geo import haversine_km

    d = haversine_km(lat, lon, estaciones["lat"].to_numpy(), estaciones["lon"].to_numpy())
    cerca = estaciones.iloc[d.argsort()[:15]]
    return cerca["id_provincia"].mode().iloc[0], cerca["provincia"].mode().iloc[0].title()


def obtener_cargadores(ruta, desvio_km):
    """Puntos de carga en la ruta: OpenChargeMap (si hay clave) → inventario oficial DGT → OSM."""
    fuentes = []
    errores = []
    clave_ocm = secreto("OCM_API_KEY", "")
    if clave_ocm:
        df, f, e = data.cargadores_ocm(ruta["coords"], clave_ocm, desvio_km)
        if not df.empty:
            return planner.puntos_en_ruta(df, ruta, desvio_km, solo_publicas=False), f, None
        errores.append(e)
    df, f, e = data.cargadores_dgt()
    if not df.empty:
        return planner.puntos_en_ruta(df, ruta, desvio_km, solo_publicas=False), f, None
    errores.append(e)
    df, f, e = data.cargadores_osm(ruta["coords"], desvio_km)
    if not df.empty:
        return planner.puntos_en_ruta(df, ruta, desvio_km, solo_publicas=False), f, None
    errores.append(e)
    return pd.DataFrame(), " / ".join(fuentes) or None, " · ".join(x for x in errores if x)


# ============================================================ cabecera y datos comunes
st.title("⛽ NAVSIQ")
st.caption("Cuánto te cuesta conducir · precios oficiales en tiempo real · gasolineras y puntos de carga en la ruta")

modo = st.radio("Modo", ["🧭 Viajar", "🏠 Casa-trabajo"], horizontal=True, label_visibility="collapsed",
                key="modo")

with st.spinner("Cargando precios oficiales de carburantes…"):
    estaciones, fecha_precios, origen_precios, error_precios = data.cargar_estaciones()
if error_precios:
    st.error(error_precios + " Vuelve a intentarlo en unos minutos.")
else:
    etq_origen = (
        "en directo" if origen_precios == "directo"
        else "instantánea automática de respaldo (el servidor directo del Ministerio no respondió)"
    )
    st.caption(
        f"🕒 Precios oficiales del Ministerio (MITECO): **{fecha_precios}** (hora peninsular) · "
        f"{etq_origen} · {len(estaciones):,} estaciones.".replace(",", ".")
    )


# ============================================================ MODO VIAJAR
def modo_viajar():
    st.subheader("🧭 Planifica tu viaje")
    c_ruta, c_veh = st.columns([1, 1], gap="large")
    with c_ruta:
        origen = selector_lugar("Salida", "vj_origen", "Ej.: Puerta del Sol, Madrid")
        destino = selector_lugar("Llegada", "vj_destino", "Ej.: Algeciras, Cádiz")
    with c_veh:
        veh = panel_vehiculo("vj")
    if not veh:
        st.info("Selecciona un modelo de vehículo para continuar.")
        return

    tipo = veh["tipo"]
    usa_combustible = tipo in ("combustion", "hev", "phev")
    usa_luz = tipo in ("ev", "phev")

    with st.container(border=True):
        st.markdown("**Autonomía y preferencias**")
        c1, c2, c3 = st.columns(3)
        if usa_combustible:
            llena_ref = veh["deposito"] * 100 / veh["consumo_l"]
            aut_llena = c1.number_input("Autonomía con el depósito lleno (km)", 50.0, 3000.0,
                                        float(round(llena_ref)), 10.0,
                                        key=f"vj_aut_llena_{veh['modelo']}",
                                        help="Calculada con depósito y consumo; ajústala a lo que marca tu coche.")
            aut_actual = c2.number_input("Autonomía que te queda ahora (km)", 0.0, 3000.0,
                                         float(round(llena_ref / 2)), 10.0,
                                         key=f"vj_aut_actual_{veh['modelo']}")
        if usa_luz:
            soc = c3.slider("Batería ahora (%)", 5, 100, 100 if tipo == "phev" else 80, 5, key="vj_soc")
        c4, c5, c6 = st.columns(3)
        desvio = c4.slider("Desvío máximo desde la ruta (km)", 1.0, 15.0, 5.0, 0.5, key="vj_desvio")
        if usa_combustible:
            pref = c5.radio("¿Qué buscas?", ["La más barata", "Una marca concreta"], key="vj_pref",
                            horizontal=True)
            solo24 = c6.checkbox("Solo abiertas 24 h", key="vj_24h")
        if tipo == "ev":
            carga_hasta = c5.slider("Cargar en ruta hasta (%)", 50, 100, 80, 5, key="vj_hasta")
            solo_rapida = c6.checkbox("Solo carga rápida (≥ 50 kW)", True, key="vj_rapida")
        with st.expander("Ajustes avanzados"):
            a1, a2 = st.columns(2)
            margen_pct = a1.slider("Margen de seguridad (% de la autonomía)", 0, 30, 10, 1, key="vj_mpct") / 100
            margen_min = a2.number_input("Margen mínimo (km)", 0.0, 200.0, 20.0, 5.0, key="vj_mmin")

    calcular = st.button("Calcular viaje", type="primary", width="stretch", key="vj_calc")
    if calcular:
        if not origen or not destino:
            st.error("Escribe y confirma la salida y la llegada.")
        else:
            with st.spinner("Calculando la ruta…"):
                ruta = data.calcular_ruta(origen["lon"], origen["lat"], destino["lon"], destino["lat"])
            if not ruta:
                st.error("No se pudo calcular la ruta (servidor OSRM). Prueba con otras direcciones o "
                         "en unos minutos.")
            else:
                st.session_state["viaje"] = {"origen": origen, "destino": destino, "ruta": ruta}

    viaje = st.session_state.get("viaje")
    if not viaje:
        st.info("Indica salida, llegada y vehículo y pulsa **Calcular viaje**.")
        return
    origen, destino, ruta = viaje["origen"], viaje["destino"], viaje["ruta"]
    L = ruta["distancia_km"]
    horas, minutos = divmod(int(round(ruta["duracion_min"])), 60)

    st.divider()
    st.markdown(f"#### {html.escape(origen['nombre'].split(',')[0])} → "
                f"{html.escape(destino['nombre'].split(',')[0])}")
    m1, m2, m3 = st.columns(3)
    m1.metric("Distancia", f"{num(L, 0)} km")
    m2.metric("Duración estimada", f"{horas} h {minutos:02d} min")
    st.caption("Tiempo ajustado a valores reales (OSRM corregido). Google Maps y Waze pueden variar ligeramente según el tráfico del momento.")
    m3.metric("Vehículo", veh["modelo"].split(" (")[0])

    # ---------- gasolineras
    cands = pd.DataFrame()
    plan = None
    col = None
    km_elec = 0.0
    if usa_combustible and not estaciones.empty:
        col = veh["combustible"]
        cands = planner.puntos_en_ruta(estaciones, ruta, desvio, columna_precio=col)
        if origen_precios == "snapshot" and not cands.empty:
            provs_ruta = cands["id_provincia"].dropna().unique().tolist()
            est_act, f_prov, n_prov = data.actualizar_provincias(estaciones, provs_ruta)
            if n_prov:
                cands = planner.puntos_en_ruta(est_act, ruta, desvio, columna_precio=col)
                st.caption(f"🔄 Precios de la ruta actualizados en directo ({n_prov} provincias · {f_prov}).")
        if solo24 and not cands.empty:
            cands = cands[cands["24h"]]
    if tipo == "phev":
        km_elec = min(L, veh["bateria"] * soc / 100 * 100 / veh["consumo_kwh"])

    p_casa = p_pub = None
    if usa_luz:
        st.markdown("##### 🔌 Precio de la electricidad")
        p_casa, p_pub = precio_luz_panel("vj")

    if usa_combustible:
        st.markdown(f"##### ⛽ Gasolineras en tu ruta · {col}")
        if estaciones.empty:
            st.warning("Sin precios de carburantes ahora mismo.")
        elif cands.empty:
            st.warning("No hay gasolineras con ese combustible a esa distancia de la ruta. "
                       "Aumenta el desvío permitido.")
        else:
            marcas = planner.resumen_marcas(cands, col)["Marca"].tolist()
            marca = None
            if pref == "Una marca concreta":
                idx = marcas.index("CEPSA/MOEVE") if "CEPSA/MOEVE" in marcas else 0
                marca = selectbox_filtrable("Tu marca", marcas, key="vj_marca", index=idx,
                                            placeholder="Escribe la marca (Repsol, Cepsa, Ballenoil…)")
            plan = planner.planificar_paradas(
                cands, L, aut_actual + km_elec, aut_llena, margen_pct, margen_min, col, marca, "barata")

            barata = cands.nsmallest(1, col).iloc[0]
            precio_ref = (barata[col] if not marca else
                          cands[cands["marca"] == marca][col].min() if (cands["marca"] == marca).any()
                          else barata[col])
            precio_plan = planner.precio_ponderado(plan["paradas"], L, col, precio_ref)

            for a in plan["avisos"]:
                st.warning(a)
            if not plan["paradas"]:
                st.success(f"Con {aut_actual + km_elec:.0f} km de autonomía llegas sin repostar "
                           f"(margen {planner.margen_seguridad(aut_actual + km_elec, margen_pct, margen_min):.0f} km). "
                           "Si quieres repostar por el camino, la mejor opción es:")
                p0 = barata.to_dict() if not marca or not (cands["marca"] == marca).any() else \
                    cands[cands["marca"] == marca].nsmallest(1, col).iloc[0].to_dict()
                p0.update({"autonomia_llegada": aut_actual + km_elec - p0["km_ruta"],
                           "km_a_recargar_lleno": max(aut_llena - (aut_actual + km_elec - p0["km_ruta"]), 0),
                           "km_minimos": 0.0})
                if p0["autonomia_llegada"] > 0:
                    tarjeta_parada(1, p0, col, veh["consumo_l"], etiqueta="Opción")
            else:
                st.markdown(f"**Te recomiendo {len(plan['paradas'])} parada(s):**")
                for i, p in enumerate(plan["paradas"], 1):
                    tarjeta_parada(i, p, col, veh["consumo_l"])

            # -------- coste del viaje
            km_comb = L - km_elec
            litros = km_comb * veh["consumo_l"] / 100
            st.markdown("##### 💶 Coste del viaje")
            opciones = ["Plan recomendado"] + [
                f"{r['marca']} · {r['municipio']} · {num(r[col], 3)} €/L (km {r['km_ruta']:.0f})"
                for _, r in cands.nsmallest(40, col).iterrows()]
            elegido = st.selectbox("Calcular con el precio de…", opciones, key="vj_eleccion")
            if elegido == "Plan recomendado":
                precio_uso = precio_plan
            else:
                precio_uso = cands.nsmallest(40, col).iloc[opciones.index(elegido) - 1][col]

            id_prov, prov_origen = provincia_cercana(origen["lat"], origen["lon"])
            media_prov = data.media_provincial(estaciones, id_prov, col) if id_prov else None
            media_corr = float(cands[col].mean())
            marca_cmp = marca or "CEPSA/MOEVE"
            de_marca = cands[cands["marca"] == marca_cmp]
            precio_marca = None
            if not de_marca.empty:
                plan_m = planner.planificar_paradas(cands, L, aut_actual + km_elec, aut_llena, margen_pct,
                                                    margen_min, col, marca_cmp, "barata")
                precio_marca = planner.precio_ponderado(plan_m["paradas"], L, col, de_marca[col].min())

            coste_elec = 0.0
            kwh_elec = 0.0
            if tipo == "phev":
                kwh_elec = km_elec * veh["consumo_kwh"] / 100
                coste_elec = kwh_elec * p_casa
            coste = litros * precio_uso + coste_elec
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Coste total", euros(coste),
                      help="Combustible del viaje al precio elegido" +
                           (" + electricidad de la batería (precio de casa)" if tipo == "phev" else ""))
            c2.metric(f"{col}", f"{num(litros, 1)} L", f"{num(precio_uso, 3)} €/L", delta_color="off")
            if media_prov:
                dif = litros * (media_prov - precio_uso)
                c3.metric(f"Con la media de {prov_origen}", euros(litros * media_prov + coste_elec),
                          f"{euros(abs(dif))} {'más' if dif > 0 else 'menos'} que tu elección",
                          delta_color="off")
            if precio_marca:
                c4.metric(f"Repostando en {marca_cmp}", euros(litros * precio_marca + coste_elec),
                          f"{num(precio_marca, 3)} €/L", delta_color="off")
            st.caption(
                f"Media de las {len(cands)} gasolineras de la ruta: {num(media_corr, 3)} €/L "
                f"({euros(litros * media_corr + coste_elec)}). "
                + (f"Tramo eléctrico: {km_elec:.0f} km, {num(kwh_elec, 1)} kWh, {euros(coste_elec)}. "
                   if tipo == "phev" else "")
                + "El combustible que ya llevas se valora al precio de reposición.")

            # -------- mapa y listados
            cargs = pd.DataFrame()
            if tipo == "phev":
                cargs, fuente_c, err_c = obtener_cargadores(ruta, desvio)
            mapa(ruta, origen, destino, cands, col, plan["paradas"], cargadores=cargs)
            t1, t2, t3 = st.tabs(["💰 Más baratas en la ruta", "🏷️ Por marca", "📋 Todas"])
            with t1:
                tabla_estaciones(cands.nsmallest(20, col), col)
            with t2:
                st.dataframe(planner.resumen_marcas(cands, col), hide_index=True,
                             width="stretch",
                             column_config={"Más barata (€/L)": st.column_config.NumberColumn(format="%.3f"),
                                            "Media (€/L)": st.column_config.NumberColumn(format="%.3f")})
                sel = st.multiselect("Ver gasolineras de", marcas,
                                     default=[marca] if marca else marcas[:1], key="vj_marcas_sel")
                tabla_estaciones(cands[cands["marca"].isin(sel)].sort_values("km_ruta"), col)
            with t3:
                tabla_estaciones(cands.sort_values("km_ruta"), col)
            if tipo == "phev":
                st.markdown("##### ⚡ Puntos de carga en la ruta")
                if cargs.empty:
                    st.info(err_c or "Sin puntos de carga en la ruta.")
                else:
                    st.caption(f"Fuente: {fuente_c} · {len(cargs)} puntos a ≤ {num(desvio, 1)} km.")
                    tabla_cargadores(cargs.sort_values("km_ruta"))
        if tipo == "hev":
            st.caption("Híbrido convencional: se recarga solo, así que el coste depende únicamente del "
                       "combustible (el consumo de referencia ya incluye el ahorro híbrido).")

    # ---------- eléctrico puro
    if tipo == "ev":
        st.markdown("##### ⚡ Recarga en tu ruta")
        with st.spinner("Buscando puntos de carga en la ruta…"):
            cargs, fuente_c, err_c = obtener_cargadores(ruta, desvio)
        aut_actual_ev = veh["bateria"] * soc / 100 * 100 / veh["consumo_kwh"]
        aut_llena_ev = veh["bateria"] * carga_hasta / 100 * 100 / veh["consumo_kwh"]
        st.caption(f"Autonomía ahora: ~{aut_actual_ev:.0f} km · cargando al {carga_hasta} %: "
                   f"~{aut_llena_ev:.0f} km.")
        cand_c = cargs
        if solo_rapida and not cargs.empty:
            cand_c = cargs[cargs["potencia_kw"].fillna(0) >= 50]
        plan_ev = planner.planificar_paradas(cand_c, L, aut_actual_ev, aut_llena_ev, margen_pct,
                                             margen_min, modo="lejana")
        if err_c and cargs.empty:
            st.warning(f"{err_c}. El coste se calcula igualmente.")
        else:
            st.caption(f"Fuente: {fuente_c} · {len(cargs)} puntos de carga a ≤ {num(desvio, 1)} km de la ruta.")
        if not cargs.empty:
            for a in plan_ev["avisos"]:
                st.warning(a)
            if not plan_ev["paradas"]:
                st.success("Llegas sin recargar por el camino.")
            else:
                st.markdown(f"**Te recomiendo {len(plan_ev['paradas'])} recarga(s):**")
                for i, p in enumerate(plan_ev["paradas"], 1):
                    tarjeta_recarga(i, p, veh["consumo_kwh"], p_pub)

        kwh = L * veh["consumo_kwh"] / 100
        kwh_casa = min(kwh, veh["bateria"] * soc / 100)
        kwh_pub = max(kwh - kwh_casa, 0)
        st.markdown("##### 💶 Coste del viaje")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Coste estimado", euros(kwh_casa * p_casa + kwh_pub * p_pub),
                  help="La batería con la que sales, a precio de casa; el resto, en cargador público.")
        c2.metric("Energía", f"{num(kwh, 1)} kWh", f"{num(kwh_pub, 1)} kWh en ruta", delta_color="off")
        c3.metric("Todo a precio de casa", euros(kwh * p_casa))
        c4.metric("Todo en cargador público", euros(kwh * p_pub))
        if not estaciones.empty:
            ref = planner.puntos_en_ruta(estaciones, ruta, desvio, columna_precio="Gasolina 95")
            if not ref.empty:
                l_ref = L * 6.0 / 100
                st.caption(f"Comparativa: un coche de gasolina de 6 L/100 km gastaría ~"
                           f"{euros(l_ref * ref['Gasolina 95'].mean())} en este viaje "
                           f"(media de la ruta {num(ref['Gasolina 95'].mean(), 3)} €/L).")
        mapa(ruta, origen, destino, cargadores=cargs, paradas_carga=plan_ev["paradas"])
        if not cargs.empty:
            with st.expander(f"📋 Todos los puntos de carga de la ruta ({len(cargs)})"):
                tabla_cargadores(cargs.sort_values("km_ruta"))


# ============================================================ MODO CASA-TRABAJO
def generar_historico_y_proyeccion(brent_df, fecha_inicio, fecha_fin, precio_actual):
    if brent_df.empty:
        fechas = pd.date_range(start=fecha_inicio, end=datetime.now().date(), freq="D")
        brent_df = pd.DataFrame({"Fecha": fechas, "Precio_Brent": 75.0})
    brent_df = brent_df.copy()
    brent_df["Precio_Brent"] = pd.to_numeric(brent_df["Precio_Brent"], errors="coerce").ffill().fillna(75.0)
    # completa los días sin cotización (fines de semana)
    brent_df = (brent_df.set_index("Fecha").resample("D").ffill().reset_index())
    brent_reciente = float(brent_df["Precio_Brent"].iloc[-1])
    ratio = precio_actual / brent_reciente if brent_reciente > 0 else 0.02
    hist = brent_df.assign(Precio_Combustible=brent_df["Precio_Brent"] * ratio, Tipo="Histórico")
    ultima = pd.to_datetime(hist["Fecha"].iloc[-1]).date()
    dias = (fecha_fin - ultima).days
    if dias > 0:
        fut = pd.DataFrame({
            "Fecha": [pd.Timestamp(ultima + timedelta(days=i)) for i in range(1, dias + 1)],
            "Precio_Brent": brent_reciente, "Precio_Combustible": precio_actual, "Tipo": "Proyección"})
        hist = pd.concat([hist, fut], ignore_index=True)
    f = pd.to_datetime(hist["Fecha"]).dt.date
    return hist[(f >= fecha_inicio) & (f <= fecha_fin)].reset_index(drop=True)


def enviar_informe_email(destinatario, r):
    smtp_server = secreto("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(secreto("SMTP_PORT", 587))
    sender_email = secreto("SENDER_EMAIL", "")
    sender_password = secreto("SENDER_PASSWORD", "")
    if not sender_email or not sender_password:
        return False, ("Faltan credenciales SMTP. Configura SENDER_EMAIL y SENDER_PASSWORD en los "
                       "Secrets de Streamlit.")
    e = {k: html.escape(str(v)) if isinstance(v, str) else v for k, v in r.items()}
    cuerpo = f"""
    <html><body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
      <h2 style="color: #1f77b4;">📊 Resumen de tu informe de desplazamientos</h2>
      <h3>📍 Trayecto</h3><ul>
        <li><b>Origen:</b> {e['origen']}</li><li><b>Destino:</b> {e['destino']}</li>
        <li><b>Distancia por trayecto:</b> {num(e['distancia_km'], 1)} km</li>
        <li><b>Distancia diaria (ida y vuelta):</b> {num(e['distancia_diaria'], 1)} km</li>
        <li><b>Días por semana:</b> {e['dias_semana']}</li></ul>
      <h3>🚗 Vehículo</h3><ul>
        <li><b>Vehículo:</b> {e['vehiculo']}</li>
        <li><b>Energía:</b> {e['tipo_combustible']}</li>
        <li><b>Consumo:</b> {e['consumo']} {e['unidad_consumo']}</li>
        <li><b>Precio de referencia:</b> {num(e['precio_ref'], 3)} {e['unidad_precio']} ({e['origen_precio']})</li></ul>
      <h3>💰 Costes</h3>
      <p><b>Gasto total en el periodo:</b> <span style="font-size:18px;color:#d9534f">
      <b>{num(e['gasto_total'], 2)} €</b></span><br>
      <b>Consumo total:</b> {num(e['consumo_total'], 1)} {e['unidad_totales']}</p>
      <h3>🧾 Impuestos (estimación)</h3><ul>
        <li>Base energía/carburante: {num(e['base'], 2)} €</li>
        <li>{e['nombre_impuesto']}: {num(e['impuesto_esp'], 2)} €</li><li>IVA (21 %): {num(e['iva'], 2)} €</li></ul>
      <p style="font-size:12px;color:#777">Generado con
      <a       <a href="https://navsiq.streamlit.app/">navsiq.streamlit.app</a></p>
    </body></html>"""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "📊 Informe de consumo y proyección de desplazamientos"
        msg["From"] = sender_email
        msg["To"] = destinatario
        msg.attach(MIMEText(cuerpo, "html"))
        with smtplib.SMTP(smtp_server, smtp_port, timeout=20) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, destinatario, msg.as_string())
        return True, "¡Informe enviado a tu correo!"
    except Exception as exc:  # noqa: BLE001
        return False, f"No se pudo enviar el correo: {exc}"


def modo_casa_trabajo():
    st.subheader("🏠 Tu trayecto diario")
    provs = sorted(data.PROVINCIAS)
    prov = selectbox_filtrable("Provincia de referencia para la media de precios", provs,
                               key="ct_prov", index=provs.index("Madrid"),
                               placeholder="Escribe la provincia…")
    id_prov = data.PROVINCIAS[prov]
    est_ct = estaciones
    if origen_precios == "snapshot" and not estaciones.empty:
        est_ct, f_prov, n_prov = data.actualizar_provincias(estaciones, [id_prov])
        if n_prov:
            st.caption(f"🔄 Precios de {prov} actualizados en directo ({f_prov}).")
    brent = data.historico_brent(10)
    c1, c2, c3 = st.columns(3)
    if len(brent) >= 2:
        c1.metric("Petróleo Brent ($/barril)", f"{num(brent['Precio_Brent'].iloc[-1], 2)} $",
                  f"{num(brent['Precio_Brent'].iloc[-1] - brent['Precio_Brent'].iloc[-2], 2)} $")
    else:
        c1.metric("Petróleo Brent ($/barril)", "s/d")
    g95 = data.media_provincial(est_ct, id_prov, "Gasolina 95")
    dsl = data.media_provincial(est_ct, id_prov, "Diésel")
    c2.metric(f"Media gasolina 95 ({prov})", f"{num(g95, 3)} €/L" if g95 else "s/d")
    c3.metric(f"Media diésel ({prov})", f"{num(dsl, 3)} €/L" if dsl else "s/d")

    st.divider()
    c_veh, c_ruta = st.columns(2, gap="large")
    with c_veh:
        veh = panel_vehiculo("ct")
    if not veh:
        st.info("Selecciona un modelo de vehículo para continuar.")
        return
    with c_ruta:
        origen = selector_lugar("🏠 Origen (casa)", "ct_origen", "Ej.: Calle Mayor 1, Madrid")
        destino = selector_lugar("🏢 Destino (trabajo)", "ct_destino", "Ej.: Gran Vía 30, Madrid")
    hoy = datetime.now(data.TZ).date()
    c1, c2, c3 = st.columns(3)
    dias_semana = c1.slider("Días de ida y vuelta por semana", 1, 7, 5, key="ct_dias")
    rango = c2.date_input("Periodo (histórico + proyección)",
                          value=(hoy - relativedelta(years=1), datetime(hoy.year, 12, 31).date()),
                          min_value=hoy - relativedelta(years=1), max_value=hoy + relativedelta(years=2),
                          key="ct_rango")
    desvio = c3.slider("Gasolineras a menos de (km) de tu trayecto", 1.0, 10.0, 3.0, 0.5, key="ct_desvio")

    if st.button("📈 Generar informe", type="primary", width="stretch", key="ct_calc"):
        if not isinstance(rango, (tuple, list)) or len(rango) != 2:
            st.error("Selecciona fecha de inicio y de fin.")
        elif not origen or not destino:
            st.error("Escribe y confirma el origen y el destino.")
        else:
            with st.spinner("Calculando ruta…"):
                ruta = data.calcular_ruta(origen["lon"], origen["lat"], destino["lon"], destino["lat"])
            if not ruta:
                st.error("No se pudo trazar la ruta. Prueba con direcciones más concretas.")
            else:
                st.session_state["trayecto"] = {"origen": origen, "destino": destino, "ruta": ruta,
                                                "rango": tuple(rango)}
    tr = st.session_state.get("trayecto")
    if not tr:
        st.info("Completa vehículo, origen y destino y pulsa **Generar informe**.")
        return
    origen, destino, ruta = tr["origen"], tr["destino"], tr["ruta"]
    fecha_inicio, fecha_fin = tr["rango"]
    km = ruta["distancia_km"]
    km_dia = km * 2

    es_ev = veh["tipo"] == "ev"
    es_phev = veh["tipo"] == "phev"
    st.divider()
    st.markdown(f"#### Trayecto: {num(km, 1)} km · {num(km_dia, 1)} km/día (ida y vuelta) · "
                f"~{ruta['duracion_min']:.0f} min por trayecto")

    cercanas = pd.DataFrame()
    if es_ev:
        p_casa, p_pub = precio_luz_panel("ct")
        mix = st.slider("% de recargas en cargador público", 0, 100, 0, 5, key="ct_mix")
        precio = p_casa * (1 - mix / 100) + p_pub * mix / 100
        origen_precio = "luz de casa (PVPC + impuestos)" if mix == 0 else f"mezcla casa/público ({mix} %)"
        consumo, unidad, etiqueta = veh["consumo_kwh"], "kWh", "Eléctrico"
    else:
        col = veh["combustible"]
        media = data.media_provincial(est_ct, id_prov, col)
        if not est_ct.empty:
            cercanas = planner.puntos_en_ruta(est_ct, ruta, desvio, columna_precio=col)
        opciones = []
        if not cercanas.empty:
            top = cercanas.nsmallest(30, col)
            opciones = [f"{r['marca']} · {r['municipio']} · {num(r[col], 3)} €/L" for _, r in top.iterrows()]
        etiquetas = (["Gasolinera más barata de tu trayecto"] if opciones else []) + \
                    ([f"Media provincial ({prov})"] if media else []) + opciones
        if not etiquetas:
            st.error("No hay precios disponibles para ese combustible.")
            return
        elegido = st.selectbox("Precio para calcular el gasto", etiquetas, key="ct_precio")
        if elegido.startswith("Gasolinera más barata"):
            fila = cercanas.nsmallest(1, col).iloc[0]
            precio, origen_precio = fila[col], f"{fila['marca']} · {fila['municipio']}"
        elif elegido.startswith("Media provincial"):
            precio, origen_precio = media, f"media de {prov}"
        else:
            fila = cercanas.nsmallest(30, col).iloc[opciones.index(elegido)]
            precio, origen_precio = fila[col], f"{fila['marca']} · {fila['municipio']}"
        consumo, unidad, etiqueta = veh["consumo_l"], "L", col
        if es_phev:
            km_elec_dia = min(km_dia, veh["bateria"] * 100 / veh["consumo_kwh"])
            p_casa, _ = precio_luz_panel("ct")
            st.caption(f"Híbrido enchufable: si cargas en casa cada día, ~{km_elec_dia:.0f} km diarios "
                       f"son eléctricos (~{euros(km_elec_dia * veh['consumo_kwh'] / 100 * p_casa)}/día) y el "
                       "resto con combustible.")
        if media and precio:
            dif = (media - precio) * km_dia * consumo / 100 * dias_semana * 52 / 12
            st.caption(f"Precio elegido: **{num(precio, 3)} €/L** ({origen_precio}). Media provincial: "
                       f"{num(media, 3)} €/L → diferencia ~{euros(abs(dif))}/mes "
                       f"{'a tu favor' if dif > 0 else 'en contra'}.")

    km_comb_dia = km_dia
    coste_elec_dia = 0.0
    if es_phev:
        km_comb_dia = max(km_dia - km_elec_dia, 0)
        coste_elec_dia = km_elec_dia * veh["consumo_kwh"] / 100 * p_casa

    brent_hist = data.historico_brent((hoy - fecha_inicio).days + 30)
    df = generar_historico_y_proyeccion(brent_hist, fecha_inicio, fecha_fin, precio)
    df["Unidades_Diarias"] = km_comb_dia / 100.0 * consumo
    df["Es_Dia_Trabajo"] = pd.to_datetime(df["Fecha"]).dt.dayofweek < dias_semana
    df["Gasto_Diario"] = 0.0
    df.loc[df["Es_Dia_Trabajo"], "Gasto_Diario"] = (df["Unidades_Diarias"] * df["Precio_Combustible"]
                                                    + coste_elec_dia)
    df["Fecha"] = pd.to_datetime(df["Fecha"])
    mensual = (df.groupby([pd.Grouper(key="Fecha", freq="MS"), "Tipo"])
                 .agg(Gasto_Mensual=("Gasto_Diario", "sum"), Brent_Medio=("Precio_Brent", "mean"))
                 .reset_index())
    mensual["Mes"] = mensual["Fecha"].dt.strftime("%m/%Y")

    total = df["Gasto_Diario"].sum()
    unidades = df.loc[df["Es_Dia_Trabajo"], "Unidades_Diarias"].sum()
    futuro = df[df["Fecha"].dt.date >= hoy]["Gasto_Diario"].sum()
    gasto_dia = km_comb_dia / 100 * consumo * precio + coste_elec_dia
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Por día laborable", euros(gasto_dia))
    c2.metric("Al mes (aprox.)", euros(gasto_dia * dias_semana * 52 / 12))
    c3.metric("Total del periodo", euros(total))
    c4.metric("Desde hoy hasta el final", euros(futuro))

    t1, t2, t3 = st.tabs(["💰 Gasto mensual", "🛢️ Precio vs Brent", "🗺️ Mapa y gasolineras"])
    with t1:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        for tipo_g, color in (("Histórico", "#1f77b4"), ("Proyección", "#ff7f0e")):
            sub = mensual[mensual["Tipo"] == tipo_g]
            if not sub.empty:
                fig.add_trace(go.Bar(x=sub["Mes"], y=sub["Gasto_Mensual"], name=f"Gasto ({tipo_g})",
                                     marker_color=color), secondary_y=False)
        linea = mensual.groupby("Mes", sort=False)["Brent_Medio"].mean().reset_index()
        fig.add_trace(go.Scatter(x=linea["Mes"], y=linea["Brent_Medio"], name="Brent medio ($)",
                                 mode="lines+markers", line=dict(color="red", width=2.5)),
                      secondary_y=True)
        fig.update_layout(barmode="stack", hovermode="x unified", margin=dict(l=10, r=10, t=40, b=10),
                          title="Gasto mensual y Brent medio", legend=dict(orientation="h"))
        fig.update_yaxes(title_text="€", secondary_y=False)
        fig.update_yaxes(title_text="Brent ($)", secondary_y=True)
        st.plotly_chart(fig, width="stretch")

        st.markdown("##### 🧾 Desglose estimado: impuestos vs energía")
        base, imp, iva = desglose_impuestos(total, unidades, "Eléctrico" if es_ev else etiqueta)
        nombre_imp = "Imp. electricidad (IEE)" if es_ev else "Imp. hidrocarburos (IEAH)"
        desg = pd.DataFrame({"Concepto": ["Base energía / carburante", nombre_imp, "IVA (21 %)"],
                             "Importe (€)": [base, imp, iva]})
        desg["%"] = desg["Importe (€)"] / total * 100 if total else 0
        d1, d2 = st.columns(2)
        d1.write(f"**Gasto analizado:** {euros(total)} ({num(unidades, 1)} {unidad})")
        d1.dataframe(desg, hide_index=True, width="stretch",
                     column_config={"Importe (€)": st.column_config.NumberColumn(format="%.2f €"),
                                    "%": st.column_config.NumberColumn(format="%.1f %%")})
        d2.plotly_chart(px.pie(desg, values="Importe (€)", names="Concepto", hole=.35,
                               color_discrete_sequence=["#2ca02c", "#d62728", "#ff7f0e"]),
                        width="stretch")

        st.markdown("##### 📧 Recibir el informe por email")
        with st.form("form_email"):
            correo = st.text_input("Tu correo electrónico")
            if st.form_submit_button("Enviar informe"):
                if not correo or "@" not in correo:
                    st.error("Introduce un correo válido.")
                else:
                    ok, msg = enviar_informe_email(correo, {
                        "origen": origen["nombre"], "destino": destino["nombre"], "distancia_km": km,
                        "distancia_diaria": km_dia, "dias_semana": dias_semana, "vehiculo": veh["modelo"],
                        "tipo_combustible": etiqueta, "consumo": consumo,
                        "unidad_consumo": "kWh/100 km" if es_ev else "L/100 km", "precio_ref": precio,
                        "unidad_precio": "€/kWh" if es_ev else "€/L", "origen_precio": origen_precio,
                        "gasto_total": total, "consumo_total": unidades, "unidad_totales": unidad,
                        "base": base, "impuesto_esp": imp, "nombre_impuesto": nombre_imp, "iva": iva})
                    (st.success if ok else st.warning)(msg)
    with t2:
        fig2 = make_subplots(specs=[[{"secondary_y": True}]])
        fig2.add_trace(go.Scatter(x=df["Fecha"], y=df["Precio_Combustible"],
                                  name=f"{etiqueta} (€/{unidad})", line=dict(color="#1f77b4")),
                       secondary_y=False)
        fig2.add_trace(go.Scatter(x=df["Fecha"], y=df["Precio_Brent"], name="Brent ($/barril)",
                                  line=dict(color="red", dash="dot")), secondary_y=True)
        fig2.add_vline(x=pd.Timestamp(hoy), line_dash="dash", line_color="green")
        fig2.update_layout(hovermode="x unified", margin=dict(l=10, r=10, t=40, b=10),
                           title=f"{etiqueta}: histórico estimado y proyección", legend=dict(orientation="h"))
        st.plotly_chart(fig2, width="stretch")
        st.caption("El histórico del carburante se estima a partir del Brent; la proyección mantiene el "
                   "precio actual elegido.")
    with t3:
        if es_ev:
            cargs, fuente_c, err_c = obtener_cargadores(ruta, max(desvio, 2.0))
            mapa(ruta, origen, destino, cargadores=cargs)
            if not cargs.empty:
                st.caption(f"Fuente: {fuente_c}")
                tabla_cargadores(cargs.sort_values("km_ruta"))
            elif err_c:
                st.info(err_c)
        else:
            mapa(ruta, origen, destino, cercanas, col)
            tabla_estaciones(cercanas.nsmallest(20, col) if not cercanas.empty else cercanas, col)


if modo.endswith("Viajar"):
    modo_viajar()
else:
    modo_casa_trabajo()

st.divider()
st.markdown(
    """
**Fuentes de datos** · Precios de carburantes: servicio REST del *Ministerio para la Transición Ecológica
(MITECO)*, actualizado cada ~30 min · Rutas: *OSRM* sobre OpenStreetMap · Direcciones: *Nominatim* y
*Photon* (OpenStreetMap) · Luz: *PVPC 2.0TD* de *Red Eléctrica* (REData) · Puntos de carga: inventario
oficial *MITERD/DGT* (Punto de Acceso Nacional), *OpenStreetMap* (Overpass) y, si se configura,
*OpenChargeMap* · Brent: *Yahoo Finance* (`BZ=F`). Cuando un servidor oficial falla o bloquea
peticiones desde la nube, la app usa automáticamente una instantánea actualizada cada 30 min. Los
consumos son de referencia: ajústalos a tu coche.
"""
)


