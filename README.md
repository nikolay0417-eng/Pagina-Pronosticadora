# Agente Deportivo

Proyecto local para recolectar partidos de **API-FOOTBALL** y generar pronosticos deportivos
explicables usando el historial descargado. Cubre 21 competiciones configuradas, incluida la
**Primera A colombiana (Liga BetPlay)**, con estadisticas reales por partido: corners, tarjetas,
tiros, posesion, faltas y pases.

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

Flags disponibles: `--actualizar-datos` (cosecha la temporada en curso), `--rellenar-stats`
(rellena corners y tarjetas gastando la cuota del dia), `--calibrar` (corre `calibrate`, acepta
`--competition` y `--limit`), `--sin-abrir` (no abre el navegador al final).

El resto de esta guia explica cada paso por separado, para cuando quieras correrlos de forma
individual.

## 1. Actualizar datos

La fuente de datos es [API-FOOTBALL](https://dashboard.api-football.com/register). Conseguí una
key gratis ahi y guardala en un archivo `api_football_key.txt` en la carpeta del proyecto (ese
archivo esta en `.gitignore`, asi que no se publica). Tambien podes usar la variable de entorno
`API_FOOTBALL_KEY`.

### Los tres modos de recoleccion

El plan gratuito tiene tres limites que definen como se recolecta:

- **100 solicitudes por dia.**
- **Historicos solo de 2022, 2023 y 2024.**
- **Por fecha, solo una ventana de hoy a hoy+2 dias** — pero esa ventana si expone la temporada
  en curso de todas las ligas.

Por eso hay tres modos que se complementan:

```powershell
# Resultados historicos. Barato: 1 solicitud trae la temporada completa de una liga.
python .\api_football.py --mode backfill

# Corners y tarjetas, partido por partido. Caro (1 solicitud c/u) pero REANUDABLE:
# corre un rato cada dia y va completando sin perder lo ya hecho.
python .\api_football.py --mode stats

# Temporada en curso. Es lo que hay que correr a diario.
python .\api_football.py --mode daily
```

Ver las ligas configuradas y cuanta cuota te queda:

```powershell
python .\api_football.py --mode leagues
python .\api_football.py --mode quota
```

Filtrar por liga en cualquier modo:

```powershell
python .\api_football.py --mode backfill --leagues COL
python .\api_football.py --mode stats --leagues COL PL PD
```

### Por que el modo `stats` va de a poco

Traer las estadisticas cuesta **1 solicitud por partido**, asi que con 100 por dia se completan
unos 95 partidos diarios. El script recuerda cuales ya bajo (en `data/api_football_state.json`)
y cuales no tienen estadisticas disponibles, asi que podes correrlo todos los dias sin repetir
trabajo. El dataset funciona igual mientras tanto: los pronosticos de goles y 1X2 solo necesitan
los resultados, que ya estan completos desde el `backfill`.

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

Puedes escribir ligas con nombres normales: `Colombia`, `Liga BetPlay`, `Dimayor`, `LaLiga`,
`Premier`, `Serie A`, `Bundesliga`, `Ligue 1`, `Champions`, `Europa League`, `Libertadores`,
`Sudamericana`, `Brasil`, `Argentina`, `Liga MX`, `Portugal`, `Francia`, `España`.

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

El modo `stats` guarda estas columnas (cada una con sufijo `_local` y `_visitante`):

```text
corners            amarillas          rojas
tiros              tiros_arco         tiros_fuera
tiros_bloqueados   tiros_dentro_area  tiros_fuera_area
faltas             fuera_juego        posesion
atajadas           pases_totales      pases_completados
pases_precision    xg                 goles_evitados
```

`xg` y `goles_evitados` vienen vacios en varias ligas: API-FOOTBALL solo calcula xG en las
competiciones con cobertura ampliada. El resto de las columnas si llega completo en la Primera A
colombiana y en las ligas grandes.

Para ver cuanto del dataset ya tiene estadisticas:

```powershell
python -c "import pandas as pd; d=pd.read_csv('data/partidos.csv'); print(d.groupby('competicion_codigo')['corners_local'].agg(['count','size']))"
```

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
4. Corners y tarjetas amarillas usan el mismo motor (Poisson independiente), evaluando varias
   lineas de una sola pasada: 7.5 a 11.5 en corners y 2.5 a 5.5 en amarillas. Se calculan los
   dos lados, porque cuando el over de una linea es bajo el under de esa misma linea es un
   mercado igual de valido.

### Corners y tarjetas en el pronostico

Tanto el pronostico del CLI como el del panel visual muestran una seccion propia con la
proyeccion, la escalera completa de lineas y el mejor mercado:

```text
Corners y tarjetas:
- Corners: proyeccion 8.81 (3.88 local + 4.93 visitante) | muestra: 33 partidos  <- muestra corta
    Over 7.5: 65.4%  |  Over 8.5: 51.9%  |  Over 9.5: 38.8%  |  Over 10.5: 27.2%  |  Over 11.5: 17.9%
    Mejor mercado: Under 11.5 corners - 82.1%
```

Estos mercados tambien entran en **mejores picks**, y se pueden filtrar:

```powershell
python .\agente_pronosticos.py picks --date 2026-08-08 --market corners
python .\agente_pronosticos.py picks --date 2026-08-08 --market tarjetas
```

**Sobre la muestra**: mientras la liga tenga menos de 60 partidos con estadisticas cargadas, la
proyeccion se muestra igual pero marcada como `muestra corta` y con confianza `baja`, porque con
pocos partidos las fuerzas por equipo todavia son ruido. No esta oculta, pero tampoco se hace
pasar por solida. Para que suba, hay que ir corriendo `--mode stats` (ver arriba): cada corrida
diaria suma ~95 partidos.

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

Lo que ya trae API-FOOTBALL y todavia no se esta usando:

- **Cuotas reales** (`/odds`): comparar la probabilidad del modelo contra la cuota del mercado
  para detectar "value bets" (cuando el modelo ve mas probabilidad de la que paga la cuota).
- **Lesiones** (`/injuries`) y **alineaciones probables** (`/fixtures/lineups`).
- **xG**: ya viene en las columnas `xg_local` / `xg_visitante` donde la liga lo tenga.

Si en algun momento el limite de 100 solicitudes diarias molesta, el plan Pro
(~USD 19/mes, 7.500 solicitudes/dia) levanta ademas el tope de temporadas historicas: se podria
bajar la temporada en curso completa de un tiron en vez de acumularla dia a dia, y rellenar las
estadisticas de las 14.000 partidos en una sola corrida en vez de a lo largo de varios meses.
No hace falta tocar el codigo: el mismo script aprovecha la cuota mas alta automaticamente.

## Historial: football-data.org

El proyecto usaba antes [football-data.org](https://www.football-data.org/). Se reemplazo porque
no cubre la liga colombiana y porque su plan gratuito dejaba vacias todas las columnas de
corners y tarjetas. El recolector viejo sigue en `API-Football.py` (nombre confuso: apunta a
football-data.org) y el dataset que genero quedo guardado en
`data/partidos_football_data_org.csv` por si lo queres comparar.
