import argparse
import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests


BASE_URL = "https://api.football-data.org/v4"
API_KEY_FILE = Path("api_key.txt")
OUTPUT_DIR = Path("data")


def _load_api_key():
    env_key = os.getenv("FOOTBALL_DATA_API_KEY")
    if env_key:
        return env_key.strip()

    if API_KEY_FILE.exists():
        return API_KEY_FILE.read_text(encoding="utf-8").strip()

    return None


API_KEY = _load_api_key()


def current_season_start_year():
    today = date.today()
    if today.month >= 7:
        return today.year
    return today.year - 1


def seasons_from(start_year):
    current = current_season_start_year()
    return [str(year) for year in range(int(start_year), current + 1)]


class FootballDataClient:
    def __init__(self, api_key):
        self.session = requests.Session()
        self.session.headers.update({"X-Auth-Token": api_key})

    def get(self, endpoint, params=None):
        url = f"{BASE_URL}{endpoint}"
        response = self.session.get(url, params=params, timeout=30)

        if response.status_code == 429:
            wait_seconds = int(response.headers.get("X-RequestCounter-Reset", "60"))
            raise RuntimeError(
                f"Limite de API alcanzado. Espera {wait_seconds} segundos y vuelve a intentar."
            )

        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            detail = response.text
            try:
                payload = response.json()
                detail = payload.get("message") or payload.get("error") or detail
            except ValueError:
                pass

            raise requests.HTTPError(
                f"{response.status_code} {response.reason} en {response.url}: {detail}"
            ) from error

        return response.json()

    def competitions(self):
        return self.get("/competitions").get("competitions", [])

    def competition(self, competition_code):
        return self.get(f"/competitions/{competition_code}")

    def matches(self, date_from=None, date_to=None, status=None, competitions=None):
        params = {}
        if date_from:
            params["dateFrom"] = date_from
        if date_to:
            params["dateTo"] = date_to
        if status:
            params["status"] = status
        if competitions:
            params["competitions"] = ",".join(competitions)

        return self.get("/matches", params=params).get("matches", [])

    def competition_matches(self, competition_code, season=None, status=None):
        params = {}
        if season:
            params["season"] = season
        if status:
            params["status"] = status

        return self.get(f"/competitions/{competition_code}/matches", params=params).get(
            "matches", []
        )

    def match_detail(self, match_id):
        return self.get(f"/matches/{match_id}")


def nested_get(data, path, default=None):
    value = data
    for key in path:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
        if value is None:
            return default
    return value


def flatten_match(match):
    score = match.get("score") or {}
    odds = match.get("odds") or {}
    home_team = match.get("homeTeam") or {}
    away_team = match.get("awayTeam") or {}
    home_stats = home_team.get("statistics") or {}
    away_stats = away_team.get("statistics") or {}
    competition = match.get("competition") or {}
    area = match.get("area") or {}
    season = match.get("season") or {}

    return {
        "match_id": match.get("id"),
        "fecha_utc": match.get("utcDate"),
        "estado": match.get("status"),
        "minuto": match.get("minute"),
        "tiempo_extra": match.get("injuryTime"),
        "asistencia": match.get("attendance"),
        "estadio": match.get("venue"),
        "jornada": match.get("matchday"),
        "fase": match.get("stage"),
        "grupo": match.get("group"),
        "ultima_actualizacion": match.get("lastUpdated"),
        "area_id": area.get("id"),
        "area": area.get("name"),
        "area_codigo": area.get("code"),
        "competicion_id": competition.get("id"),
        "competicion": competition.get("name"),
        "competicion_codigo": competition.get("code"),
        "competicion_tipo": competition.get("type"),
        "temporada_id": season.get("id"),
        "temporada_inicio": season.get("startDate"),
        "temporada_fin": season.get("endDate"),
        "equipo_local_id": home_team.get("id"),
        "equipo_local": home_team.get("name"),
        "equipo_local_corto": home_team.get("shortName"),
        "equipo_local_tla": home_team.get("tla"),
        "equipo_visitante_id": away_team.get("id"),
        "equipo_visitante": away_team.get("name"),
        "equipo_visitante_corto": away_team.get("shortName"),
        "equipo_visitante_tla": away_team.get("tla"),
        "ganador": score.get("winner"),
        "duracion": score.get("duration"),
        "goles_local_final": nested_get(score, ["fullTime", "home"]),
        "goles_visitante_final": nested_get(score, ["fullTime", "away"]),
        "goles_local_descanso": nested_get(score, ["halfTime", "home"]),
        "goles_visitante_descanso": nested_get(score, ["halfTime", "away"]),
        "goles_local_regular": nested_get(score, ["regularTime", "home"]),
        "goles_visitante_regular": nested_get(score, ["regularTime", "away"]),
        "goles_local_extra": nested_get(score, ["extraTime", "home"]),
        "goles_visitante_extra": nested_get(score, ["extraTime", "away"]),
        "penales_local": nested_get(score, ["penalties", "home"]),
        "penales_visitante": nested_get(score, ["penalties", "away"]),
        "cuota_local": odds.get("homeWin"),
        "cuota_empate": odds.get("draw"),
        "cuota_visitante": odds.get("awayWin"),
        "arbitros": ", ".join(
            referee.get("name", "")
            for referee in match.get("referees", [])
            if referee.get("name")
        ),
        "cantidad_goles_eventos": len(match.get("goals", [])),
        "cantidad_tarjetas": len(match.get("bookings", [])),
        "cantidad_cambios": len(match.get("substitutions", [])),
        "corners_local": home_stats.get("corner_kicks"),
        "corners_visitante": away_stats.get("corner_kicks"),
        "faltas_local": home_stats.get("fouls"),
        "faltas_visitante": away_stats.get("fouls"),
        "tiros_local": home_stats.get("shots"),
        "tiros_visitante": away_stats.get("shots"),
        "tiros_arco_local": home_stats.get("shots_on_goal"),
        "tiros_arco_visitante": away_stats.get("shots_on_goal"),
        "posesion_local": home_stats.get("ball_possession"),
        "posesion_visitante": away_stats.get("ball_possession"),
        "amarillas_local": home_stats.get("yellow_cards"),
        "amarillas_visitante": away_stats.get("yellow_cards"),
        "doble_amarilla_local": home_stats.get("yellow_red_cards"),
        "doble_amarilla_visitante": away_stats.get("yellow_red_cards"),
        "rojas_local": home_stats.get("red_cards"),
        "rojas_visitante": away_stats.get("red_cards"),
    }


def with_timestamp(path):
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return path.with_name(f"{path.stem}_{timestamp}{path.suffix}")


def save_dataset(matches, output_name):
    OUTPUT_DIR.mkdir(exist_ok=True)
    raw_path = OUTPUT_DIR / f"{output_name}.json"
    csv_path = OUTPUT_DIR / f"{output_name}.csv"
    excel_path = OUTPUT_DIR / f"{output_name}.xlsx"

    raw_path.write_text(json.dumps(matches, indent=2, ensure_ascii=False), encoding="utf-8")

    dataframe = pd.DataFrame(flatten_match(match) for match in matches)
    dataframe.to_csv(csv_path, index=False, encoding="utf-8-sig")

    try:
        dataframe.to_excel(excel_path, index=False)
    except PermissionError:
        locked_path = excel_path
        excel_path = with_timestamp(excel_path)
        dataframe.to_excel(excel_path, index=False)
        print(
            f"No pude sobrescribir {locked_path}. "
            f"Probablemente esta abierto en Excel. Guarde una copia en {excel_path}."
        )

    return dataframe, raw_path, csv_path, excel_path


def print_empty_dataset_hint(args):
    print("No llegaron partidos para esos filtros.")
    print("Revisa estas causas comunes:")
    print("- Para historicos usa --mode competition o --mode history, no solo --mode range.")
    print("- La temporada se pasa como el ano inicial: 2023 significa temporada 2023/24.")
    print("- Tu plan de football-data.org puede no incluir historicos de esa temporada.")
    print("- Algunas competiciones no tienen datos historicos disponibles para todos los anos.")
    print("Comando de prueba recomendado:")
    print(
        f"python .\\API-Football.py --mode competition-info --competition {args.competition}"
    )


STATISTICS_FIELDS = [
    "corner_kicks",
    "free_kicks",
    "goal_kicks",
    "offsides",
    "fouls",
    "ball_possession",
    "saves",
    "throw_ins",
    "shots",
    "shots_on_goal",
    "shots_off_goal",
    "yellow_cards",
    "yellow_red_cards",
    "red_cards",
]


def test_match_statistics(client, competition_code, season=None, sample_size=5, pause_seconds=6):
    print(f"Buscando los ultimos {sample_size} partidos finalizados de {competition_code}...")
    matches = client.competition_matches(competition_code, season=season, status="FINISHED")
    if not matches:
        print("No encontre partidos finalizados para esa competicion.")
        return

    sample = matches[-sample_size:]
    any_data_found = False

    for index, match in enumerate(sample, start=1):
        match_id = match.get("id")
        home_name = nested_get(match, ["homeTeam", "name"], "?")
        away_name = nested_get(match, ["awayTeam", "name"], "?")
        print(f"\n[{index}/{len(sample)}] {home_name} vs {away_name} (id={match_id})")

        detail = client.match_detail(match_id)
        home_stats = nested_get(detail, ["homeTeam", "statistics"], {}) or {}
        away_stats = nested_get(detail, ["awayTeam", "statistics"], {}) or {}

        if not home_stats and not away_stats:
            print("  Sin objeto 'statistics' en la respuesta (vacio).")
        else:
            any_data_found = True
            for field in STATISTICS_FIELDS:
                home_value = home_stats.get(field)
                away_value = away_stats.get(field)
                if home_value is not None or away_value is not None:
                    print(f"  {field}: local={home_value} visitante={away_value}")

        if index < len(sample):
            time.sleep(pause_seconds)

    print("")
    if any_data_found:
        print(
            "Tu plan SI entrega estadisticas por partido via el endpoint de detalle. "
            "Se puede armar un modo de recoleccion que las incluya (mas lento, 1 llamada por partido)."
        )
    else:
        print(
            "Tu plan no esta entregando estadisticas (corners, tarjetas, tiros libres, etc.) "
            "ni siquiera en el endpoint de detalle. Es una limitacion del plan Free, no del codigo."
        )


def _fetch_with_retry(fetch, retries=2, retry_wait=15):
    attempt = 0
    while True:
        try:
            return fetch()
        except requests.HTTPError:
            raise
        except requests.exceptions.RequestException as error:
            if attempt >= retries:
                raise error
            attempt += 1
            print(f"  Corte de conexion ({error.__class__.__name__}), reintento {attempt}/{retries} en {retry_wait}s...")
            time.sleep(retry_wait)


def collect_all_competition_matches(client, season=None, status=None, pause_seconds=6):
    all_matches = []
    competitions = client.competitions()

    for index, competition in enumerate(competitions, start=1):
        code = competition.get("code")
        name = competition.get("name")
        if not code:
            continue

        print(f"[{index}/{len(competitions)}] Descargando {name} ({code})...")
        try:
            matches = _fetch_with_retry(
                lambda: client.competition_matches(code, season=season, status=status)
            )
            all_matches.extend(matches)
        except requests.exceptions.RequestException as error:
            print(f"  No se pudo descargar {code}: {error}")

        time.sleep(pause_seconds)

    unique_matches = {match["id"]: match for match in all_matches if match.get("id")}
    return list(unique_matches.values())


def collect_competition_history(client, competition_code, seasons, status=None, pause_seconds=6):
    all_matches = []

    for index, season in enumerate(seasons, start=1):
        print(f"[{index}/{len(seasons)}] Descargando {competition_code} temporada {season}...")
        try:
            matches = _fetch_with_retry(
                lambda: client.competition_matches(
                    competition_code,
                    season=str(season),
                    status=status,
                )
            )
            all_matches.extend(matches)
        except requests.exceptions.RequestException as error:
            print(f"  No se pudo descargar {competition_code} {season}: {error}")

        time.sleep(pause_seconds)

    unique_matches = {match["id"]: match for match in all_matches if match.get("id")}
    return list(unique_matches.values())


def collect_all_competitions_history(client, seasons, status=None, pause_seconds=6):
    all_matches = []
    competitions = client.competitions()
    available_competitions = [
        competition
        for competition in competitions
        if competition.get("code")
    ]
    total_requests = len(available_competitions) * len(seasons)
    request_number = 0

    for competition in available_competitions:
        code = competition["code"]
        name = competition.get("name", code)

        for season in seasons:
            request_number += 1
            print(
                f"[{request_number}/{total_requests}] "
                f"Descargando {name} ({code}) temporada {season}..."
            )
            try:
                matches = _fetch_with_retry(
                    lambda: client.competition_matches(
                        code,
                        season=str(season),
                        status=status,
                    )
                )
                all_matches.extend(matches)
            except requests.exceptions.RequestException as error:
                print(f"  No se pudo descargar {code} {season}: {error}")

            time.sleep(pause_seconds)

    unique_matches = {match["id"]: match for match in all_matches if match.get("id")}
    return list(unique_matches.values())


def parse_args():
    parser = argparse.ArgumentParser(
        description="Recolector de partidos de football-data.org para pronosticos deportivos."
    )
    parser.add_argument(
        "--mode",
        choices=[
            "range",
            "competition",
            "history",
            "recent-history",
            "recent-all",
            "all-competitions",
            "competition-info",
            "test-stats",
        ],
        default="recent-all",
        help="recent-all trae todas las competiciones disponibles desde --from-season; range trae partidos por fechas; competition trae una liga; history trae varias temporadas; recent-history trae una liga desde --from-season; all-competitions recorre todas las competiciones de una temporada; competition-info muestra temporadas disponibles.",
    )
    parser.add_argument("--date-from", default=str(date.today()))
    parser.add_argument("--date-to", default=str(date.today() + timedelta(days=7)))
    parser.add_argument("--competition", default="PL", help="Codigo de competicion, ejemplo: PL, CL, PD, SA, BL1.")
    parser.add_argument("--season", help="Ano inicial de temporada, ejemplo: 2025.")
    parser.add_argument(
        "--from-season",
        default="2024",
        help="Ano inicial para recent-history. Por defecto: 2024.",
    )
    parser.add_argument(
        "--seasons",
        nargs="+",
        help="Lista de temporadas para historicos, ejemplo: --seasons 2021 2022 2023 2024 2025.",
    )
    parser.add_argument(
        "--status",
        choices=["SCHEDULED", "LIVE", "IN_PLAY", "PAUSED", "FINISHED", "POSTPONED", "SUSPENDED", "CANCELLED"],
        help="Filtra por estado del partido.",
    )
    parser.add_argument("--output", default="partidos")
    parser.add_argument(
        "--sample-size",
        type=int,
        default=5,
        help="Cuantos partidos probar en --mode test-stats. Por defecto: 5.",
    )
    return parser.parse_args()


def main():
    if not API_KEY:
        raise SystemExit(
            "Falta la API key de football-data.org. Consigue una gratis en "
            "https://www.football-data.org/client/register y despues, en la carpeta del "
            f"proyecto, crea un archivo llamado '{API_KEY_FILE}' con la key adentro (solo eso, "
            "sin comillas ni nada mas)."
        )

    args = parse_args()
    client = FootballDataClient(API_KEY)

    if args.mode == "range":
        matches = client.matches(
            date_from=args.date_from,
            date_to=args.date_to,
            status=args.status,
        )
    elif args.mode == "competition-info":
        competition = client.competition(args.competition)
        seasons = competition.get("seasons", [])
        print(f"Competicion: {competition.get('name')} ({competition.get('code')})")
        print(f"Temporadas reportadas por la API: {len(seasons)}")
        for season in seasons:
            print(
                f"- {season.get('startDate')} a {season.get('endDate')} "
                f"| id={season.get('id')} | actual={season.get('currentMatchday')}"
            )
        return
    elif args.mode == "test-stats":
        test_match_statistics(client, args.competition, season=args.season, sample_size=args.sample_size)
        return
    elif args.mode == "competition":
        matches = client.competition_matches(
            args.competition,
            season=args.season,
            status=args.status,
        )
    elif args.mode == "history":
        if not args.seasons:
            raise SystemExit("Usa --seasons con una o mas temporadas. Ejemplo: --seasons 2021 2022 2023")
        matches = collect_competition_history(
            client,
            args.competition,
            args.seasons,
            status=args.status,
        )
    elif args.mode == "recent-history":
        seasons = seasons_from(args.from_season)
        print(f"Temporadas a descargar: {', '.join(seasons)}")
        matches = collect_competition_history(
            client,
            args.competition,
            seasons,
            status=args.status,
        )
    elif args.mode == "recent-all":
        seasons = seasons_from(args.from_season)
        print(f"Temporadas a descargar: {', '.join(seasons)}")
        matches = collect_all_competitions_history(
            client,
            seasons,
            status=args.status,
        )
    else:
        matches = collect_all_competition_matches(
            client,
            season=args.season,
            status=args.status,
        )

    dataframe, raw_path, csv_path, excel_path = save_dataset(matches, args.output)

    print(f"Partidos encontrados: {len(dataframe)}")
    print(f"JSON crudo: {raw_path}")
    print(f"CSV limpio: {csv_path}")
    print(f"Excel limpio: {excel_path}")

    if not dataframe.empty:
        print(dataframe.head())
    else:
        print_empty_dataset_hint(args)


if __name__ == "__main__":
    main()
