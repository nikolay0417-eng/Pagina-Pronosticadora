"""Recolector de partidos usando API-FOOTBALL (api-sports.io).

Reemplaza a football-data.org como fuente principal: cubre la liga colombiana y
mas de 1200 competiciones, y entrega estadisticas reales por partido (corners,
tarjetas, tiros, posesion, faltas, pases) que football-data.org dejaba vacias.

El plan Free tiene tres limitaciones que definen como funciona este script:

  1. 100 solicitudes por dia.
  2. Historicos solo de las temporadas 2022, 2023 y 2024.
  3. Por fecha solo deja consultar una ventana de hoy hasta hoy+2 dias, pero esa
     ventana SI expone la temporada en curso de todas las ligas.

Por eso la recoleccion se divide en tres modos que se complementan:

  backfill  Trae los resultados historicos. Barato: 1 solicitud devuelve la
            temporada completa de una liga (380 partidos). Sin estadisticas.
  stats     Rellena las estadisticas partido por partido. Caro: 1 solicitud por
            partido. Es reanudable, asi que se puede correr un rato cada dia y
            va completando el dataset sin perder lo ya hecho.
  daily     Cosecha la ventana de hoy+2 dias. Es lo que mantiene al dia la
            temporada en curso, que el plan Free no deja bajar de un tiron.

Todos los modos hacen upsert sobre data/partidos.csv, respetando el mismo
esquema de columnas que ya usan data_loader.py, poisson_model.py y dashboard.py.
"""

import argparse
import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests


BASE_URL = "https://v3.football.api-sports.io"
API_KEY_FILE = Path("api_football_key.txt")
OUTPUT_DIR = Path("data")
DATASET = OUTPUT_DIR / "partidos.csv"
STATE_FILE = OUTPUT_DIR / "api_football_state.json"

# Temporadas que el plan Free permite consultar como historico.
FREE_SEASONS = (2022, 2023, 2024)

# Codigo interno -> (id en API-FOOTBALL, nombre legible)
# Los ids estan verificados contra el catalogo /leagues, no adivinados.
LEAGUES = {
    "COL": (239, "Primera A (Colombia)"),
    "COLB": (240, "Primera B (Colombia)"),
    "PL": (39, "Premier League"),
    "ELC": (40, "Championship"),
    "PD": (140, "LaLiga"),
    "SA": (135, "Serie A"),
    "BL1": (78, "Bundesliga"),
    "BL2": (79, "2. Bundesliga"),
    "FL1": (61, "Ligue 1"),
    "DED": (88, "Eredivisie"),
    "PPL": (94, "Primeira Liga"),
    "JPL": (144, "Jupiler Pro League"),
    "SPFL": (179, "Scottish Premiership"),
    "BSA": (71, "Brasileirao"),
    "ARG": (128, "Liga Profesional Argentina"),
    "MEX": (262, "Liga MX"),
    "MLS": (253, "Major League Soccer"),
    "CL": (2, "Champions League"),
    "EL": (3, "Europa League"),
    "CLI": (13, "Copa Libertadores"),
    "CSU": (11, "Copa Sudamericana"),
}

# Lo que se descarga si no se pasa --leagues.
DEFAULT_LEAGUES = [
    "COL", "PL", "PD", "SA", "BL1", "FL1", "DED", "PPL",
    "BSA", "ARG", "MEX", "CL", "EL", "CLI", "CSU",
]

# Estado de API-FOOTBALL -> estado en el esquema del proyecto.
STATUS_MAP = {
    "TBD": "SCHEDULED", "NS": "SCHEDULED",
    "1H": "IN_PLAY", "2H": "IN_PLAY", "ET": "IN_PLAY", "BT": "IN_PLAY",
    "P": "IN_PLAY", "LIVE": "IN_PLAY", "INT": "IN_PLAY",
    "HT": "PAUSED",
    "FT": "FINISHED", "AET": "FINISHED", "PEN": "FINISHED",
    "AWD": "FINISHED", "WO": "FINISHED",
    "PST": "POSTPONED", "SUSP": "SUSPENDED", "ABD": "SUSPENDED",
    "CANC": "CANCELLED",
}

# Etiqueta que usa API-FOOTBALL -> sufijo de columna en el dataset.
STAT_COLUMNS = {
    "Shots on Goal": "tiros_arco",
    "Shots off Goal": "tiros_fuera",
    "Total Shots": "tiros",
    "Blocked Shots": "tiros_bloqueados",
    "Shots insidebox": "tiros_dentro_area",
    "Shots outsidebox": "tiros_fuera_area",
    "Fouls": "faltas",
    "Corner Kicks": "corners",
    "Offsides": "fuera_juego",
    "Ball Possession": "posesion",
    "Yellow Cards": "amarillas",
    "Red Cards": "rojas",
    "Goalkeeper Saves": "atajadas",
    "Total passes": "pases_totales",
    "Passes accurate": "pases_completados",
    "Passes %": "pases_precision",
    "expected_goals": "xg",
    "goals_prevented": "goles_evitados",
}


def load_api_key():
    env_key = os.getenv("API_FOOTBALL_KEY")
    if env_key:
        return env_key.strip()
    if API_KEY_FILE.exists():
        return API_KEY_FILE.read_text(encoding="utf-8").strip()
    return None


class PlanLimit(RuntimeError):
    """El plan no da acceso a lo pedido (temporada o fecha fuera de rango)."""


class QuotaExhausted(RuntimeError):
    """Se acabaron las solicitudes del dia."""


class ApiFootballClient:
    def __init__(self, api_key, pause_seconds=6.5):
        self.session = requests.Session()
        self.session.headers.update({"x-apisports-key": api_key})
        self.pause_seconds = pause_seconds
        self.requests_made = 0

    def get(self, endpoint, params=None, retries=2, retry_wait=15):
        attempt = 0
        while True:
            try:
                response = self.session.get(
                    f"{BASE_URL}{endpoint}", params=params, timeout=30
                )
                break
            except requests.exceptions.RequestException as error:
                if attempt >= retries:
                    raise
                attempt += 1
                print(
                    f"    Corte de conexion ({error.__class__.__name__}), "
                    f"reintento {attempt}/{retries} en {retry_wait}s..."
                )
                time.sleep(retry_wait)

        self.requests_made += 1

        if response.status_code == 429:
            raise QuotaExhausted("La API respondio 429 (demasiadas solicitudes).")

        response.raise_for_status()
        payload = response.json()

        errors = payload.get("errors") or {}
        if isinstance(errors, dict) and errors:
            message = " | ".join(f"{key}: {value}" for key, value in errors.items())
            if "requests" in errors or "limit" in message.lower():
                raise QuotaExhausted(message)
            if "plan" in errors or "season" in errors or "date" in errors:
                raise PlanLimit(message)
            raise RuntimeError(message)

        time.sleep(self.pause_seconds)
        return payload

    def status(self):
        # /status no consume cuota, asi que no aplicamos la pausa.
        response = self.session.get(f"{BASE_URL}/status", timeout=30)
        response.raise_for_status()
        return response.json().get("response", {})

    def fixtures(self, **params):
        return self.get("/fixtures", params).get("response", [])

    def fixture_statistics(self, fixture_id):
        return self.get("/fixtures/statistics", {"fixture": fixture_id}).get("response", [])


def parse_stat_value(value):
    """Convierte '52%' -> 52.0, '1.35' -> 1.35, None -> None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def league_code_for(league_id):
    for code, (lid, _) in LEAGUES.items():
        if lid == league_id:
            return code
    return str(league_id)


def flatten_fixture(item):
    """Convierte la respuesta de API-FOOTBALL al esquema del proyecto."""
    fixture = item.get("fixture") or {}
    league = item.get("league") or {}
    teams = item.get("teams") or {}
    goals = item.get("goals") or {}
    score = item.get("score") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    status = fixture.get("status") or {}
    venue = fixture.get("venue") or {}

    if home.get("winner") is True:
        winner = "HOME_TEAM"
    elif away.get("winner") is True:
        winner = "AWAY_TEAM"
    elif home.get("winner") is False and away.get("winner") is False:
        winner = "DRAW"
    else:
        winner = None

    extra = score.get("extratime") or {}
    penalty = score.get("penalty") or {}
    duration = "PENALTY_SHOOTOUT" if penalty.get("home") is not None else (
        "EXTRA_TIME" if extra.get("home") is not None else "REGULAR"
    )

    return {
        "match_id": fixture.get("id"),
        "fecha_utc": fixture.get("date"),
        "estado": STATUS_MAP.get(status.get("short"), status.get("short")),
        "estado_api": status.get("short"),
        "minuto": status.get("elapsed"),
        "tiempo_extra": status.get("extra"),
        "estadio": venue.get("name"),
        "ciudad": venue.get("city"),
        "jornada": None,
        "fase": league.get("round"),
        "grupo": None,
        "area": league.get("country"),
        "competicion_id": league.get("id"),
        "competicion": league.get("name"),
        "competicion_codigo": league_code_for(league.get("id")),
        "temporada": league.get("season"),
        "equipo_local_id": home.get("id"),
        "equipo_local": home.get("name"),
        "equipo_visitante_id": away.get("id"),
        "equipo_visitante": away.get("name"),
        "ganador": winner,
        "duracion": duration,
        "goles_local_final": goals.get("home"),
        "goles_visitante_final": goals.get("away"),
        "goles_local_descanso": (score.get("halftime") or {}).get("home"),
        "goles_visitante_descanso": (score.get("halftime") or {}).get("away"),
        "goles_local_regular": (score.get("fulltime") or {}).get("home"),
        "goles_visitante_regular": (score.get("fulltime") or {}).get("away"),
        "goles_local_extra": extra.get("home"),
        "goles_visitante_extra": extra.get("away"),
        "penales_local": penalty.get("home"),
        "penales_visitante": penalty.get("away"),
        "arbitros": fixture.get("referee"),
    }


def flatten_statistics(blocks):
    """[{team, statistics:[{type,value}]}, ...] -> {corners_local: 5, ...}"""
    row = {}
    for index, block in enumerate(blocks):
        side = "local" if index == 0 else "visitante"
        for entry in block.get("statistics", []):
            column = STAT_COLUMNS.get(entry.get("type"))
            if column:
                row[f"{column}_{side}"] = parse_stat_value(entry.get("value"))
    return row


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {"sin_estadisticas": []}


def save_state(state):
    OUTPUT_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def load_dataset():
    if DATASET.exists():
        return pd.read_csv(DATASET)
    return pd.DataFrame()


def save_dataset(dataframe):
    OUTPUT_DIR.mkdir(exist_ok=True)
    dataframe = dataframe.sort_values("fecha_utc").reset_index(drop=True)
    dataframe.to_csv(DATASET, index=False, encoding="utf-8-sig")
    return DATASET


def upsert(existing, new_rows):
    """Mezcla filas nuevas sobre el dataset, sin perder columnas ya rellenadas.

    Los backfill de resultados no traen estadisticas; si sobrescribieran la fila
    entera borrarian los corners y tarjetas que el modo stats ya habia guardado.
    Por eso se combinan campo por campo, dejando ganar al valor no nulo.
    """
    incoming = pd.DataFrame(new_rows)
    if incoming.empty:
        return existing, 0, 0

    incoming = incoming.drop_duplicates(subset="match_id", keep="last")

    if existing.empty:
        return incoming, len(incoming), 0

    known_ids = set(existing["match_id"].dropna().astype("int64"))
    incoming_ids = set(incoming["match_id"].dropna().astype("int64"))

    added = len(incoming_ids - known_ids)
    updated = len(incoming_ids & known_ids)

    # combine_first deja ganar al valor nuevo y cae al viejo cuando el nuevo es
    # nulo, que es justo lo que queremos: un backfill de resultados no debe
    # borrar los corners que el modo stats ya habia guardado.
    merged = (
        incoming.set_index("match_id")
        .combine_first(existing.set_index("match_id"))
        .reset_index()
    )

    # combine_first ordena las columnas alfabeticamente; recuperamos el orden util.
    ordered = [c for c in existing.columns if c in merged.columns]
    ordered += [c for c in merged.columns if c not in ordered]
    return merged[ordered], added, updated


def report_quota(client, label=""):
    try:
        info = client.status()
    except Exception:
        return None
    requests_info = info.get("requests", {})
    current = requests_info.get("current")
    limit = requests_info.get("limit_day")
    plan = info.get("subscription", {}).get("plan")
    print(f"  Cuota{label}: {current}/{limit} solicitudes usadas hoy (plan {plan}).")
    if current is not None and limit is not None:
        return limit - current
    return None


def resolve_leagues(codes):
    resolved = []
    for code in codes:
        code = code.strip().upper()
        if code not in LEAGUES:
            raise SystemExit(
                f"Codigo de liga desconocido: {code}. "
                f"Disponibles: {', '.join(sorted(LEAGUES))}"
            )
        resolved.append(code)
    return resolved


def mode_backfill(client, args):
    """Resultados historicos. 1 solicitud por liga-temporada."""
    codes = resolve_leagues(args.leagues or DEFAULT_LEAGUES)
    seasons = [int(s) for s in (args.seasons or FREE_SEASONS)]

    fuera_de_plan = [s for s in seasons if s not in FREE_SEASONS]
    if fuera_de_plan and not args.permitir_temporadas_pagas:
        print(
            f"Aviso: las temporadas {fuera_de_plan} no estan en el plan Free "
            f"(solo {list(FREE_SEASONS)}). Se intentaran igual y se marcaran si fallan."
        )

    print(f"Ligas: {', '.join(codes)}")
    print(f"Temporadas: {', '.join(str(s) for s in seasons)}")
    print(f"Solicitudes estimadas: {len(codes) * len(seasons)}\n")

    rows = []
    total = len(codes) * len(seasons)
    done = 0

    for code in codes:
        league_id, label = LEAGUES[code]
        for season in seasons:
            done += 1
            print(f"[{done}/{total}] {label} temporada {season}...", end=" ", flush=True)
            try:
                fixtures = client.fixtures(league=league_id, season=season)
            except PlanLimit as error:
                print(f"sin acceso ({error})")
                continue
            except QuotaExhausted as error:
                print(f"\n\nCuota agotada: {error}")
                print("Los datos traidos hasta aca se guardan igual.")
                break
            except Exception as error:
                print(f"error: {error}")
                continue

            rows.extend(flatten_fixture(item) for item in fixtures)
            print(f"{len(fixtures)} partidos")
        else:
            continue
        break

    return rows


def mode_daily(client, args):
    """Ventana de hoy a hoy+2: unica via del plan Free a la temporada en curso."""
    codes = set(resolve_leagues(args.leagues or DEFAULT_LEAGUES))
    wanted_ids = {LEAGUES[code][0] for code in codes}

    rows = []
    for offset in range(0, args.dias):
        day = date.today() + timedelta(days=offset)
        print(f"Fecha {day}...", end=" ", flush=True)
        try:
            fixtures = client.fixtures(date=str(day))
        except PlanLimit as error:
            print(f"fuera de la ventana permitida ({error})")
            continue
        except QuotaExhausted as error:
            print(f"\nCuota agotada: {error}")
            break

        if args.todas_las_ligas:
            selected = fixtures
        else:
            selected = [f for f in fixtures if (f.get("league") or {}).get("id") in wanted_ids]

        print(f"{len(fixtures)} partidos en total, {len(selected)} de tus ligas")
        rows.extend(flatten_fixture(item) for item in selected)

    return rows


def mode_stats(client, args):
    """Rellena estadisticas partido por partido. Reanudable y consciente de la cuota."""
    existing = load_dataset()
    if existing.empty:
        raise SystemExit(
            "El dataset esta vacio. Corre primero:\n"
            "  python .\\api_football.py --mode backfill"
        )

    state = load_state()
    sin_datos = set(state.get("sin_estadisticas", []))

    finished = existing[existing["estado"].eq("FINISHED")].copy()

    # Un partido esta pendiente si nunca le pedimos estadisticas con exito.
    if "corners_local" in finished.columns:
        pending = finished[finished["corners_local"].isna()]
    else:
        pending = finished

    pending_ids = [
        int(mid) for mid in pending["match_id"].dropna().astype("int64")
        if int(mid) not in sin_datos
    ]

    if args.leagues:
        codes = set(resolve_leagues(args.leagues))
        allowed = set(
            existing[existing["competicion_codigo"].isin(codes)]["match_id"]
            .dropna().astype("int64")
        )
        pending_ids = [mid for mid in pending_ids if mid in allowed]

    if not pending_ids:
        print("No hay partidos pendientes de estadisticas. Todo al dia.")
        return []

    remaining = report_quota(client, " al empezar")
    budget = args.limite
    if remaining is not None:
        budget = min(budget, max(0, remaining - args.reserva))

    if budget <= 0:
        print(
            f"Sin cuota disponible hoy (reserva de {args.reserva} solicitudes). "
            "Volve a intentar manana."
        )
        return []

    targets = pending_ids[: budget]
    print(
        f"\nPartidos sin estadisticas: {len(pending_ids)}. "
        f"Voy a pedir {len(targets)} hoy (limite de cuota).\n"
    )

    rows = []
    for index, match_id in enumerate(targets, start=1):
        print(f"[{index}/{len(targets)}] fixture {match_id}...", end=" ", flush=True)
        try:
            blocks = client.fixture_statistics(match_id)
        except QuotaExhausted as error:
            print(f"\n\nCuota agotada: {error}")
            break
        except PlanLimit as error:
            print(f"sin acceso ({error})")
            sin_datos.add(match_id)
            continue
        except Exception as error:
            print(f"error: {error}")
            continue

        if not blocks:
            print("sin estadisticas disponibles")
            sin_datos.add(match_id)
            continue

        stats = flatten_statistics(blocks)
        stats["match_id"] = match_id
        rows.append(stats)
        corners = (
            f"corners {stats.get('corners_local')}-{stats.get('corners_visitante')}, "
            f"amarillas {stats.get('amarillas_local')}-{stats.get('amarillas_visitante')}"
        )
        print(corners)

    state["sin_estadisticas"] = sorted(sin_datos)
    save_state(state)

    faltan = len(pending_ids) - len(rows)
    if faltan > 0:
        print(f"\nQuedan {faltan} partidos pendientes. Volve a correr este modo manana.")

    return rows


def mode_leagues(client, args):
    print("Ligas configuradas en este proyecto:\n")
    for code, (league_id, label) in sorted(LEAGUES.items()):
        marca = "*" if code in DEFAULT_LEAGUES else " "
        print(f" {marca} {code:<5} id={league_id:<4} {label}")
    print("\n(*) incluida por defecto cuando no pasas --leagues")
    return []


def parse_args():
    parser = argparse.ArgumentParser(
        description="Recolector de partidos via API-FOOTBALL (cubre la liga colombiana).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Ejemplos:

  # Ver que ligas hay configuradas
  python .\\api_football.py --mode leagues

  # Resultados historicos de todas las ligas por defecto (barato, ~45 solicitudes)
  python .\\api_football.py --mode backfill

  # Solo la liga colombiana
  python .\\api_football.py --mode backfill --leagues COL

  # Rellenar corners y tarjetas gastando la cuota del dia (reanudable)
  python .\\api_football.py --mode stats --leagues COL

  # Mantener al dia la temporada en curso (correr a diario)
  python .\\api_football.py --mode daily
""",
    )
    parser.add_argument(
        "--mode",
        choices=["backfill", "stats", "daily", "leagues", "quota"],
        default="daily",
        help="backfill: resultados historicos. stats: rellena estadisticas por partido. "
        "daily: ventana de la temporada en curso. leagues: lista ligas. quota: cuota restante.",
    )
    parser.add_argument(
        "--leagues", nargs="+",
        help=f"Codigos de liga. Por defecto: {' '.join(DEFAULT_LEAGUES)}",
    )
    parser.add_argument(
        "--seasons", nargs="+",
        help=f"Temporadas para backfill. Por defecto: {' '.join(str(s) for s in FREE_SEASONS)}",
    )
    parser.add_argument(
        "--dias", type=int, default=3,
        help="Cuantos dias hacia adelante cosechar en modo daily. Por defecto: 3 (el maximo del plan Free).",
    )
    parser.add_argument(
        "--todas-las-ligas", action="store_true",
        help="En modo daily, guarda los partidos de las 260 ligas de la ventana, no solo las tuyas.",
    )
    parser.add_argument(
        "--limite", type=int, default=200,
        help="Tope de partidos a consultar en modo stats. Por defecto: 200 (la cuota manda igual).",
    )
    parser.add_argument(
        "--reserva", type=int, default=5,
        help="Solicitudes que se dejan sin gastar como margen. Por defecto: 5.",
    )
    parser.add_argument(
        "--pausa", type=float, default=6.5,
        help="Segundos entre solicitudes (el plan Free limita a ~10 por minuto). Por defecto: 6.5.",
    )
    parser.add_argument(
        "--permitir-temporadas-pagas", action="store_true",
        help="No avisar cuando pidas temporadas fuera del plan Free.",
    )
    return parser.parse_args()


def main():
    api_key = load_api_key()
    if not api_key:
        raise SystemExit(
            "Falta la API key de API-FOOTBALL.\n"
            "Conseguila gratis en https://dashboard.api-football.com/register y despues:\n"
            f"  - guardala en un archivo '{API_KEY_FILE}' dentro de la carpeta del proyecto, o\n"
            "  - defini la variable de entorno API_FOOTBALL_KEY."
        )

    args = parse_args()
    client = ApiFootballClient(api_key, pause_seconds=args.pausa)

    if args.mode == "leagues":
        mode_leagues(client, args)
        return

    if args.mode == "quota":
        report_quota(client)
        return

    handlers = {"backfill": mode_backfill, "stats": mode_stats, "daily": mode_daily}
    rows = handlers[args.mode](client, args)

    if not rows:
        print("\nNo hay filas nuevas para guardar.")
        report_quota(client, " al terminar")
        return

    existing = load_dataset()
    merged, added, updated = upsert(existing, rows)
    path = save_dataset(merged)

    print(f"\nPartidos nuevos: {added}")
    print(f"Partidos actualizados: {updated}")
    print(f"Total en el dataset: {len(merged)}")
    print(f"Guardado en: {path}")

    if "corners_local" in merged.columns:
        con_stats = merged["corners_local"].notna().sum()
        finalizados = merged["estado"].eq("FINISHED").sum()
        print(f"Con estadisticas completas: {con_stats} de {finalizados} finalizados")

    print(f"Solicitudes hechas en esta corrida: {client.requests_made}")
    report_quota(client, " al terminar")


if __name__ == "__main__":
    main()
