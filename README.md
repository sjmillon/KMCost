# ⛽ KMCost

**Cuánto te cuesta conducir**, con precios oficiales en tiempo real. App web hecha en
[Streamlit](https://streamlit.io) y publicada en **https://kmcost.streamlit.app**.

## Modos

### 🧭 Viajar
1. Escribe la **salida** y la **llegada** (cualquier dirección de España).
2. Elige tu **vehículo**: catálogo con consumos de referencia (BMW X3 diésel, Seat León/Ibiza/Arona,
   Dacia, Golf TDI, Clio, 208, Toyota Corolla/C-HR híbridos, Kia Sportage y Outlander PHEV,
   Tesla Model 3/Y, MG4…). Todos los valores se pueden editar.
3. Indica la **autonomía** que te queda y la que tienes con el depósito lleno (se calcula con el
   depósito y el consumo).
4. Elige qué buscas: **la más barata** o **una marca concreta** (CEPSA y Moeve cuentan como una sola marca).

La app traza la ruta y te muestra:
- **Todas las gasolineras de la ruta** (a menos de 5 km, ajustable), con un listado por marca para
  quien siempre reposta en la misma.
- **Las más baratas** del trayecto.
- **Dónde parar**: un plan de paradas que respeta tu autonomía con un margen de seguridad del 10 %
  (20 km como mínimo). Si el viaje es más largo que un depósito, planifica varias paradas.
- **El coste del viaje** al precio de la gasolinera elegida, comparado con la media de tu provincia
  y con tu marca (o con CEPSA/Moeve).
- **Un mapa interactivo**: al pulsar una gasolinera o un cargador, se abre en **Google Maps** o **Waze**.

**Eléctricos e híbridos**
- **Eléctrico**: puntos de carga de la ruta (con opción de solo carga rápida de 50 kW o más), plan de
  recargas según la batería, y coste con la luz de casa (PVPC de hoy más el impuesto eléctrico y el
  IVA) y en cargador público (0,45 €/kWh por defecto, editable).
- **Híbrido enchufable**: primero gasta la batería (a precio de casa) y luego combustible. Muestra
  gasolineras y puntos de carga.
- **Híbrido convencional**: se trata como un coche de combustión, con su consumo real.

### 🏠 Casa-trabajo
El cálculo de siempre del gasto diario, mensual y anual de ir a trabajar:
- Precio de la **gasolinera más barata de tu trayecto**, la que elijas o la **media provincial**.
- Histórico estimado y proyección con el **Brent**, desglose de **impuestos** (IEAH o IEE e IVA) y
  envío del **informe por email**.
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
```

## Secrets (opcionales)
Copia `.streamlit/secrets.toml.example` como `.streamlit/secrets.toml` en local, o pega su contenido en
*Streamlit Community Cloud → Settings → Secrets*:
- `SMTP_SERVER`, `SMTP_PORT`, `SENDER_EMAIL`, `SENDER_PASSWORD`: para enviar el informe por email.
- `OCM_API_KEY`: para añadir OpenChargeMap (clave gratuita) como fuente de puntos de carga.

Sin secrets, la app funciona igual. Solo deja de enviar emails y usa las fuentes abiertas de puntos de carga.

## Estructura
```
app.py               Interfaz (modos Viajar y Casa-trabajo)
kmcost/data.py       Llamadas a las APIs (con caché y reintentos)
kmcost/geo.py        Geometría: proyección de puntos sobre la ruta
kmcost/planner.py    Gasolineras y cargadores en la ruta y plan de paradas
kmcost/costs.py      Costes, impuestos y formato
kmcost/vehicles.py   Catálogo de vehículos y consumos de referencia
tests/               Pruebas básicas (pytest)
```

## Limitaciones
- Los consumos son de referencia: ajústalos a tu coche.
- La posición en la ruta y el desvío se calculan en línea recta hasta la carretera, así que el
  desvío real puede ser algo mayor.
- La app no sabe en qué sentido de la autovía está cada gasolinera.
- El precio de los cargadores públicos varía según el operador; la app usa el que indiques.
- El PVPC es el término de energía de la tarifa regulada; no incluye el término de potencia.
