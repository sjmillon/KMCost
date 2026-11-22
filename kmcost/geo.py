"""Geometría: distancias, proyección de puntos sobre una ruta y utilidades de polilíneas."""
import math

import numpy as np

R_TIERRA_KM = 6371.0088


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * R_TIERRA_KM * np.arcsin(np.sqrt(a))


def km_acumulados(coords):
    """coords: lista [[lon, lat], ...] (formato GeoJSON). Devuelve array de km acumulados."""
    arr = np.asarray(coords, dtype=float)
    if len(arr) < 2:
        return np.zeros(len(arr))
    d = haversine_km(arr[:-1, 1], arr[:-1, 0], arr[1:, 1], arr[1:, 0])
    return np.concatenate([[0.0], np.cumsum(d)])


def simplificar(coords, max_puntos=1500):
    """Reduce el número de vértices manteniendo inicio y fin (muestreo uniforme)."""
    n = len(coords)
    if n <= max_puntos:
        return list(coords)
    idx = np.unique(np.linspace(0, n - 1, max_puntos).round().astype(int))
    return [coords[i] for i in idx]


def proyectar_en_ruta(lats, lons, coords, escala_km=None):
    """Proyecta puntos sobre la ruta.

    Devuelve (distancia_a_ruta_km, km_en_ruta) para cada punto. Usa una proyección
    equirectangular local (suficientemente precisa para distancias de unos pocos km).
    escala_km: longitud real de la ruta (p. ej. la de OSRM) para reescalar los km en ruta.
    """
    lats = np.asarray(lats, dtype=float)
    lons = np.asarray(lons, dtype=float)
    ruta = np.asarray(coords, dtype=float)
    if len(lats) == 0 or len(ruta) < 2:
        return np.full(len(lats), np.inf), np.zeros(len(lats))

    lat0 = math.radians(float(np.mean(ruta[:, 1])))
    kx = 111.320 * math.cos(lat0)
    ky = 110.574
    rx = ruta[:, 0] * kx
    ry = ruta[:, 1] * ky
    ax, ay = rx[:-1], ry[:-1]
    bx, by = rx[1:], ry[1:]
    dx, dy = bx - ax, by - ay
    seg_len2 = dx * dx + dy * dy
    seg_len2[seg_len2 == 0] = 1e-12
    acum = km_acumulados(coords)
    seg_km = np.diff(acum)

    px = lons * kx
    py = lats * ky
    dist_out = np.full(len(lats), np.inf)
    km_out = np.zeros(len(lats))
    bloque = 400  # procesa por bloques para limitar memoria
    for i in range(0, len(lats), bloque):
        qx = px[i:i + bloque][:, None]
        qy = py[i:i + bloque][:, None]
        t = ((qx - ax) * dx + (qy - ay) * dy) / seg_len2
        t = np.clip(t, 0.0, 1.0)
        cx = ax + t * dx
        cy = ay + t * dy
        d2 = (qx - cx) ** 2 + (qy - cy) ** 2
        j = np.argmin(d2, axis=1)
        filas = np.arange(len(j))
        dist_out[i:i + bloque] = np.sqrt(d2[filas, j])
        km_out[i:i + bloque] = acum[j] + t[filas, j] * seg_km[j]

    if escala_km and acum[-1] > 0:
        km_out = km_out * (escala_km / acum[-1])
    return dist_out, km_out


def bbox(coords, margen_km=10.0):
    arr = np.asarray(coords, dtype=float)
    dlat = margen_km / 110.574
    lat_med = math.radians(float(np.mean(arr[:, 1])))
    dlon = margen_km / (111.320 * max(math.cos(lat_med), 0.1))
    return (arr[:, 1].min() - dlat, arr[:, 0].min() - dlon, arr[:, 1].max() + dlat, arr[:, 0].max() + dlon)


def codificar_polilinea(coords, precision=5):
    """Codifica [[lon, lat], ...] en el formato Encoded Polyline de Google (lat, lon)."""
    factor = 10 ** precision
    resultado = []
    prev_lat = prev_lon = 0
    for lon, lat in coords:
        ilat = int(round(lat * factor))
        ilon = int(round(lon * factor))
        for valor in (ilat - prev_lat, ilon - prev_lon):
            v = ~(valor << 1) if valor < 0 else (valor << 1)
            while v >= 0x20:
                resultado.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            resultado.append(chr(v + 63))
        prev_lat, prev_lon = ilat, ilon
    return "".join(resultado)
