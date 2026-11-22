"""Cálculo de costes e impuestos."""

IEAH_DIESEL = 0.379  # €/L, impuesto especial de hidrocarburos (gasóleo)
IEAH_GASOLINA = 0.472  # €/L (gasolina)
IEE = 0.0511269632
IVA = 0.21


def coste_combustible(km, consumo_l_100, precio_l):
    litros = km * consumo_l_100 / 100.0
    return litros, litros * precio_l


def coste_electrico(km, consumo_kwh_100, precio_kwh):
    kwh = km * consumo_kwh_100 / 100.0
    return kwh, kwh * precio_kwh


def desglose_impuestos(coste_total, unidades, tipo):
    """Devuelve (base, impuesto_especial, iva). tipo: 'Eléctrico' o nombre de combustible."""
    if coste_total <= 0:
        return 0.0, 0.0, 0.0
    iva = coste_total - coste_total / (1 + IVA)
    sin_iva = coste_total / (1 + IVA)
    if tipo == "Eléctrico":
        iee = sin_iva - sin_iva / (1 + IEE)
        return max(sin_iva - iee, 0.0), iee, iva
    ieah = IEAH_DIESEL if "Diésel" in tipo else IEAH_GASOLINA
    imp = min(unidades * ieah, sin_iva)
    return max(sin_iva - imp, 0.0), imp, iva


def euros(valor, dec=2):
    if valor is None:
        return "—"
    s = f"{valor:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def num(valor, dec=1):
    if valor is None:
        return "—"
    s = f"{valor:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")
