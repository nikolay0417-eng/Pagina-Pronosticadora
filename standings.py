from data_loader import finished_matches


ZONE_RULES = {
    "PL": {"title": 3, "champions": 5, "europa": 6, "conference": 7, "relegation": 18},
    "PD": {"title": 3, "champions": 4, "europa": 6, "conference": 7, "relegation": 18},
    "SA": {"title": 3, "champions": 4, "europa": 6, "conference": 7, "relegation": 18},
    "BL1": {"title": 3, "champions": 4, "europa": 6, "conference": 7, "relegation": 16},
    "FL1": {"title": 3, "champions": 4, "europa": 5, "conference": 6, "relegation": 16},
    "DED": {"title": 3, "champions": 2, "europa": 4, "conference": 5, "relegation": 16},
    "PPL": {"title": 3, "champions": 2, "europa": 4, "conference": 5, "relegation": 16},
    "BSA": {"title": 4, "champions": 6, "europa": 12, "conference": 0, "relegation": 17},
    "ELC": {"title": 2, "champions": 0, "europa": 0, "conference": 0, "relegation": 22},
    # En Colombia, Argentina y Mexico el titulo se define en playoffs, asi que
    # "pelea campeonato" marca los puestos que clasifican a esa fase final.
    "COL": {"title": 8, "champions": 0, "europa": 0, "conference": 0, "relegation": 19},
    "COLB": {"title": 8, "champions": 0, "europa": 0, "conference": 0, "relegation": 0},
    "ARG": {"title": 8, "champions": 0, "europa": 0, "conference": 0, "relegation": 27},
    "MEX": {"title": 6, "champions": 0, "europa": 10, "conference": 0, "relegation": 0},
    "MLS": {"title": 9, "champions": 0, "europa": 0, "conference": 0, "relegation": 0},
    "BL2": {"title": 3, "champions": 0, "europa": 0, "conference": 0, "relegation": 16},
    "JPL": {"title": 6, "champions": 0, "europa": 0, "conference": 0, "relegation": 16},
    "SPFL": {"title": 3, "champions": 0, "europa": 0, "conference": 0, "relegation": 11},
}

DOMESTIC_LEAGUES = set(ZONE_RULES.keys())

# El recolector nuevo guarda el ano de temporada en "temporada"; el esquema
# viejo de football-data.org usaba "temporada_inicio". Aceptamos los dos para
# que los datasets guardados de antes se sigan pudiendo leer.
SEASON_COLUMNS = ("temporada", "temporada_inicio")


def season_column(matches):
    for column in SEASON_COLUMNS:
        if column in matches.columns:
            return column
    return None


def latest_competition_for_match(matches, home_team, away_team):
    home_games = matches[
        matches["equipo_local"].eq(home_team) | matches["equipo_visitante"].eq(home_team)
    ]
    away_games = matches[
        matches["equipo_local"].eq(away_team) | matches["equipo_visitante"].eq(away_team)
    ]
    common_competitions = set(home_games["competicion_codigo"].dropna()).intersection(
        set(away_games["competicion_codigo"].dropna())
    )
    if not common_competitions:
        return None

    domestic_common = common_competitions.intersection(DOMESTIC_LEAGUES)
    preferred_competitions = domestic_common or common_competitions
    common_games = matches[matches["competicion_codigo"].isin(preferred_competitions)]
    latest = common_games.groupby("competicion_codigo")["fecha_utc"].max().sort_values()
    return latest.index[-1]


def latest_season_for_competition(matches, competition):
    competition_matches = matches[matches["competicion_codigo"].eq(competition)]
    if competition_matches.empty:
        return None
    column = season_column(competition_matches)
    if not column:
        return None

    # Una tabla solo tiene sentido sobre partidos ya jugados. Cuando la temporada
    # en curso todavia no tiene resultados (pretemporada, o las primeras fechas),
    # caemos a la ultima temporada que si los tiene en vez de devolver una tabla
    # vacia.
    played = finished_matches(competition_matches)
    source = played if not played.empty else competition_matches
    return source.sort_values("fecha_utc")[column].iloc[-1]


def build_table(matches, competition, season_start=None):
    matches = finished_matches(matches)
    matches = matches[matches["competicion_codigo"].eq(competition)].copy()
    column = season_column(matches)
    if season_start is not None and column:
        matches = matches[matches[column].eq(season_start)].copy()

    table = {}
    for _, row in matches.iterrows():
        home = row["equipo_local"]
        away = row["equipo_visitante"]
        home_goals = int(row["goles_local_final"])
        away_goals = int(row["goles_visitante_final"])

        _ensure_team(table, home)
        _ensure_team(table, away)

        table[home]["played"] += 1
        table[away]["played"] += 1
        table[home]["goals_for"] += home_goals
        table[home]["goals_against"] += away_goals
        table[away]["goals_for"] += away_goals
        table[away]["goals_against"] += home_goals

        if home_goals > away_goals:
            table[home]["wins"] += 1
            table[away]["losses"] += 1
            table[home]["points"] += 3
        elif home_goals < away_goals:
            table[away]["wins"] += 1
            table[home]["losses"] += 1
            table[away]["points"] += 3
        else:
            table[home]["draws"] += 1
            table[away]["draws"] += 1
            table[home]["points"] += 1
            table[away]["points"] += 1

    rows = []
    for team, stats in table.items():
        stats["team"] = team
        stats["goal_difference"] = stats["goals_for"] - stats["goals_against"]
        rows.append(stats)

    rows.sort(
        key=lambda item: (
            item["points"],
            item["goal_difference"],
            item["goals_for"],
        ),
        reverse=True,
    )

    for position, row in enumerate(rows, start=1):
        row["position"] = position
        row["zone"] = classify_zone(competition, position, len(rows))

    return rows


def team_standing(matches, team, competition=None, season_start=None):
    if not competition:
        competition = latest_competition_for_team(matches, team)
    if not competition:
        return None

    if not season_start:
        season_start = latest_season_for_competition(matches, competition)

    table = build_table(matches, competition, season_start=season_start)
    for row in table:
        if row["team"] == team:
            row = row.copy()
            row["competition"] = competition
            row["season_start"] = season_start
            row["teams"] = len(table)
            return row

    return None


def match_standings(matches, home_team, away_team, competition=None):
    if not competition:
        competition = latest_competition_for_match(matches, home_team, away_team)

    if not competition:
        return {"competition": None, "home": None, "away": None}

    season_start = latest_season_for_competition(matches, competition)
    return {
        "competition": competition,
        "season_start": season_start,
        "home": team_standing(matches, home_team, competition, season_start),
        "away": team_standing(matches, away_team, competition, season_start),
    }


def latest_competition_for_team(matches, team):
    games = matches[
        matches["equipo_local"].eq(team) | matches["equipo_visitante"].eq(team)
    ]
    if games.empty:
        return None

    domestic_games = games[games["competicion_codigo"].isin(DOMESTIC_LEAGUES)]
    preferred = domestic_games if not domestic_games.empty else games
    latest = preferred.groupby("competicion_codigo")["fecha_utc"].max().sort_values()
    return latest.index[-1]


def classify_zone(competition, position, total_teams):
    rules = ZONE_RULES.get(competition, {})
    relegation_from = rules.get("relegation")

    if relegation_from and position >= relegation_from:
        return "zona de descenso"
    if rules.get("title") and position <= rules["title"]:
        return "pelea campeonato"
    if rules.get("champions") and position <= rules["champions"]:
        return "zona Champions"
    if rules.get("europa") and position <= rules["europa"]:
        return "zona Europa League"
    if rules.get("conference") and position <= rules["conference"]:
        return "zona Conference League"
    if position <= max(4, int(total_teams * 0.25)):
        return "parte alta"
    if position >= max(1, total_teams - 3):
        return "parte baja"
    return "mitad de tabla"


def format_standing_line(standing):
    if not standing:
        return "Sin posicion disponible en la tabla."

    return (
        f"{standing['team']}: puesto {standing['position']}/{standing['teams']} "
        f"con {standing['points']} pts, DG {standing['goal_difference']} "
        f"({standing['zone']})."
    )


def _ensure_team(table, team):
    if team not in table:
        table[team] = {
            "played": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "goals_for": 0,
            "goals_against": 0,
            "points": 0,
        }
