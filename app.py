import streamlit as st
import requests
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import yfinance as yf
from geopy.geocoders import Nominatim
from dateutil.relativedelta import relativedelta

st.set_page_config(page_title="Dashboard de Consumo y Precios", page_icon="⛽", layout="wide")

# --- Funciones de Datos ---

@st.cache_data(ttl=3600)
def obtener_precio_actual_combustibles(provincia_id="28"): # Madrid por defecto
    url = f"https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/EstacionesTerrestres/FiltroProvincia/{provincia_id}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        estaciones = data.get('ListaEESSPrecio', [])
        
        precios = {'Gasolina 95': [], 'Diésel': [], 'Gasolina 98': [], 'Diésel Premium': []}
        
        for est in estaciones:
            if est['Precio Gasolina 95 E5']:
                precios['Gasolina 95'].append(float(est['Precio Gasolina 95 E5'].replace(',', '.')))
            if est['Precio Gasoleo A']:
                precios['Diésel'].append(float(est['Precio Gasoleo A'].replace(',', '.')))
            if est['Precio Gasolina 98 E5']:
                precios['Gasolina 98'].append(float(est['Precio Gasolina 98 E5'].replace(',', '.')))
            if est['Precio Gasoleo Premium']:
                precios['Diésel Premium'].append(float(est['Precio Gasoleo Premium'].replace(',', '.')))
                
        medias = {k: sum(v)/len(v) if v else None for k, v in precios.items()}
        return medias
    except Exception as e:
        return None

@st.cache_data(ttl=86400)
def obtener_historico_brent(dias=365):
    try:
        brent = yf.download("BZ=F", period=f"{dias}d")
        return brent['Close'].reset_index()
    except:
        return pd.DataFrame()

# Como no tenemos un histórico real de gasolineras a nivel usuario, simularemos una correlación
# basada en el Brent para la visualización del pasado y predicción, que es el objetivo
def generar_historico_y_proyeccion(brent_df, fecha_inicio, fecha_fin, tipo_combustible, precio_actual):
    if brent_df.empty or precio_actual is None:
        return pd.DataFrame()

    brent_df.columns = ['Fecha', 'Precio_Brent']
    brent_df['Fecha'] = pd.to_datetime(brent_df['Fecha']).dt.tz_localize(None)
    
    # Precio base del Brent reciente para correlacionar
    brent_reciente = brent_df['Precio_Brent'].iloc[-1].item() if not brent_df.empty else 80.0
    ratio = precio_actual / brent_reciente if brent_reciente else 0.02
    
    # Generar histórico (último año)
    historico = brent_df.copy()
    historico['Precio_Combustible'] = historico['Precio_Brent'] * ratio
    historico['Tipo'] = 'Histórico'
    
    # Generar proyección (futuro)
    ultima_fecha = historico['Fecha'].iloc[-1]
    dias_futuro = (fecha_fin - ultima_fecha).days
    
    if dias_futuro > 0:
        fechas_futuras = [ultima_fecha + timedelta(days=i) for i in range(1, dias_futuro + 1)]
        # Añadir un poco de variabilidad a la proyección manteniendo la tendencia reciente
        tendencia = (historico['Precio_Brent'].iloc[-1].item() - historico['Precio_Brent'].iloc[-30].item()) / 30 if len(historico)>30 else 0
        
        precios_futuros_brent = []
        precio_actual_brent = brent_reciente
        import random
        for _ in range(dias_futuro):
            variacion = random.uniform(-1, 1) + tendencia
            precio_actual_brent += variacion
            precios_futuros_brent.append(precio_actual_brent)
            
        proyeccion = pd.DataFrame({
            'Fecha': fechas_futuras,
            'Precio_Brent': precios_futuros_brent,
            'Precio_Combustible': [p * ratio for p in precios_futuros_brent],
            'Tipo': 'Proyección'
        })
        df_final = pd.concat([historico, proyeccion], ignore_index=True)
    else:
        df_final = historico

    df_final = df_final[(df_final['Fecha'].dt.date >= fecha_inicio) & (df_final['Fecha'].dt.date <= fecha_fin)]
    return df_final

def obtener_coordenadas(direccion):
    geolocator = Nominatim(user_agent="calculadora_combustible")
    try:
        # Añadir 'España' para acotar la búsqueda y devolver múltiples opciones
        ubicaciones = geolocator.geocode(f"{direccion}, España", exactly_one=False, limit=5)
        return ubicaciones
    except:
        return None

def calcular_ruta_osrm(lon1, lat1, lon2, lat2):
    url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
    try:
        respuesta = requests.get(url).json()
        if respuesta.get('code') == 'Ok':
            distancia_km = respuesta['routes'][0]['distance'] / 1000
            tiempo_minutos = respuesta['routes'][0]['duration'] / 60
            return distancia_km, tiempo_minutos
    except:
        pass
    return None, None

# --- UI ---

st.title("📊 Dashboard de Consumo y Proyección de Combustible")

# 1. Precios Actuales y Brent
st.header("1. Mercado Actual: Gasolina vs Brent")
precios_actuales = obtener_precio_actual_combustibles()
brent_df = obtener_historico_brent(10) # Últimos días

if precios_actuales and not brent_df.empty:
    col1, col2, col3 = st.columns(3)
    brent_hoy = brent_df['Close'].iloc[-1].item()
    brent_ayer = brent_df['Close'].iloc[-2].item() if len(brent_df)>1 else brent_hoy
    diff_brent = brent_hoy - brent_ayer
    
    col1.metric("Petróleo Brent ($/barril)", f"${brent_hoy:.2f}", f"{diff_brent:.2f} $")
    col2.metric("Media Gasolina 95 (Madrid)", f"{precios_actuales.get('Gasolina 95', 0):.3f} €/L")
    col3.metric("Media Diésel (Madrid)", f"{precios_actuales.get('Diésel', 0):.3f} €/L")
else:
    st.warning("No se pudieron cargar los datos del mercado en este momento.")

st.divider()

# 2. Configuración del Viaje y Vehículo
st.header("2. Tus Desplazamientos")

col_vehiculo, col_ruta = st.columns(2)

with col_vehiculo:
    st.subheader("🚗 Vehículo")
    tipo_combustible = st.selectbox("Tipo de combustible", ["Gasolina 95", "Diésel", "Gasolina 98", "Diésel Premium"])
    consumo = st.number_input("Consumo medio (L/100km)", min_value=1.0, value=6.5, step=0.1)

with col_ruta:
    st.subheader("🗺️ Ruta")
    
    # Búsqueda de Origen
    origen_query = st.text_input("🏠 Calle o lugar de Origen (Ej: Calle de Alcalá, Madrid)")
    origen_seleccionado = None
    if origen_query:
        opciones_origen = obtener_coordenadas(origen_query)
        if opciones_origen:
            nombres_origen = [loc.address for loc in opciones_origen]
            seleccion_org = st.selectbox("Confirma tu origen exacto:", nombres_origen, key="org")
            origen_seleccionado = next((loc for loc in opciones_origen if loc.address == seleccion_org), None)
        else:
            st.warning("No se encontró la dirección. Intenta añadir más detalles (ej: ciudad).")

    # Búsqueda de Destino
    destino_query = st.text_input("🏢 Calle o lugar de Destino (Ej: Gran Vía, Madrid)")
    destino_seleccionado = None
    if destino_query:
        opciones_destino = obtener_coordenadas(destino_query)
        if opciones_destino:
            nombres_destino = [loc.address for loc in opciones_destino]
            seleccion_dest = st.selectbox("Confirma tu destino exacto:", nombres_destino, key="dest")
            destino_seleccionado = next((loc for loc in opciones_destino if loc.address == seleccion_dest), None)
        else:
            st.warning("No se encontró la dirección. Intenta añadir más detalles.")

st.divider()

# 3. Planificación y Gráficos
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
        max_value=hoy + relativedelta(years=2)
    )

if st.button("📈 Generar Informe y Proyección", type="primary", use_container_width=True):
    if len(rango_fechas) != 2:
        st.error("Por favor, selecciona una fecha de inicio y una de fin.")
    elif not origen_seleccionado or not destino_seleccionado:
        st.error("Por favor, confirma el origen y el destino de la ruta.")
    else:
        fecha_inicio, fecha_fin = rango_fechas
        
        with st.spinner("Calculando ruta y obteniendo datos del mercado..."):
            distancia_km, tiempo_min = calcular_ruta_osrm(
                origen_seleccionado.longitude, origen_seleccionado.latitude,
                destino_seleccionado.longitude, destino_seleccionado.latitude
            )
            
            if distancia_km is None:
                st.error("No se pudo calcular la ruta. Revisa las direcciones.")
            else:
                distancia_diaria = distancia_km * 2 # Ida y vuelta
                
                # Cargar histórico de Brent más amplio para el gráfico
                dias_historico = (hoy - fecha_inicio).days + 30 # Margen
                df_brent_historico = obtener_historico_brent(dias_historico)
                
                precio_actual = precios_actuales.get(tipo_combustible)
                
                if df_brent_historico.empty or not precio_actual:
                    st.error("Error al obtener datos financieros. Intenta más tarde.")
                else:
                    # Generar DataFrame con precios e info de gasto
                    df_precios = generar_historico_y_proyeccion(
                        df_brent_historico, fecha_inicio, fecha_fin, tipo_combustible, precio_actual
                    )
                    
                    if not df_precios.empty:
                        # Calcular gasto diario (solo aplicable los días de trabajo)
                        # Para simplificar, asumimos el gasto repartido, o calculamos el gasto mensual
                        df_precios['Litros_Diarios'] = (distancia_diaria / 100) * consumo
                        
                        # Crear una columna de "Día de trabajo" para simular
                        df_precios['Es_Dia_Trabajo'] = df_precios['Fecha'].dt.dayofweek < 5 # L-V simplificado
                        
                        df_precios['Gasto_Diario'] = 0.0
                        df_precios.loc[df_precios['Es_Dia_Trabajo'], 'Gasto_Diario'] = df_precios['Litros_Diarios'] * df_precios['Precio_Combustible']
                        
                        # Resumir por mes
                        df_mensual = df_precios.groupby([pd.Grouper(key='Fecha', freq='M'), 'Tipo']).agg(
                            Precio_Medio_L=('Precio_Combustible', 'mean'),
                            Gasto_Mensual=('Gasto_Diario', 'sum')
                        ).reset_index()

                        # --- VISUALIZACIÓN ---
                        st.subheader(f"Ruta: {distancia_km:.1f} km (Trayecto) | {distancia_diaria:.1f} km/día")
                        
                        tab1, tab2 = st.tabs(["💰 Gasto Mensual (Histórico y Proyección)", "🛢️ Evolución de Precios"])
                        
                        with tab1:
                            fig_gasto = px.bar(
                                df_mensual, x='Fecha', y='Gasto_Mensual', color='Tipo',
                                title='Gasto Total Mensual en Desplazamientos',
                                labels={'Gasto_Mensual': 'Gasto (€)', 'Fecha': 'Mes'},
                                color_discrete_map={'Histórico': '#1f77b4', 'Proyección': '#ff7f0e'}
                            )
                            st.plotly_chart(fig_gasto, use_container_width=True)
                            
                            gasto_futuro = df_precios[(df_precios['Fecha'].dt.date >= hoy) & (df_precios['Fecha'].dt.date <= fecha_fin)]['Gasto_Diario'].sum()
                            st.info(f"**Proyección:** Desde hoy hasta el {fecha_fin.strftime('%d/%m/%Y')}, se estima un gasto de **{gasto_futuro:.2f} €**.")

                        with tab2:
                            fig_precio = px.line(
                                df_precios, x='Fecha', y=['Precio_Combustible', 'Precio_Brent'],
                                title=f'Correlación Estimada: {tipo_combustible} (€/L) vs Brent ($/Barril)',
                                labels={'value': 'Precio', 'variable': 'Indicador'}
                            )
                            # Eje Y secundario
                            import plotly.graph_objects as go
                            fig_precio_dual = go.Figure()
                            fig_precio_dual.add_trace(go.Scatter(x=df_precios['Fecha'], y=df_precios['Precio_Combustible'], name=f'{tipo_combustible} (€/L)', mode='lines', line=dict(color='blue')))
                            fig_precio_dual.add_trace(go.Scatter(x=df_precios['Fecha'], y=df_precios['Precio_Brent'], name='Brent ($/Barril)', mode='lines', line=dict(color='orange'), yaxis='y2'))
                            
                            fig_precio_dual.update_layout(
                                title=f"Evolución del Precio: {tipo_combustible} vs Petróleo Brent",
                                yaxis=dict(title=f'{tipo_combustible} (€/L)', titlefont=dict(color='blue'), tickfont=dict(color='blue')),
                                yaxis2=dict(title='Brent ($/Barril)', titlefont=dict(color='orange'), tickfont=dict(color='orange'), overlaying='y', side='right'),
                                hovermode='x unified'
                            )
                            
                            # Añadir línea vertical para marcar el "Hoy"
                            fig_precio_dual.add_vline(x=hoy, line_dash="dash", line_color="green", annotation_text="Hoy")
                            
                            st.plotly_chart(fig_precio_dual, use_container_width=True)
