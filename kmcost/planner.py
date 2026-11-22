"""Selección de gasolineras/cargadores en la ruta y planificación de paradas."""
import numpy as np
import pandas as pd

from .geo import bbox, proyectar_en_ruta, simplificar


def margen_seguridad(autonomia_llena_km, pct=0.10, minimo_km=20.0):
    return max(autonomia_llena_km * pct, minimo_km)


def puntos_en_ruta(df, ruta, desvio_km=5.0, columna_precio=None, solo_publicas=True):
    """Filtra los puntos (gasolineras o cargadores) a menos de `desvio_km` de la ruta.

    Añade columnas `km_ruta` (posición desde el origen) y `desvio_km` (distancia a la ruta).
    """
    if df is None or df.empty:
        return pd.DataFrame()
    sub = df
    if columna_precio:
        sub = sub[sub[columna_precio].notna() & (sub[columna_precio] > 0)]
    if solo_publicas and "publica" in sub:
        sub = sub[sub["publica"]]
    lat_min, lon_min, lat_max, lon_max = bbox(ruta["coords"], margen_km=desvio_km + 2)
    sub = sub[sub["lat"].between(lat_min, lat_max) & sub["lon"].between(lon_min, lon_max)]
    if sub.empty:
        return sub.assign(km_ruta=[], desvio_km=[])
    coords = simplificar(ruta["coords"], 4000)
    dist, km = proyectar_en_ruta(sub["lat"].to_numpy(), sub["lon"].to_numpy(), coords,
                                 escala_km=ruta["distancia_km"])
    sub = sub.assign(desvio_km=dist, km_ruta=km)
    sub = sub[sub["desvio_km"] <= desvio_km]
    return sub.sort_values("km_ruta").reset_index(drop=True)


def planificar_paradas(cands, distancia_total, autonomia_actual, autonomia_llena,
                       margen_pct=0.10, margen_min_km=20.0, columna_precio=None, marca=None,
                       modo="barata", max_paradas=25):
    """Plan de paradas para llegar al destino.

    cands: DataFrame con `km_ruta` (y `columna_precio` / `marca` si aplica).
    modo "barata": la más barata alcanzable (evitando parar demasiado pronto).
    modo "lejana": la más lejana alcanzable (cargadores con precio desconocido).
    marca: si se indica, se prefiere esa marca; si no hay ninguna alcanzable, se avisa y se usa otra.

    Devuelve dict con `paradas` (lista de dicts), `avisos` y `llega` (bool).
    """
    avisos = []
    paradas = []
    pos = 0.0
    rango = float(autonomia_actual)
    util_llena = max(autonomia_llena - margen_seguridad(autonomia_llena, margen_pct, margen_min_km), 1.0)
    if cands is None or cands.empty:
        cands = pd.DataFrame(columns=["km_ruta"])

    for _ in range(max_paradas):
        margen_km = margen_seguridad(rango, margen_pct, margen_min_km)
        if pos + rango - margen_km >= distancia_total:
            return {"paradas": paradas, "avisos": avisos, "llega": True}

        limite = pos + rango - margen_km
        ventana = cands[(cands["km_ruta"] > pos + 0.5) & (cands["km_ruta"] <= limite)]
        sin_margen = False
        if ventana.empty:
            ventana = cands[(cands["km_ruta"] > pos + 0.5) & (cands["km_ruta"] <= pos + rango)]
            sin_margen = True
        if ventana.empty:
            avisos.append(
                f"No hay ningún punto alcanzable a partir del km {pos:.0f}: con {rango:.0f} km de "
                "autonomía no llegas a la siguiente opción de la ruta. Aumenta el desvío permitido "
                "o reposta antes de salir."
            )
            return {"paradas": paradas, "avisos": avisos, "llega": False}
        if sin_margen:
            avisos.append(
                f"Parada al límite: entre el km {pos:.0f} y el siguiente punto no se puede respetar "
                f"el margen de seguridad de {margen_km:.0f} km."
            )

        elegida_de = ventana
        if marca:
            de_marca = ventana[ventana["marca"] == marca]
            if de_marca.empty:
                avisos.append(
                    f"No hay {marca} alcanzable entre el km {pos:.0f} y el km {limite:.0f}; "
                    "te propongo la mejor alternativa de otra marca."
                )
            else:
                elegida_de = de_marca

        # Si desde alguna estación de la ventana ya se llega al destino con el depósito lleno,
        # se elige entre esas (así se evita una parada extra).
        finales = elegida_de[elegida_de["km_ruta"] >= distancia_total - util_llena]
        if not finales.empty:
            pool = finales
        else:
            # Evita parar demasiado pronto: usa la segunda mitad de la ventana si hay opciones.
            mitad = pos + 0.5 * (limite - pos)
            tardias = elegida_de[elegida_de["km_ruta"] >= mitad]
            pool = tardias if not tardias.empty else elegida_de

        if modo == "barata" and columna_precio:
            pool = pool.sort_values([columna_precio, "km_ruta"], ascending=[True, False])
        else:
            # Cargadores: entre los de los últimos ~40 km alcanzables, el de más potencia.
            if "potencia_kw" in pool:
                cerca_limite = pool[pool["km_ruta"] >= pool["km_ruta"].max() - 40]
                pool = cerca_limite.assign(_pot=cerca_limite["potencia_kw"].fillna(0))
                pool = pool.sort_values(["_pot", "km_ruta"], ascending=[False, False])
            else:
                pool = pool.sort_values("km_ruta", ascending=False)
        fila = pool.iloc[0]
        km = float(fila["km_ruta"])
        llegada = rango - (km - pos)  # km de autonomía al llegar
        restante = distancia_total - km
        parada = fila.to_dict()
        parada.update({
            "km_desde_anterior": km - pos,
            "autonomia_llegada": llegada,
            "km_a_recargar_lleno": max(autonomia_llena - llegada, 0.0),
            "km_minimos": max(min(restante + margen_seguridad(autonomia_llena, margen_pct,
                                                               margen_min_km),
                                  autonomia_llena) - llegada, 0.0),
            "margen_aplicado": margen_km,
        })
        paradas.append(parada)
        pos = km
        rango = float(autonomia_llena)

    avisos.append("Se alcanzó el número máximo de paradas planificadas.")
    return {"paradas": paradas, "avisos": avisos, "llega": False}


def precio_ponderado(paradas, distancia_total, columna_precio, precio_sin_paradas):
    """Precio medio del combustible del viaje.

    El tramo inicial (combustible que ya llevas) se valora al precio de la primera parada,
    es decir, a coste de reposición.
    """
    if not paradas:
        return precio_sin_paradas
    kms = [p["km_ruta"] for p in paradas] + [distancia_total]
    total = 0.0
    # tramo inicial + tramo tras la primera parada al precio de la primera
    total += kms[1] * paradas[0][columna_precio]
    for i in range(1, len(paradas)):
        total += (kms[i + 1] - kms[i]) * paradas[i][columna_precio]
    return total / distancia_total if distancia_total else precio_sin_paradas


def resumen_marcas(cands, columna_precio):
    if cands is None or cands.empty:
        return pd.DataFrame()
    g = cands.groupby("marca")[columna_precio].agg(["count", "min", "mean"]).reset_index()
    g.columns = ["Marca", "Estaciones", "Más barata (€/L)", "Media (€/L)"]
    return g.sort_values(["Estaciones", "Más barata (€/L)"], ascending=[False, True]).reset_index(drop=True)


__all__ = ["margen_seguridad", "puntos_en_ruta", "planificar_paradas", "precio_ponderado",
           "resumen_marcas", "np"]
