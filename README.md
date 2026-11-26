# ⛽ NAVSIQ

**Cuánto te cuesta conducir**, con precios oficiales en tiempo real. App web hecha en
[Streamlit](https://streamlit.io) y publicada en **https://navsiq.streamlit.app**.

## Modos

### 🧭 Viajar
1. Escribe la **salida** y la **llegada** (cualquier dirección de España).
2. Elige tu **vehículo**: indica el tipo y el consumo medio (o kWh y batería si es eléctrico/híbrido enchufable).
3. Indica la **autonomía** que te queda y la que tienes con el depósito lleno (se calcula con el depósito y el consumo).
4. Elige qué buscas: **la más barata** o **una marca concreta** (CEPSA y Moeve cuentan como una sola marca).

La app traza la ruta y te muestra:
- **Todas las gasolineras de la ruta** (a menos de 5 km, ajustable), con un listado por marca para quien siempre reposta en la misma.
- **Las más baratas** del trayecto.
- **Dónde parar**: un plan de paradas que respeta tu autonomía con un margen de seguridad del 10 % (20 km como mínimo). Si el viaje es más largo que un depósito, planifica varias paradas.
- **El coste del viaje** al precio de la gasolinera elegida, comparado con la media de tu provincia y con tu marca (o con CEPSA/Moeve).
- **Un mapa interactivo**: al pulsar una gasolinera o un cargador, se abre en **Google Maps** o **Waze**.

**Eléctricos e híbridos**
- **Eléctrico**: puntos de carga de la ruta (con opción de solo carga rápida de 50 kW o más), plan de recargas según la batería, y coste con la luz de casa (PVPC de hoy más el impuesto eléctrico y el IVA) y en cargador público (0,45 €/kWh por defecto, editable).
- **Híbrido enchufable**: primero gasta la batería (a precio de casa) y luego combustible. Muestra gasolineras y puntos de carga.
- **Híbrido convencional**: se trata como un coche de combustión, con su consumo real.

### 🏠 Casa-trabajo
El cálculo de siempre del gasto diario, mensual y anual de ir a trabajar:
- Precio de la **gasolinera más barata de tu trayecto**, la que elijas o la **media provincial**.
- Histórico estimado y proyección con el **Brent**, desglose de **impuestos** (IEAH o IEE e IVA) y envío del **informe por email**.
- Mapa de las gasolineras o puntos de carga de tu trayecto.

## Fuentes de datos (públicas y gratuitas)
| Dato | Fuente | Caché |
|---|---|---|
| Precios de carburantes | API REST del MITECO (`sedeaplicaciones.minetur.gob.es`, EstacionesTerrestres) | 45 min |
| Rutas | OSRM (`router.project-osrm.org`, HTTPS) | 24 h |
| Direcciones | Nominatim (OpenStreetMap) y Photon como respaldo | 24 h |
| Precio de la luz | PVPC 2.0TD de Red Eléctrica (`apidatos.ree.es`), con ESIOS como respaldo | 1 h |
| Puntos de carga | Inventario oficial MITERD/DGT (Punto de Acceso Nacional, DATEX II), OpenStreetMap (Overpass, con espejos) y OpenChargeMap si hay clave | 6–12 h |
| Brent | Yahoo Finance (`BZ=F`) | 6 h |

## Ejecutar en local
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
