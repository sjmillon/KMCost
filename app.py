from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import random
import smtplib

from dateutil.relativedelta import relativedelta
import geopy
from geopy.geocoders import Nominatim
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(
    page_title="Dashboard de Consumo y Precios", page_icon="⛽", layout="wide"
)

# Diccionario oficial de provincias e identificadores INE
PROVINCIAS = {
    "Álava": "01", "Albacete": "02", "Alicante": "03", "Almería": "04", "Ávila": "05",
    "Badajoz": "06", "Balears (Illes)": "07", "Barcelona": "08", "Burgos": "09", "Cáceres": "10",
    "Cádiz": "11", "Castellón": "12", "Ciudad Real": "13", "Córdoba": "14", "A Coruña": "15",
    "Cuenca": "16", "Girona": "17", "Granada": "18", "Guadalajara": "19", "Gipuzkoa": "20",
    "Huelva": "21", "Huesca": "22", "Jaén": "23", "León": "24", "Lleida": "25",
    "La Rioja": "26", "Lugo": "27", "Madrid": "28", "Málaga": "29", "Murcia": "30",
    "Navarra": "31", "Ourense": "32", "Asturias": "33", "Palencia": "34", "Las Palmas": "35",
    "Pontevedra": "36", "Salamanca": "37", "Santa Cruz de Tenerife": "38", "Cantabria": "39", "Segovia": "40",
    "Sevilla": "41", "Soria": "42", "Tarragona": "43", "Teruel": "44", "Toledo": "45",
    "Valencia": "46", "Valladolid": "47", "Bizkaia": "48", "Zamora": "49", "Zaragoza": "50",
    "Ceuta": "51", "Melilla": "52"
}

# --- 1. FUNCIONES DE EXTRACCIÓN Y DATOS ---

@st.cache_data(ttl=3600)
def obtener_precio_actual_combustibles(provincia_id="28"):
    fallback = {
        "Gasolina 95": 1.62,
        "Diésel": 1.51,
        "Gasolina 98": 1.78,
        "Diésel Premium": 1.60,
        "Eléctrico": 0.20
    }
    url = f"https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/EstacionesTerrestres/FiltroProvincia/{provincia_id}"
    try:
        response = requests.get(url, timeout=6)
        if response.status_code == 200:
            data = response.json()
            estaciones = data.get("ListaEESSPrecio", [])
            precios = {
                "Gasolina 95": [],
                "Diésel": [],
                "Gasolina 98": [],
                "Diésel Premium": [],
            }

            for est in estaciones:
                if est.get("Precio Gasolina 95 E5"):
                    precios["Gasolina 95"].append(
                        float(est["Precio Gasolina 95 E5"].replace(",", "."))
                    )
                if est.get("Precio Gasoleo A"):
                    precios["Diésel"].append(
                        float(est["Precio Gasoleo A"].replace(",", "."))
                    )
                if est.get("Precio Gasolina 98 E5"):
                    precios["Gasolina 98"].append(
                        float(est["Precio Gasolina 98 E5"].replace(",", "."))
                    )
                if est.get("Precio Gasoleo Premium"):
                    precios["Diésel Premium"].append(
                        float(est["Precio Gasoleo Premium"].replace(",", "."))
                    )

            medias = {
                k: (sum(v) / len(v) if v else fallback[k])
                for k, v in precios.items()
            }
            medias["Eléctrico"] = 0.20
            return medias
    except Exception:
        pass
    return fallback


@st.cache_data(ttl=86400)
def obtener_historico_brent(dias=365):
    for symbol in ["BZ=F", "BRNT"]:
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period=f"{dias}d")
            if not hist.empty and "Close" in hist.columns:
                df = hist[["Close"]].reset_index()
                df.columns = ["Fecha", "Precio_Brent"]
                df["Fecha"] = pd.to_datetime(df["Fecha"]).dt.tz_localize(None)
                df["Precio_Brent"] = df["Precio_Brent"].clip(lower=40.0, upper=110.0)
                return df
        except Exception:
            continue
    return pd.DataFrame()


def generar_historico_y_proyeccion(
    brent_df, fecha_inicio, fecha_fin, tipo_combustible, precio_actual
):
    hoy_date = datetime.now().date()

    if (
        brent_df.empty
        or "Fecha" not in brent_df.columns
        or "Precio_Brent" not in brent_df.columns
    ):
        fechas = pd.date_range(start=fecha_inicio, end=hoy_date, freq="D")
        brent_df = pd.DataFrame({"Fecha": fechas, "Precio_Brent": 75.0})
    else:
        brent_df = brent_df.copy()
        brent_df["Fecha"] = pd.to_datetime(brent_df["Fecha"]).dt.tz_localize(None)

    brent_df["Precio_Brent"] = pd.to_numeric(
        brent_df["Precio_Brent"], errors="coerce"
    ).fillna(75.0)

    brent_reciente = (
        float(brent_df["Precio_Brent"].iloc[-1])
        if len(brent_df) > 0
        else 75.0
    )
    ratio = (
        precio_actual / brent_reciente
        if (brent_reciente and brent_reciente > 0)
        else 0.02
    )

    historico = brent_df.copy()
    historico["Precio_Combustible"] = historico["Precio_Brent"] * ratio
    historico["Tipo"] = "Histórico"

    ultima_fecha_dt = pd.to_datetime(historico["Fecha"].iloc[-1]).date()
    dias_futuro = (fecha_fin - ultima_fecha_dt).days

    if dias_futuro > 0:
        fechas_futuras = [
            pd.Timestamp(ultima_fecha_dt + timedelta(days=i))
            for i in range(1, dias_futuro + 1)
        ]

        proyeccion = pd.DataFrame(
            {
                "Fecha": fechas_futuras,
                "Precio_Brent": brent_reciente,
                "Precio_Combustible": precio_actual,
                "Tipo": "Proyección",
            }
        )
        df_final = pd.concat([historico, proyeccion], ignore_index=True)
    else:
        df_final = historico

    df_final["Fecha_Date"] = pd.to_datetime(df_final["Fecha"]).dt.date
    df_final = df_final[
        (df_final["Fecha_Date"] >= fecha_inicio)
        & (df_final["Fecha_Date"] <= fecha_fin)
    ].drop(columns=["Fecha_Date"])
    return df_final


@st.cache_data(ttl=86400)
def obtener_coordenadas(direccion):
    if not direccion or len(direccion.strip()) < 3:
        return None
    geolocator = Nominatim(user_agent="calculadora_combustible_app_v9")
    try:
        query = (
            direccion
            if "españa" in direccion.lower() or "spain" in direccion.lower()
            else f"{direccion}, España"
        )
        ubicaciones = geolocator.geocode(
            query, exactly_one=False, limit=5, timeout=5
        )
        return ubicaciones
    except Exception:
        return None


@st.cache_data(ttl=86400)
def calcular_ruta_osrm(lon1, lat1, lon2, lat2):
    url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            respuesta = res.json()
            if respuesta.get("code") == "Ok" and respuesta.get("routes"):
                distancia_km = respuesta["routes"][0]["distance"] / 1000.0
                tiempo_minutos = respuesta["routes"][0]["duration"] / 60.0
                return distancia_km, tiempo_minutos
    except Exception:
        pass
    return None, None


def calcular_desglose_impuestos(coste_total, consumo_total_unidades, tipo_combustible):
    if tipo_combustible == "Eléctrico":
        # IVA 21% e Impuesto Especial sobre la Electricidad (IEE ~5.11%)
        iva = coste_total - (coste_total / 1.21)
        base_mas_iee = coste_total / 1.21
        iee = base_mas_iee - (base_mas_iee / 1.0511)
        base_energia = max(0.0, base_mas_iee - iee)
        return base_energia, iee, iva
    else:
        iva = coste_total - (coste_total / 1.21)
        if "Diésel" in tipo_combustible:
            ieah_por_litro = 0.379
        else:
            ieah_por_litro = 0.472
            
        ieah_total = min(consumo_total_unidades * ieah_por_litro, coste_total - iva)
        base_materia_prima = max(0.0, coste_total - iva - ieah_total)
        return base_materia_prima, ieah_total, iva


def enviar_informe_email(destinatario, resumen_dict):
    smtp_server = st.secrets.get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(st.secrets.get("SMTP_PORT", 587))
    sender_email = st.secrets.get("SENDER_EMAIL", "")
    sender_password = st.secrets.get("SENDER_PASSWORD", "")

    if not sender_email or not sender_password:
        return False, "Faltan credenciales SMTP. Configura SENDER_EMAIL y SENDER_PASSWORD en los Secrets de Streamlit."

    asunto = "📊 Informe de Consumo y Proyección de Desplazamientos"
    
    cuerpo_html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
        <h2 style="color: #1f77b4;">📊 Resumen de tu Informe de Desplazamientos</h2>
        <hr style="border: 0; border-top: 1px solid #ccc;"/>
        <h3>📍 Datos del Trayecto</h3>
        <ul>
          <li><b>Origen:</b> {resumen_dict['origen']}</li>
          <li><b>Destino:</b> {resumen_dict['destino']}</li>
          <li><b>Distancia por trayecto:</b> {resumen_dict['distancia_km']:.1f} km</li>
          <li><b>Distancia diaria (ida y vuelta):</b> {resumen_dict['distancia_diaria']:.1f} km</li>
          <li><b>Días de desplazamiento semanal:</b> {resumen_dict['dias_semana']} días</li>
        </ul>

        <h3>🚗 Vehículo y Consumo</h3>
        <ul>
          <li><b>Tipo de Energía/Combustible:</b> {resumen_dict['tipo_combustible']}</li>
          <li><b>Consumo medio:</b> {resumen_dict['consumo']} {resumen_dict['unidad_consumo']}</li>
          <li><b>Precio de referencia:</b> {resumen_dict['precio_ref']:.3f} {resumen_dict['unidad_precio']}</li>
        </ul>

        <h3>💰 Proyección de Costes</h3>
        <div style="background-color: #f4f4f4; padding: 15px; border-radius: 5px;">
          <p style="margin: 0;"><b>Gasto total acumulado en el periodo:</b> <span style="font-size: 18px; color: #d9534f;"><b>{resumen_dict['gasto_total']:.2f} €</b></span></p>
          <p style="margin: 5px 0 0 0;"><b>Consumo total estimado:</b> {resumen_dict['consumo_total']:.1f} {resumen_dict['unidad_totales']}</p>
        </div>

        <h3>🧾 Desglose Estimado de Impuestos</h3>
        <table style="width: 100%; border-collapse: collapse; margin-top: 10px;">
          <tr style="background-color: #eee;">
            <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">Concepto</th>
            <th style="padding: 8px; border: 1px solid #ddd; text-align: right;">Importe</th>
          </tr>
          <tr>
            <td style="padding: 8px; border: 1px solid #ddd;">Base Carburante / Energía</td>
            <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">{resumen_dict['base']:.2f} €</td>
          </tr>
          <tr>
            <td style="padding: 8px; border: 1px solid #ddd;">Impuesto Especial ({resumen_dict['nombre_impuesto']})</td>
            <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">{resumen_dict['impuesto_esp']:.2f} €</td>
          </tr>
          <tr>
            <td style="padding: 8px; border: 1px solid #ddd;">IVA (21%)</td>
            <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">{resumen_dict['iva']:.2f} €</td>
          </tr>
        </table>
        <br/>
        <p style="font-size: 12px; color: #777;">Generado automáticamente desde <a href="https://kmcost.streamlit.app/">kmcost.streamlit.app</a></p>
      </body>
    </html>
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = asunto
        msg["From"] = sender_email
        msg["To"] = destinatario
        msg.attach(MIMEText(cuerpo_html, "html"))

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, destinatario, msg.as_string())
        return True, "¡Informe enviado con éxito a tu correo electrónico!"
    except Exception as e:
        return False, f"No se pudo enviar el correo: {str(e)}"


# --- 2. INTERFAZ DE USUARIO ---

st.title("📊 Dashboard de Consumo y Proyección de Combustible")

# Panel de Mercado
st.header("1. Mercado Actual: Gasolina vs Brent")

lista_provincias = sorted(PROVINCIAS.keys())
provincia_seleccionada = st.selectbox(
    "📍 Selecciona la provincia de referencia para los precios:",
    lista_provincias,
    index=lista_provincias.index("Madrid")
)
provincia_id = PROVINCIAS[provincia_seleccionada]

precios_actuales = obtener_precio_actual_combustibles(provincia_id)
brent_df = obtener_historico_brent(10)

col1, col2, col3 = st.columns(3)
if (
    not brent_df.empty
    and "Precio_Brent" in brent_df.columns
    and len(brent_df) >= 2
):
    brent_hoy = float(brent_df["Precio_Brent"].iloc[-1])
    brent_ayer = float(brent_df["Precio_Brent"].iloc[-2])
    diff_brent = brent_hoy - brent_ayer
    col1.metric(
        "Petróleo Brent ($/barril)", f"${brent_hoy:.2f}", f"{diff_brent:.2f} $"
    )
else:
    col1.metric("Petróleo Brent ($/barril)", "$75.00", "0.00 $")

col2.metric(
    f"Media Gasolina 95 ({provincia_seleccionada})",
    f"{precios_actuales.get('Gasolina 95', 1.62):.3f} €/L",
)
col3.metric(
    f"Media Diésel ({provincia_seleccionada})",
    f"{precios_actuales.get('Diésel', 1.51):.3f} €/L",
)

st.divider()

# Configuración de Trayecto
st.header("2. Tus Desplazamientos")
col_vehiculo, col_ruta = st.columns(2)

with col_vehiculo:
    st.subheader("🚗 Vehículo")
    tipo_combustible = st.selectbox(
        "Tipo de combustible / Energía",
        ["Gasolina 95", "Diésel", "Gasolina 98", "Diésel Premium", "Eléctrico"],
    )

    if tipo_combustible == "Eléctrico":
        consumo = st.number_input(
            "Consumo medio (kWh/100km)", min_value=1.0, value=18.0, step=0.5
        )
        precio_electrico_input = st.number_input(
            "Precio estimado de recarga (€/kWh)", min_value=0.01, value=0.20, step=0.01
        )
        precios_actuales["Eléctrico"] = precio_electrico_input
    else:
        consumo = st.number_input(
            "Consumo medio (L/100km)", min_value=1.0, value=6.5, step=0.1
        )

with col_ruta:
    st.subheader("🗺️ Ruta")

    origen_query = st.text_input(
        "🏠 Escribe tu calle de Origen (Ej: Calle Mayor, Madrid)"
    )
    origen_seleccionado = None
    if origen_query:
        opciones_origen = obtener_coordenadas(origen_query)
        if opciones_origen:
            nombres_origen = [loc.address for loc in opciones_origen]
            seleccion_org = st.selectbox(
                "Confirma tu origen exacto:", nombres_origen, key="org"
            )
            origen_seleccionado = next(
                (
                    loc
                    for loc in opciones_origen
                    if loc.address == seleccion_org
                ),
                None,
            )
        else:
            st.warning("Dirección no encontrada. Añade ciudad o código postal.")

    destino_query = st.text_input(
        "🏢 Escribe tu calle de Destino (Ej: Gran Vía, Madrid)"
    )
    destino_seleccionado = None
    if destino_query:
        opciones_destino = obtener_coordenadas(destino_query)
        if opciones_destino:
            nombres_destino = [loc.address for loc in opciones_destino]
            seleccion_dest = st.selectbox(
                "Confirma tu destino exacto:", nombres_destino, key="dest"
            )
            destino_seleccionado = next(
                (
                    loc
                    for loc in opciones_destino
                    if loc.address == seleccion_dest
                ),
                None,
            )
        else:
            st.warning("Dirección no encontrada. Añade ciudad o código postal.")

st.divider()

# Planificación y Rango
st.header("3. Histórico y Proyecciones")
col_plan1, col_plan2 = st.columns(2)
hoy = datetime.now().date()
hace_un_ano = hoy - relativedelta(years=1)
fin_de_ano = datetime(hoy.year, 12, 31).date()

with col_plan1:
    dias_por_semana = st.slider("Días de ida y vuelta a la semana", 1, 7, 5)
    rango_fechas = st.date_input(
        "Periodo a analizar (Histórico + Proyección)",
        value=(hace_un_ano, fin_de_ano),
        min_value=hace_un_ano,
        max_value=hoy + relativedelta(years=2),
    )

if st.button(
    "📈 Generar Informe y Proyección", type="primary", use_container_width=True
):
    if (
        not isinstance(rango_fechas, (tuple, list))
        or len(rango_fechas) != 2
    ):
        st.error(
            "Por favor, selecciona un rango completo en el calendario (fecha de inicio y fecha de fin)."
        )
    elif not origen_seleccionado or not destino_seleccionado:
        st.error(
            "Debes confirmar el origen y destino seleccionándolos en las listas desplegables superiores."
        )
    else:
        fecha_inicio, fecha_fin = rango_fechas

        with st.spinner("Calculando ruta y procesando datos de mercado..."):
            distancia_km, tiempo_min = calcular_ruta_osrm(
                origen_seleccionado.longitude,
                origen_seleccionado.latitude,
                destino_seleccionado.longitude,
                destino_seleccionado.latitude,
            )

            if distancia_km is None:
                st.error(
                    "No se pudo trazar la ruta entre los puntos seleccionados. Intenta elegir direcciones más específicas."
                )
            else:
                distancia_diaria = distancia_km * 2.0
                dias_historico = (hoy - fecha_inicio).days + 30
                df_brent_historico = obtener_historico_brent(dias_historico)
                precio_actual = precios_actuales.get(tipo_combustible, 1.65)

                df_precios = generar_historico_y_proyeccion(
                    df_brent_historico,
                    fecha_inicio,
                    fecha_fin,
                    tipo_combustible,
                    precio_actual,
                )

                df_precios["Unidades_Diarias"] = (
                    distancia_diaria / 100.0
                ) * consumo
                df_precios["Es_Dia_Trabajo"] = (
                    df_precios["Fecha"].dt.dayofweek < dias_por_semana
                )
                df_precios["Gasto_Diario"] = 0.0
                df_precios.loc[
                    df_precios["Es_Dia_Trabajo"], "Gasto_Diario"
                ] = (
                    df_precios["Unidades_Diarias"]
                    * df_precios["Precio_Combustible"]
                )

                df_mensual = (
                    df_precios.groupby(
                        [pd.Grouper(key="Fecha", freq="MS"), "Tipo"]
                    )
                    .agg(
                        Gasto_Mensual=("Gasto_Diario", "sum"),
                        Brent_Medio=("Precio_Brent", "mean"),
                    )
                    .reset_index()
                )

                df_mensual["Mes_Texto"] = df_mensual["Fecha"].dt.strftime("%b %Y")

                st.subheader(
                    f"Resumen de Ruta: {distancia_km:.1f} km (Trayecto) | {distancia_diaria:.1f} km/día (Ida y Vuelta)"
                )

                tab1, tab2 = st.tabs(
                    [
                        "💰 Gasto Mensual (Histórico y Proyección)",
                        "🛢️ Evolución de Precios",
                    ]
                )

                with tab1:
                    fig_gasto = make_subplots(specs=[[{"secondary_y": True}]])

                    for tipo in df_mensual["Tipo"].unique():
                        df_sub = df_mensual[df_mensual["Tipo"] == tipo]
                        fig_gasto.add_trace(
                            go.Bar(
                                x=df_sub["Mes_Texto"],
                                y=df_sub["Gasto_Mensual"],
                                name=f"Gasto ({tipo})",
                                marker_color="#1f77b4" if tipo == "Histórico" else "#ff7f0e",
                            ),
                            secondary_y=False,
                        )

                    df_brent_linea = df_mensual.groupby("Mes_Texto", sort=False)["Brent_Medio"].mean().reset_index()

                    fig_gasto.add_trace(
                        go.Scatter(
                            x=df_brent_linea["Mes_Texto"],
                            y=df_brent_linea["Brent_Medio"],
                            name="Brent Medio ($/barril)",
                            mode="lines+markers",
                            line=dict(color="red", width=2.5),
                        ),
                        secondary_y=True,
                    )

                    fig_gasto.update_layout(
                        title="Gasto Total Mensual (Barras Apiladas = Total Mes) y Brent Medio",
                        hovermode="x unified",
                        barmode="stack",
                    )
                    fig_gasto.update_yaxes(title_text="Gasto Total (€)", secondary_y=False)
                    fig_gasto.update_yaxes(title_text="Precio Brent Medio ($)", secondary_y=True)

                    st.plotly_chart(fig_gasto, use_container_width=True)

                    df_periodo = df_precios[
                        (df_precios["Fecha"].dt.date >= fecha_inicio)
                        & (df_precios["Fecha"].dt.date <= fecha_fin)
                    ]
                    gasto_total_periodo = df_periodo["Gasto_Diario"].sum()
                    unidades_totales_periodo = (
                        df_periodo[df_periodo["Es_Dia_Trabajo"]]["Unidades_Diarias"].sum()
                    )

                    gasto_futuro = df_precios[
                        (df_precios["Fecha"].dt.date >= hoy)
                        & (df_precios["Fecha"].dt.date <= fecha_fin)
                    ]["Gasto_Diario"].sum()

                    st.info(
                        f"**Resumen de gasto:** Gasto acumulado total en el periodo seleccionado: **{gasto_total_periodo:.2f} €** (Proyección restante desde hoy: **{gasto_futuro:.2f} €**)."
                    )

                    st.divider()
                    st.subheader("🧾 Desglose Estimado del Gasto: Impuestos vs Energía")
                    
                    base, imp_esp, iva = calcular_desglose_impuestos(
                        gasto_total_periodo, unidades_totales_periodo, tipo_combustible
                    )

                    col_d1, col_d2 = st.columns([1, 1])
                    
                    nombre_imp_esp = "Imp. Electricidad (IEE)" if tipo_combustible == "Eléctrico" else "Imp. Hidrocarburos (IEAH)"
                    unidad_label = "kWh" if tipo_combustible == "Eléctrico" else "Litros"

                    with col_d1:
                        st.write(f"**Gasto Total Analizado:** {gasto_total_periodo:.2f} € ({unidades_totales_periodo:.1f} {unidad_label})")
                        
                        df_desglose = pd.DataFrame({
                            "Concepto": ["Base Energía / Carburante", nombre_imp_esp, "IVA (21%)"],
                            "Importe (€)": [base, imp_esp, iva],
                            "Porcentaje": [(base/gasto_total_periodo)*100 if gasto_total_periodo else 0,
                                           (imp_esp/gasto_total_periodo)*100 if gasto_total_periodo else 0,
                                           (iva/gasto_total_periodo)*100 if gasto_total_periodo else 0]
                        })
                        
                        st.dataframe(
                            df_desglose.style.format({"Importe (€)": "{:.2f} €", "Porcentaje": "{:.1f} %"}),
                            use_container_width=True,
                            hide_index=True
                        )

                    with col_d2:
                        fig_pie = px.pie(
                            df_desglose,
                            values="Importe (€)",
                            names="Concepto",
                            title="Distribución del Coste Total",
                            color_discrete_sequence=["#2ca02c", "#d62728", "#ff7f0e"]
                        )
                        st.plotly_chart(fig_pie, use_container_width=True)

                    # --- MÓDULO DE ENVÍO DE EMAIL ---
                    st.divider()
                    st.subheader("📧 Recibir Informe Detallado por Email")
                    
                    with st.form("form_email"):
                        email_usuario = st.text_input("Introduce tu correo electrónico para recibir este informe:")
                        submit_email = st.form_submit_button("Enviar Informe")

                        if submit_email:
                            if not email_usuario or "@" not in email_usuario:
                                st.error("Por favor, introduce una dirección de correo válida.")
                            else:
                                resumen_data = {
                                    "origen": origen_seleccionado.address,
                                    "destino": destino_seleccionado.address,
                                    "distancia_km": distancia_km,
                                    "distancia_diaria": distancia_diaria,
                                    "dias_semana": dias_por_semana,
                                    "tipo_combustible": tipo_combustible,
                                    "consumo": consumo,
                                    "unidad_consumo": "kWh/100km" if tipo_combustible == "Eléctrico" else "L/100km",
                                    "precio_ref": precio_actual,
                                    "unidad_precio": "€/kWh" if tipo_combustible == "Eléctrico" else "€/L",
                                    "gasto_total": gasto_total_periodo,
                                    "consumo_total": unidades_totales_periodo,
                                    "unidad_totales": "kWh" if tipo_combustible == "Eléctrico" else "Litros",
                                    "base": base,
                                    "impuesto_esp": imp_esp,
                                    "nombre_impuesto": nombre_imp_esp,
                                    "iva": iva
                                }
                                ok, msg = enviar_informe_email(email_usuario, resumen_data)
                                if ok:
                                    st.success(msg)
                                else:
                                    st.warning(msg)

                with tab2:
                    fig_precio_dual = make_subplots(specs=[[{"secondary_y": True}]])

                    fig_precio_dual.add_trace(
                        go.Scatter(
                            x=df_precios["Fecha"],
                            y=df_precios["Precio_Combustible"],
                            name=f"{tipo_combustible} (€/{'kWh' if tipo_combustible == 'Eléctrico' else 'L'})",
                            mode="lines",
                            line=dict(color="#0055ff", width=3),
                        ),
                        secondary_y=False,
                    )

                    fig_precio_dual.add_trace(
                        go.Scatter(
                            x=df_precios["Fecha"],
                            y=df_precios["Precio_Brent"],
                            name="Brent ($/Barril)",
                            mode="lines",
                            line=dict(color="#ff7f0e", width=2, dash="dash"),
                        ),
                        secondary_y=True,
                    )

                    min_comb = df_precios["Precio_Combustible"].min()
                    max_comb = df_precios["Precio_Combustible"].max()
                    min_brent = df_precios["Precio_Brent"].min()
                    max_brent = df_precios["Precio_Brent"].max()

                    fig_precio_dual.update_layout(
                        title=f"Evolución del Precio: {tipo_combustible} vs Petróleo Brent",
                        hovermode="x unified",
                    )
                    
                    fig_precio_dual.update_yaxes(
                        title_text=f"{tipo_combustible}",
                        secondary_y=False,
                        range=[max(0.0, min_comb * 0.7), max_comb * 1.15],
                    )
                    
                    fig_precio_dual.update_yaxes(
                        title_text="Brent ($/Barril)",
                        secondary_y=True,
                        range=[max(0.0, min_brent * 0.85), max_brent * 1.3],
                    )

                    fig_precio_dual.add_vline(
                        x=hoy.strftime("%Y-%m-%d"),
                        line_dash="dash",
                        line_color="green",
                        annotation_text="Hoy",
                    )
                    st.plotly_chart(fig_precio_dual, use_container_width=True)

# --- 3. PIE DE PÁGINA / FUENTES DE DATOS ---
st.divider()
st.markdown(
    """
    ### ℹ️ Origen y Fuentes de Datos
    - **Precios de Carburantes y Luz:** Servicio REST público del *Ministerio para la Transición Ecológica y el Reto Demográfico* de España y referencia de tarifas medias de recarga.
    - **Cotización del Petróleo Brent:** Cotización oficial del barril de crudo Brent en tiempo real extraída del mercado bursátil internacional (*Yahoo Finance*, Ticker `BZ=F`).
    - **Rutas y Distancias:** Cálculo vial ejecutado mediante la API *OSRM (Open Source Routing Machine)* sobre mapas abiertos.
    - **Geocodificación de Direcciones:** Motor de geolocalización *Nominatim* de la plataforma colaborativa *OpenStreetMap*.
    """
)
