import streamlit as st
import requests
import urllib.parse
from datetime import datetime

st.set_page_config(page_title="Calculadora de Gasto de Gasolina", page_icon="🚗", layout="centered")

def obtener_coordenadas(direccion):
    url = f"https://nominatim.openstreetmap.org/search?format=json&q={urllib.parse.quote(direccion)}"
    headers = {'User-Agent': 'CalculadoraGasolina/1.0'}
    try:
        respuesta = requests.get(url, headers=headers).json()
        if respuesta:
            return respuesta[0]['lat'], respuesta[0]['lon']
    except:
        pass
    return None, None

def calcular_ruta(origen, destino):
    lat1, lon1 = obtener_coordenadas(origen)
    lat2, lon2 = obtener_coordenadas(destino)
    
    if not lat1 or not lat2:
        return "Error al encontrar las direcciones", 0, 0
        
    url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
    try:
        respuesta = requests.get(url).json()
        if respuesta['code'] == 'Ok':
            distancia_km = respuesta['routes'][0]['distance'] / 1000
            tiempo_minutos = respuesta['routes'][0]['duration'] / 60
            return distancia_km, tiempo_minutos
    except:
        pass
    return 0, 0

st.title("🚗 Calculadora de Gasto para ir al Trabajo")
st.markdown("Estima el coste de tus desplazamientos en función de la ruta, el consumo y los días que vas a la oficina.")

with st.sidebar:
    st.header("⚙️ Ajustes del Vehículo")
    tipo_combustible = st.selectbox("Tipo de combustible", ["Gasolina 95", "Gasolina 98", "Diésel", "Diésel Premium"])
    consumo = st.number_input("Consumo de tu coche (L/100km)", min_value=1.0, max_value=30.0, value=6.5, step=0.1)
    precio_combustible = st.number_input(f"Precio actual del {tipo_combustible} (€/L)", min_value=0.5, max_value=3.0, value=1.65, step=0.01)

col1, col2 = st.columns(2)
with col1:
    origen = st.text_input("🏠 Lugar de origen", placeholder="Ej: Puerta del Sol, Madrid")
with col2:
    destino = st.text_input("🏢 Lugar de destino (Trabajo)", placeholder="Ej: Las Rozas, Madrid")

st.divider()
st.subheader("📅 Planificación")
col3, col4 = st.columns(2)
with col3:
    dias_semana = st.slider("Días a la semana que vas a la oficina", min_value=1, max_value=7, value=3)
with col4:
    semanas = st.number_input("Semanas a estimar (Ej: 4 para un mes)", min_value=1, max_value=52, value=4)

if st.button("🚀 Calcular Gasto Estimado", type="primary", use_container_width=True):
    if not origen or not destino:
        st.warning("⚠️ Por favor, introduce el origen y el destino.")
    else:
        with st.spinner("Calculando ruta con OSRM..."):
            distancia, tiempo = calcular_ruta(origen, destino)
            
            if isinstance(distancia, str):
                st.error("❌ No se ha podido calcular la ruta. Comprueba las direcciones.")
            else:
                # El trayecto es ida y vuelta
                distancia_diaria = distancia * 2
                tiempo_diario = tiempo * 2
                
                # Consumo diario
                litros_diarios = (distancia_diaria / 100) * consumo
                coste_diario = litros_diarios * precio_combustible
                
                # Totales del periodo
                total_dias = dias_semana * semanas
                coste_total = coste_diario * total_dias
                distancia_total = distancia_diaria * total_dias
                tiempo_total_horas = (tiempo_diario * total_dias) / 60
                
                st.success("✅ ¡Cálculo completado!")
                
                st.subheader("📊 Resultados de la Estimación")
                
                m1, m2, m3 = st.columns(3)
                m1.metric("📍 Distancia por trayecto", f"{distancia:.2f} km")
                m2.metric("⏱️ Tiempo est. por trayecto", f"{tiempo:.0f} min")
                m3.metric("💶 Coste Diario (Ida y Vuelta)", f"{coste_diario:.2f} €")
                
                st.divider()
                
                st.markdown(f"### 🎯 Resumen para {total_dias} días de trabajo ({semanas} semanas)")
                
                r1, r2, r3 = st.columns(3)
                r1.metric("🛣️ Distancia Total", f"{distancia_total:.1f} km")
                r2.metric("⏳ Tiempo Total en el coche", f"{tiempo_total_horas:.1f} horas")
                r3.metric("💰 Coste Total Estimado", f"{coste_total:.2f} €")
                
                st.info("💡 Este cálculo asume un tráfico fluido. El consumo real puede variar dependiendo del estilo de conducción y los atascos.")
