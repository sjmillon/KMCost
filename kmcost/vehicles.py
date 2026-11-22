"""Catálogo de vehículos con consumos de referencia (uso real aproximado, editable en la app)."""

# tipo: "combustion" | "hev" (híbrido convencional) | "phev" (híbrido enchufable) | "ev" (eléctrico)
# consumo_l: L/100 km en carburante; deposito: litros
# consumo_kwh: kWh/100 km en modo eléctrico; bateria: kWh útiles
VEHICULOS = {
    "BMW X3 xDrive20d (diésel)": dict(tipo="combustion", combustible="Diésel", consumo_l=6.8, deposito=68),
    "Seat León 1.5 TSI": dict(tipo="combustion", combustible="Gasolina 95", consumo_l=6.0, deposito=50),
    "Seat Ibiza 1.0 TSI": dict(tipo="combustion", combustible="Gasolina 95", consumo_l=5.5, deposito=40),
    "Seat Arona 1.0 TSI": dict(tipo="combustion", combustible="Gasolina 95", consumo_l=5.8, deposito=40),
    "Dacia Sandero 1.0 TCe": dict(tipo="combustion", combustible="Gasolina 95", consumo_l=5.7, deposito=50),
    "Dacia Duster 1.5 dCi (diésel)": dict(tipo="combustion", combustible="Diésel", consumo_l=5.3, deposito=50),
    "Volkswagen Golf 2.0 TDI (diésel)": dict(tipo="combustion", combustible="Diésel", consumo_l=5.0, deposito=50),
    "Renault Clio 1.0 TCe": dict(tipo="combustion", combustible="Gasolina 95", consumo_l=5.4, deposito=42),
    "Peugeot 208 1.2 PureTech": dict(tipo="combustion", combustible="Gasolina 95", consumo_l=5.5, deposito=44),
    "Toyota Corolla 1.8 Hybrid (HEV)": dict(tipo="hev", combustible="Gasolina 95", consumo_l=4.8, deposito=43),
    "Toyota C-HR 1.8 Hybrid (HEV)": dict(tipo="hev", combustible="Gasolina 95", consumo_l=5.0, deposito=43),
    "Hyundai Tucson 1.6 T-GDI HEV": dict(tipo="hev", combustible="Gasolina 95", consumo_l=6.0, deposito=52),
    "Kia Sportage 1.6 T-GDI PHEV": dict(tipo="phev", combustible="Gasolina 95", consumo_l=6.8, deposito=42,
                                         consumo_kwh=20.0, bateria=13.8),
    "Mitsubishi Outlander PHEV": dict(tipo="phev", combustible="Gasolina 95", consumo_l=7.5, deposito=56,
                                      consumo_kwh=23.0, bateria=20.0),
    "Tesla Model 3 RWD": dict(tipo="ev", consumo_kwh=14.5, bateria=57.5),
    "Tesla Model 3 Long Range": dict(tipo="ev", consumo_kwh=15.5, bateria=75.0),
    "Tesla Model Y Long Range": dict(tipo="ev", consumo_kwh=16.5, bateria=75.0),
    "MG4 Electric 64 kWh": dict(tipo="ev", consumo_kwh=17.0, bateria=61.7),
    "Personalizado (gasolina)": dict(tipo="combustion", combustible="Gasolina 95", consumo_l=6.5, deposito=50),
    "Personalizado (diésel)": dict(tipo="combustion", combustible="Diésel", consumo_l=6.0, deposito=55),
    "Personalizado (eléctrico)": dict(tipo="ev", consumo_kwh=17.0, bateria=60.0),
}

TIPOS_LABEL = {
    "combustion": "Combustión",
    "hev": "Híbrido convencional (HEV)",
    "phev": "Híbrido enchufable (PHEV)",
    "ev": "Eléctrico (EV)",
}
