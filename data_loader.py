from datetime import timedelta, timezone
from pathlib import Path
from difflib import get_close_matches
import unicodedata

import pandas as pd


DEFAULT_DATASET = Path("data") / "partidos.csv"

LOCAL_TZ = timezone(timedelta(hours=-5))  # Colombia (Bogota), sin horario de verano

TEAM_ALIASES = {
    "barcelona": "FC Barcelona",
    "barca": "FC Barcelona",
    "real madrid": "Real Madrid CF",
    "madrid": "Real Madrid CF",
    "atletico madrid": "Club Atletico de Madrid",
    "atleti": "Club Atletico de Madrid",
    "villareal": "Villarreal CF",
    "villarreal": "Villarreal CF",
    "mallorca": "RCD Mallorca",
    "monaco": "AS Monaco FC",
    "lille": "Lille OSC",
}


def load_matches(path=DEFAULT_DATASET):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"No encontre el archivo {path}. Ejecuta primero API-Football.py para generar la data."
        )

    matches = pd.read_csv(path)
    matches["fecha_utc"] = pd.to_datetime(matches["fecha_utc"], errors="coerce", utc=True)
    matches["fecha_local"] = matches["fecha_utc"].dt.tz_convert(LOCAL_TZ)

    numeric_columns = [
        "goles_local_final",
        "goles_visitante_final",
        "jornada",
        "cantidad_tarjetas",
        "corners_local",
        "corners_visitante",
        "faltas_local",
        "faltas_visitante",
        "tiros_local",
        "tiros_visitante",
        "tiros_arco_local",
        "tiros_arco_visitante",
        "posesion_local",
        "posesion_visitante",
        "amarillas_local",
        "amarillas_visitante",
        "doble_amarilla_local",
        "doble_amarilla_visitante",
        "rojas_local",
        "rojas_visitante",
    ]
    for column in numeric_columns:
        if column in matches.columns:
            matches[column] = pd.to_numeric(matches[column], errors="coerce")

    return matches.sort_values("fecha_utc").reset_index(drop=True)


def finished_matches(matches):
    required = ["goles_local_final", "goles_visitante_final"]
    filtered = matches[matches["estado"].eq("FINISHED")].copy()
    return filtered.dropna(subset=required)


def upcoming_matches(matches):
    return matches[matches["estado"].isin(["SCHEDULED", "TIMED"])].copy()


def team_names(matches):
    teams = pd.concat([matches["equipo_local"], matches["equipo_visitante"]])
    return sorted(teams.dropna().unique().tolist())


def team_competitions(matches, team):
    games = matches[
        matches["equipo_local"].eq(team) | matches["equipo_visitante"].eq(team)
    ]
    return set(games["competicion_codigo"].dropna().unique().tolist())


def find_team(matches, query, preferred_competitions=None):
    original_query = query
    query = normalize_text(query)
    teams = team_names(matches)
    preferred_competitions = set(preferred_competitions or [])

    alias = TEAM_ALIASES.get(query)
    if alias in teams:
        return alias

    exact = [team for team in teams if normalize_text(team) == query]
    if exact:
        return best_team_candidate(matches, exact, preferred_competitions)

    contains = [team for team in teams if query in normalize_text(team)]
    if contains:
        return best_team_candidate(matches, contains, preferred_competitions)

    normalized_by_team = {normalize_text(team): team for team in teams}
    close = get_close_matches(
        query,
        normalized_by_team.keys(),
        n=5,
        cutoff=0.72,
    )
    if close:
        candidates = [normalized_by_team[item] for item in close]
        return best_team_candidate(matches, candidates, preferred_competitions)

    raise ValueError(f"No encontre un equipo parecido a '{original_query}'.")


def best_team_candidate(matches, candidates, preferred_competitions=None):
    preferred_competitions = set(preferred_competitions or [])

    def score(team):
        competitions = team_competitions(matches, team)
        preferred_score = 100 if competitions.intersection(preferred_competitions) else 0
        domestic_score = 20 if competitions.intersection({"PL", "PD", "SA", "BL1", "FL1"}) else 0
        name_score = -len(team)
        return preferred_score + domestic_score + name_score

    return sorted(candidates, key=score, reverse=True)[0]


def normalize_text(value):
    value = str(value).casefold().strip()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(character for character in value if not unicodedata.combining(character))
    return value
