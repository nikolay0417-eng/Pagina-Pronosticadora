# Agente Deportivo

Proyecto local para recolectar partidos de football-data.org y generar pronosticos deportivos explicables usando el historial descargado.

## Ejecucion rapida (un solo paso)

Para no tener que correr cada script a mano, `ejecutar_todo.py` encadena el flujo completo:
genera el panel visual con los datos que ya tengas descargados y lo abre en el navegador.

En Windows, doble clic en `ejecutar_todo.bat` hace exactamente eso.

Desde la terminal:

```powershell
python .\ejecutar_todo.py
```

Por defecto **no** vuelve a descargar datos ni recalibra (esos pasos tardan varios minutos y no
hace falta repetirlos cada vez). Si los queres incluir:

```powershell
python .\ejecutar_todo.py --actualizar-datos --calibrar
```

Flags disponibles: `--actualizar-datos` (corre `API-Football.py`), `--calibrar` (corre
`calibrate`, acepta `--competition` y `--limit`), `--sin-abrir` (no abre el navegador al final).

El resto de esta guia explica cada paso por separado, para cuando quieras correrlos de forma
individual.

## 1. Actualizar datos

Primero conseguí una API key gratis en [football-data.org](https://www.football-data.org/client/register)
y definila como variable de entorno (no va escrita en el codigo, asi el repo se puede publicar
sin exponerla):

```powershell
$env:FOOTBALL_DATA_API_KEY = "tu_key"
```

Esa variable solo dura en la sesion actual de PowerShell; si abris una terminal nueva hay que
definirla de nuevo (o agregarla a tu perfil de PowerShell si la usas seguido).

Por defecto descarga todas las competiciones disponibles desde la temporada 2024 hasta la actual:

```powershell
python .\API-Football.py
```

Tambien puedes descargar una competicion especifica:

```powershell
python .\API-Football.py --mode recent-history --competition PL --from-season 2024 --status FINISHED --output premier_desde_2024
```

## 2. Usar el agente

Modo conversacional:

```powershell
python .\agente_pronosticos.py
```

Al abrirlo veras un menu para escoger:

```text
1. Pronosticar partido especifico
2. Ver partidos por fecha
3. Ver resultados por fecha
4. Ver mejores picks
5. Ver ficha completa de equipo
6. Buscar equipos
0. Salir
```

Pronostico directo:

```powershell
python .\agente_pronosticos.py predict --home "Liverpool" --away "Chelsea" --competition PL
```

Buscar equipos:

```powershell
python .\agente_pronosticos.py teams --search Liverpool
```

Analizar equipo:

```powershell
python .\agente_pronosticos.py team --team "Liverpool"
```

Ver proximos partidos cargados en el dataset:

```powershell
python .\agente_pronosticos.py upcoming
```

Ver partidos de una fecha:

```powershell
python .\agente_pronosticos.py date --date 2026-05-17 --competition LaLiga
```

Ver resultados finalizados de una fecha:

```powershell
python .\agente_pronosticos.py results --date 2026-05-09
python .\agente_pronosticos.py results --date 2026-05-09 --competition LaLiga
```

Ver mejores oportunidades/picks:

```powershell
python .\agente_pronosticos.py picks --date 2026-05-17 --competition LaLiga --limit 10
```

Filtrar picks por mercado:

```powershell
python .\agente_pronosticos.py picks --date 2026-05-17 --market Over
python .\agente_pronosticos.py picks --date 2026-05-17 --market "marcan"
```

Ver ficha completa de un equipo:

```powershell
python .\agente_pronosticos.py profile --team "Real Madrid"
python .\agente_pronosticos.py profile --team "Real Madrid" --competition LaLiga
```

Puedes escribir ligas con nombres normales: `LaLiga`, `Premier`, `Serie A`, `Bundesliga`, `Ligue 1`, `Champions`, `Libertadores`, `Brasil`, `Portugal`, `Francia`, `España`.

Medir precision del agente con historicos:

```powershell
python .\agente_pronosticos.py backtest --competition LaLiga --limit 300
python .\agente_pronosticos.py backtest --competition Premier --date-from 2025-08-01
```

Calibrar el modelo contra el historico (ajusta decaimiento temporal y correlacion Dixon-Coles
buscando el menor Brier score, y guarda el resultado en `data/model_config.json`):

```powershell
python .\agente_pronosticos.py calibrate --competition LaLiga --limit 150
```

Puede tardar varios minutos porque prueba varias combinaciones de parametros contra el
historico real. Cuanto mas alto el `--limit`, mas confiable la calibracion pero mas tarda.

Generar panel visual:

```powershell
python .\dashboard.py
```

Luego abre `dashboard.html` en el navegador. El panel visual incluye el mismo menu del agente:

```text
1. Pronosticar partido especifico
2. Ver partidos por fecha
3. Ver resultados por fecha
4. Ver mejores picks
5. Ver ficha completa de equipo
6. Buscar equipos
7. Medir precision con backtest
8. Revisar datos avanzados
```

El predictor visual (opcion 1 del panel) corre el mismo modelo matematico en el navegador
(JavaScript), usando la fuerza de ataque/defensa de cada equipo que ya viene precalculada en
el archivo generado.

## Zona horaria

Todas las fechas y horas que se muestran (CLI y panel visual) estan convertidas a hora de
Colombia (UTC-5, sin horario de verano). La API entrega las fechas en UTC; se guardan asi en
`data/partidos.csv` (`fecha_utc`), pero para filtrar por dia y para mostrarlas se usa siempre la
hora local ya convertida. Si alguna vez corres esto desde otro pais, cambia `LOCAL_TZ` en
[data_loader.py](data_loader.py).

## Estadisticas Avanzadas

El recolector intenta guardar estas columnas si la API las entrega:

```text
corners_local, corners_visitante
amarillas_local, amarillas_visitante
rojas_local, rojas_visitante
faltas_local, faltas_visitante
tiros_local, tiros_visitante
tiros_arco_local, tiros_arco_visitante
posesion_local, posesion_visitante
```

Si al actualizar datos esas columnas quedan vacias, significa que el endpoint de lista no las esta entregando para tu plan o respuesta actual. El siguiente paso seria consultar detalle por partido, que consume muchas mas solicitudes de API.

## Como funciona el modelo

El pronostico usa un modelo de **Poisson / Dixon-Coles** (`poisson_model.py`), el mismo enfoque
estadistico que usan las casas de apuestas y los papers de analitica de futbol desde Dixon & Coles
(1997). En vez de pesos inventados a mano, calcula matematicamente:

1. **Fuerza de ataque y defensa de cada equipo**, relativa al promedio de su liga, dandole mas
   peso a los partidos recientes (decaimiento exponencial) y regularizando hacia la media cuando
   hay pocos partidos disponibles (para no sobre-confiar en muestras chicas, por ejemplo equipos
   recien ascendidos).
2. Con eso arma los **goles esperados** de local y visitante, y construye la matriz completa de
   probabilidad de cada marcador posible (0-0, 1-0, 0-1, 1-1, 2-1, ...), con la correccion de
   Dixon-Coles para los marcadores bajos.
3. De esa matriz salen 1X2, over/under exactos, ambos marcan y el marcador mas probable — ya no
   son aproximaciones lineales, son la probabilidad real segun el modelo.
4. Corners y tarjetas amarillas usan el mismo motor (Poisson independiente) para las lineas
   over 8.5 corners / over 3.5 amarillas.

El historial directo (head-to-head) y la posicion en la tabla se muestran como contexto
informativo en las senales, pero ya no inflan artificialmente la probabilidad: la evidencia en
analitica deportiva es que el h2h por si solo aporta poca señal una vez que ya conoces la fuerza
real de cada equipo.

**Calibracion medible**: el backtest ahora reporta, ademas del % de aciertos por mercado, el
**Brier score** del mercado 1X2 (0 = probabilidades perfectas, 0.667 = equivalente a adivinar al
azar). Es la metrica estandar para saber si las probabilidades estan bien calibradas, no solo si
"acertaste". El comando `calibrate` prueba varias combinaciones de decaimiento temporal y
correlacion Dixon-Coles contra el historico real y guarda la que minimiza el Brier score en
`data/model_config.json`.

No garantiza resultados; sirve como base analitica rigurosa para comparar partidos y detectar
mercados con mejor pinta.

## Proximo paso: mas datos

Para llevar esto mas lejos con informacion que football-data.org no entrega (cuotas reales de
mercado, xG, lesiones, alineaciones), dos opciones para cuando quieras sumarlas — ninguna esta
integrada todavia, hace falta que crees la cuenta y consigas la API key:

- **[The Odds API](https://the-odds-api.com/)**: cuotas reales de multiples casas de apuestas.
  Plan gratuito con 500 solicitudes/mes. Sirve para comparar la probabilidad que calcula este
  modelo contra la cuota real del mercado y detectar "value bets" (cuando el modelo ve mas
  probabilidad de la que paga la cuota).
- **[API-FOOTBALL](https://www.api-football.com/)** (tambien disponible via RapidAPI): estadisticas
  avanzadas por partido (tiros, posesion, xG en las ligas principales), lesiones y alineaciones
  probables antes del partido. Plan gratuito con 100 solicitudes/dia.

Cuando tengas una key de alguno, se puede sumar como una fuente de datos mas sin tocar el modelo
Poisson (son capas independientes).
