import itertools

import pandas as pd

from data_loader import finished_matches
from poisson_model import DEFAULT_CONFIG, save_model_config
from predictor import predict_match


MIN_HISTORY_MATCHES = 6

CALIBRATION_GRID = {
    "half_life_days": [90, 200, 365],
    "rho": [-0.03, -0.08, -0.13],
}
DEFAULT_SHRINKAGE_K = DEFAULT_CONFIG["shrinkage_k"]


def _iterate_predictions(matches, competition=None, date_from=None, date_to=None, limit=None, last_n=10, model_config=None):
    matches = matches.sort_values("fecha_utc").reset_index(drop=True)
    candidates = finished_matches(matches)

    if competition:
        candidates = candidates[candidates["competicion_codigo"].eq(competition)]
    if date_from:
        candidates = candidates[candidates["fecha_local"].dt.date.astype(str).ge(date_from)]
    if date_to:
        candidates = candidates[candidates["fecha_local"].dt.date.astype(str).le(date_to)]

    candidates = candidates.sort_values("fecha_utc")
    if limit:
        candidates = candidates.tail(limit)

    for _, match in candidates.iterrows():
        history = matches[matches["fecha_utc"].lt(match["fecha_utc"])]
        if not has_enough_history(history, match["equipo_local"], match["equipo_visitante"]):
            continue

        prediction = predict_match(
            history,
            match["equipo_local"],
            match["equipo_visitante"],
            competition=match["competicion_codigo"],
            last_n=last_n,
            include_advanced=False,
            model_config=model_config,
        )
        yield match, prediction


def evaluate_predictions(matches, competition=None, date_from=None, date_to=None, limit=None, last_n=10, model_config=None):
    records = []
    probability_records = []

    for match, prediction in _iterate_predictions(
        matches, competition, date_from, date_to, limit, last_n, model_config
    ):
        probabilities = prediction["probabilities"]
        probability_records.append(
            {
                "fecha": match["fecha_local"],
                "competicion": match["competicion_codigo"],
                "resultado": _match_outcome(match),
                "prob_local": probabilities["home_win"],
                "prob_empate": probabilities["draw"],
                "prob_visitante": probabilities["away_win"],
            }
        )

        for market in prediction["market_suggestions"]:
            result = evaluate_market(market["name"], match)
            if result is None:
                continue

            records.append(
                {
                    "fecha": match["fecha_local"],
                    "competicion": match["competicion_codigo"],
                    "local": match["equipo_local"],
                    "visitante": match["equipo_visitante"],
                    "marcador": f"{int(match['goles_local_final'])}-{int(match['goles_visitante_final'])}",
                    "mercado": market["name"],
                    "probabilidad": market["probability"],
                    "confianza": market["confidence"],
                    "acierto": result,
                }
            )

    return pd.DataFrame(records), pd.DataFrame(probability_records)


def summarize_backtest(results):
    if results.empty:
        return pd.DataFrame(
            columns=["grupo", "pronosticos", "aciertos", "precision", "prob_promedio"]
        )

    groups = []
    for group_name, group in results.groupby(results["mercado"].map(market_family)):
        picks = len(group)
        hits = int(group["acierto"].sum())
        groups.append(
            {
                "grupo": group_name,
                "pronosticos": picks,
                "aciertos": hits,
                "precision": round((hits / picks) * 100, 1),
                "prob_promedio": round(group["probabilidad"].mean(), 1),
            }
        )

    summary = pd.DataFrame(groups).sort_values(
        ["precision", "pronosticos"],
        ascending=[False, False],
    )
    return summary.reset_index(drop=True)


def summarize_by_confidence(results):
    if results.empty:
        return pd.DataFrame(
            columns=["confianza", "pronosticos", "aciertos", "precision", "prob_promedio"]
        )

    rows = []
    for confidence, group in results.groupby("confianza"):
        picks = len(group)
        hits = int(group["acierto"].sum())
        rows.append(
            {
                "confianza": confidence,
                "pronosticos": picks,
                "aciertos": hits,
                "precision": round((hits / picks) * 100, 1),
                "prob_promedio": round(group["probabilidad"].mean(), 1),
            }
        )

    return pd.DataFrame(rows).sort_values("precision", ascending=False).reset_index(drop=True)


def _match_outcome(match):
    home_goals = int(match["goles_local_final"])
    away_goals = int(match["goles_visitante_final"])
    if home_goals > away_goals:
        return "local"
    if home_goals < away_goals:
        return "visitante"
    return "empate"


def brier_score(probabilities):
    if probabilities.empty:
        return None

    errors = []
    for _, row in probabilities.iterrows():
        actual = {"local": 0.0, "empate": 0.0, "visitante": 0.0}
        actual[row["resultado"]] = 1.0
        predicted = {
            "local": row["prob_local"] / 100,
            "empate": row["prob_empate"] / 100,
            "visitante": row["prob_visitante"] / 100,
        }
        errors.append(sum((predicted[key] - actual[key]) ** 2 for key in actual))

    return round(sum(errors) / len(errors), 4)


def calibrate_model(matches, competition=None, limit=70):
    best = None

    for half_life_days, rho in itertools.product(
        CALIBRATION_GRID["half_life_days"],
        CALIBRATION_GRID["rho"],
    ):
        config = {"half_life_days": half_life_days, "rho": rho, "shrinkage_k": DEFAULT_SHRINKAGE_K}
        _results, probabilities = evaluate_predictions(
            matches,
            competition=competition,
            limit=limit,
            model_config=config,
        )
        score = brier_score(probabilities)
        if score is None:
            continue

        if best is None or score < best["brier_score"]:
            best = {**config, "brier_score": score, "sample_size": len(probabilities)}

    if best:
        save_model_config({key: best[key] for key in DEFAULT_CONFIG})

    return best


def has_enough_history(history, home_team, away_team):
    home_count = count_team_matches(history, home_team)
    away_count = count_team_matches(history, away_team)
    return home_count >= MIN_HISTORY_MATCHES and away_count >= MIN_HISTORY_MATCHES


def count_team_matches(matches, team):
    return int(
        (
            matches["equipo_local"].eq(team)
            | matches["equipo_visitante"].eq(team)
        ).sum()
    )


def evaluate_market(market_name, match):
    home_goals = int(match["goles_local_final"])
    away_goals = int(match["goles_visitante_final"])
    total_goals = home_goals + away_goals
    home = match["equipo_local"]
    away = match["equipo_visitante"]

    if market_name == "empate":
        return home_goals == away_goals
    if market_name == f"{home} gana":
        return home_goals > away_goals
    if market_name == f"{away} gana":
        return away_goals > home_goals
    if market_name == f"{home} o empate":
        return home_goals >= away_goals
    if market_name == f"{away} o empate":
        return away_goals >= home_goals
    if market_name == "Over 1.5 goles":
        return total_goals > 1.5
    if market_name == "Over 2.5 goles":
        return total_goals > 2.5
    if market_name == "Ambos equipos marcan":
        return home_goals > 0 and away_goals > 0

    return None


def market_family(market_name):
    if market_name in ["Over 1.5 goles", "Over 2.5 goles"]:
        return market_name
    if market_name == "Ambos equipos marcan":
        return market_name
    if " o empate" in market_name:
        return "Doble oportunidad"
    if market_name == "empate":
        return "Empate"
    if market_name.endswith(" gana"):
        return "Ganador"
    return "Otro"


def format_backtest(summary, confidence_summary, sample_size, brier=None):
    lines = [
        "Backtest del agente",
        f"Pronosticos evaluados: {sample_size}",
        "",
        "Precision por mercado:",
    ]

    if summary.empty:
        lines.append("- No hubo suficientes pronosticos para evaluar.")
    else:
        for _, row in summary.iterrows():
            lines.append(
                f"- {row['grupo']}: {row['precision']}% "
                f"({int(row['aciertos'])}/{int(row['pronosticos'])}) "
                f"| prob. prom. {row['prob_promedio']}%"
            )

    lines.append("")
    lines.append("Precision por confianza:")
    if confidence_summary.empty:
        lines.append("- No hubo suficientes pronosticos para evaluar.")
    else:
        for _, row in confidence_summary.iterrows():
            lines.append(
                f"- {row['confianza']}: {row['precision']}% "
                f"({int(row['aciertos'])}/{int(row['pronosticos'])}) "
                f"| prob. prom. {row['prob_promedio']}%"
            )

    if brier is not None:
        lines.append("")
        lines.append(
            f"Brier score del mercado 1X2: {brier} (0 = probabilidades perfectas, "
            "0.667 = al azar; mide que tan bien calibradas estan las probabilidades, no solo aciertos)."
        )

    return "\n".join(lines)
