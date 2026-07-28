import pandas as pd

from data_loader import finished_matches


def team_match_rows(matches, team):
    home = matches[matches["equipo_local"].eq(team)].copy()
    home["side"] = "home"
    home["opponent"] = home["equipo_visitante"]
    home["goals_for"] = home["goles_local_final"]
    home["goals_against"] = home["goles_visitante_final"]
    home["result"] = home.apply(_home_result, axis=1)

    away = matches[matches["equipo_visitante"].eq(team)].copy()
    away["side"] = "away"
    away["opponent"] = away["equipo_local"]
    away["goals_for"] = away["goles_visitante_final"]
    away["goals_against"] = away["goles_local_final"]
    away["result"] = away.apply(_away_result, axis=1)

    combined = pd.concat([home, away], ignore_index=True)
    return combined.sort_values("fecha_utc")


def team_summary(matches, team, last_n=10, side=None, competition=None):
    matches = finished_matches(matches)
    if competition:
        matches = matches[matches["competicion_codigo"].eq(competition)]

    rows = team_match_rows(matches, team)
    if side:
        rows = rows[rows["side"].eq(side)]

    recent = rows.tail(last_n)
    total = len(recent)

    if total == 0:
        return {
            "team": team,
            "matches": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "points_per_match": 0.0,
            "goals_for_avg": 0.0,
            "goals_against_avg": 0.0,
            "total_goals_avg": 0.0,
            "clean_sheet_rate": 0.0,
            "over_15_rate": 0.0,
            "over_25_rate": 0.0,
            "both_score_rate": 0.0,
        }

    wins = int(recent["result"].eq("W").sum())
    draws = int(recent["result"].eq("D").sum())
    losses = int(recent["result"].eq("L").sum())
    total_goals = recent["goals_for"] + recent["goals_against"]

    return {
        "team": team,
        "matches": total,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "points_per_match": round(((wins * 3) + draws) / total, 2),
        "goals_for_avg": round(recent["goals_for"].mean(), 2),
        "goals_against_avg": round(recent["goals_against"].mean(), 2),
        "total_goals_avg": round(total_goals.mean(), 2),
        "clean_sheet_rate": round((recent["goals_against"].eq(0).mean()) * 100, 1),
        "over_15_rate": round((total_goals.gt(1.5).mean()) * 100, 1),
        "over_25_rate": round((total_goals.gt(2.5).mean()) * 100, 1),
        "both_score_rate": round(
            ((recent["goals_for"].gt(0)) & (recent["goals_against"].gt(0))).mean() * 100,
            1,
        ),
    }


def head_to_head(matches, home_team, away_team, last_n=5):
    matches = finished_matches(matches)
    direct = matches[
        (
            matches["equipo_local"].eq(home_team)
            & matches["equipo_visitante"].eq(away_team)
        )
        |
        (
            matches["equipo_local"].eq(away_team)
            & matches["equipo_visitante"].eq(home_team)
        )
    ].copy()

    direct = direct.sort_values("fecha_utc").tail(last_n)
    if direct.empty:
        return {
            "matches": 0,
            "home_team_wins": 0,
            "away_team_wins": 0,
            "draws": 0,
            "goals_avg": 0.0,
            "games": [],
        }

    home_wins = 0
    away_wins = 0
    draws = 0
    games = []

    for _, row in direct.iterrows():
        local = row["equipo_local"]
        visitor = row["equipo_visitante"]
        local_goals = int(row["goles_local_final"])
        visitor_goals = int(row["goles_visitante_final"])

        if local_goals == visitor_goals:
            draws += 1
        elif local_goals > visitor_goals and local == home_team:
            home_wins += 1
        elif local_goals < visitor_goals and visitor == home_team:
            home_wins += 1
        else:
            away_wins += 1

        games.append(
            {
                "date": row["fecha_local"].date().isoformat(),
                "home": local,
                "away": visitor,
                "score": f"{local_goals}-{visitor_goals}",
                "competition": row["competicion_codigo"],
            }
        )

    goals_avg = (direct["goles_local_final"] + direct["goles_visitante_final"]).mean()
    return {
        "matches": len(direct),
        "home_team_wins": home_wins,
        "away_team_wins": away_wins,
        "draws": draws,
        "goals_avg": round(goals_avg, 2),
        "games": games,
    }


def _home_result(row):
    if row["goles_local_final"] > row["goles_visitante_final"]:
        return "W"
    if row["goles_local_final"] == row["goles_visitante_final"]:
        return "D"
    return "L"


def _away_result(row):
    if row["goles_visitante_final"] > row["goles_local_final"]:
        return "W"
    if row["goles_visitante_final"] == row["goles_local_final"]:
        return "D"
    return "L"
