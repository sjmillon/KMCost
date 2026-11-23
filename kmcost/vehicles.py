"""Catálogo de vehículos con consumos de referencia (uso real aproximado, editable en la app)."""

# tipo: "combustion" | "hev" (híbrido convencional) | "phev" (híbrido enchufable) | "ev" (eléctrico)
# consumo_l: L/100 km en carburante; deposito: litros
# consumo_kwh: kWh/100 km en modo eléctrico; bateria: kWh útiles

VEHICULOS = {
    # BMW
    "BMW X3 xDrive20d (diésel)": dict(marca="BMW", tipo="combustion", combustible="Diésel", consumo_l=6.8, deposito=68),
    # Seat
    "Seat León 1.5 TSI": dict(marca="Seat", tipo="combustion", combustible="Gasolina 95", consumo_l=6.0, deposito=50),
    "Seat Ibiza 1.0 TSI": dict(marca="Seat", tipo="combustion", combustible="Gasolina 95", consumo_l=5.5, deposito=40),
    "Seat Arona 1.0 TSI": dict(marca="Seat", tipo="combustion", combustible="Gasolina 95", consumo_l=5.8, deposito=40),
    # Dacia
    "Dacia Sandero 1.0 TCe": dict(marca="Dacia", tipo="combustion", combustible="Gasolina 95", consumo_l=5.7, deposito=50),
    "Dacia Duster 1.5 dCi (diésel)": dict(marca="Dacia", tipo="combustion", combustible="Diésel", consumo_l=5.3, deposito=50),
    # Volkswagen
    "Volkswagen Golf 2.0 TDI (diésel)": dict(marca="Volkswagen", tipo="combustion", combustible="Diésel", consumo_l=5.0, deposito=50),
    # Renault
    "Renault Clio 1.0 TCe": dict(marca="Renault", tipo="combustion", combustible="Gasolina 95", consumo_l=5.4, deposito=42),
    # Peugeot
    "Peugeot 208 1.2 PureTech": dict(marca="Peugeot", tipo="combustion", combustible="Gasolina 95", consumo_l=5.5, deposito=44),
    # Toyota
    "Toyota Corolla 1.8 Hybrid (HEV)": dict(marca="Toyota", tipo="hev", combustible="Gasolina 95", consumo_l=4.8, deposito=43),
    "Toyota C-HR 1.8 Hybrid (HEV)": dict(marca="Toyota", tipo="hev", combustible="Gasolina 95", consumo_l=5.0, deposito=43),
    "Toyota RAV4 Hybrid (HEV)": dict(marca="Toyota", tipo="hev", combustible="Gasolina 95", consumo_l=5.7, deposito=55),
    "Toyota RAV4 Plug-in Hybrid (PHEV)": dict(marca="Toyota", tipo="phev", combustible="Gasolina 95", consumo_l=6.5, deposito=55,
                                              consumo_kwh=22.0, bateria=18.1),
    # Hyundai
    "Hyundai Tucson 1.6 T-GDI HEV": dict(marca="Hyundai", tipo="hev", combustible="Gasolina 95", consumo_l=6.0, deposito=52),
    # Kia
    "Kia Sportage 1.6 T-GDI PHEV": dict(marca="Kia", tipo="phev", combustible="Gasolina 95", consumo_l=6.8, deposito=42,
                                         consumo_kwh=20.0, bateria=13.8),
    # Mitsubishi
    "Mitsubishi Outlander PHEV": dict(marca="Mitsubishi", tipo="phev", combustible="Gasolina 95", consumo_l=7.5, deposito=56,
                                      consumo_kwh=23.0, bateria=20.0),
    # BYD
    "BYD Seal U DM-i (PHEV)": dict(marca="BYD", tipo="phev", combustible="Gasolina 95", consumo_l=5.5, deposito=60,
                                   consumo_kwh=18.0, bateria=18.3),
    "BYD Seal U (EV)": dict(marca="BYD", tipo="ev", consumo_kwh=18.5, bateria=71.8),
    # Mercedes-Benz (SUV comunes)
    "Mercedes GLC 220d (diésel)": dict(marca="Mercedes-Benz", tipo="combustion", combustible="Diésel", consumo_l=6.2, deposito=66),
    "Mercedes GLE 350d (diésel)": dict(marca="Mercedes-Benz", tipo="combustion", combustible="Diésel", consumo_l=7.5, deposito=85),
    "Mercedes GLC 300e (PHEV)": dict(marca="Mercedes-Benz", tipo="phev", combustible="Gasolina 95", consumo_l=7.0, deposito=66,
                                     consumo_kwh=24.0, bateria=31.2),
    # Tesla
    "Tesla Model 3 RWD": dict(marca="Tesla", tipo="ev", consumo_kwh=14.5, bateria=57.5),
    "Tesla Model 3 Long Range": dict(marca="Tesla", tipo="ev", consumo_kwh=15.5, bateria=75.0),
    "Tesla Model Y Long Range": dict(marca="Tesla", tipo="ev", consumo_kwh=16.5, bateria=75.0),
    # MG
    "MG4 Electric 64 kWh": dict(marca="MG", tipo="ev", consumo_kwh=17.0, bateria=61.7),
    # Personalizados
    "Personalizado (gasolina)": dict(marca="Personalizado", tipo="combustion", combustible="Gasolina 95", consumo_l=6.5, deposito=50),
    "Personalizado (diésel)": dict(marca="Personalizado", tipo="combustion", combustible="Diésel", consumo_l=6.0, deposito=55),
    "Personalizado (eléctrico)": dict(marca="Personalizado", tipo="ev", consumo_kwh=17.0, bateria=60.0),
}

TIPOS_LABEL = {
    "combustion": "Combustión",
    "hev": "Híbrido convencional (HEV)",
    "phev": "Híbrido enchufable (PHEV)",
    "ev": "Eléctrico (EV)",
}

def marcas_disponibles():
    """Devuelve lista ordenada de marcas únicas."""
    return sorted({v["marca"] for v in VEHICULOS.values()})

def modelos_de_marca(marca):
    """Devuelve lista de modelos de una marca."""
    return [nombre for nombre, datos in VEHICULOS.items() if datos["marca"] == marca]
