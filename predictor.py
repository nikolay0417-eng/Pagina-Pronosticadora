import poisson_model
from metrics import head_to_head, team_summary
from standings import format_standing_line, latest_competition_for_match, match_standings


def predict_match(matches, home_team, away_team, competition=None, last_n=10, include_advanced=True, model_config=None):
    if not competition:
        competition = latest_competition_for_match(matches, home_team, away_team)

    home_recent = team_summary(matches, home_team, last_n=last_n, competition=competition)
    away_recent = team_summary(matches, away_team, last_n=last_n, competition=competition)
    home_home = team_summary(
        matches,
        home_team,
        last_n=last_n,
        side="home",
        competition=competition,
    )
    away_away = team_summary(
        matches,
        away_team,
        last_n=last_n,
        side="away",
        competition=competition,
    )
    direct = head_to_head(matches, home_team, away_team)

    goals = poisson_model.predict_goals(matches, home_team, away_team, competition=competition, config=model_config)

    probabilities = {
        "home_win": round(goals["home_win"] * 100, 1),
        "draw": round(goals["draw"] * 100, 1),
        "away_win": round(goals["away_win"] * 100, 1),
    }
    goals_projection = {
        "home_expected_goals": goals["lambda_home"],
        "away_expected_goals": goals["lambda_away"],
        "expected_total_goals": round(goals["lambda_home"] + goals["lambda_away"], 2),
        "over_15": round(goals["over_15"] * 100, 1),
        "over_25": round(goals["over_25"] * 100, 1),
        "both_teams_score": round(goals["both_teams_score"] * 100, 1),
    }

    confidence = _confidence(home_recent, away_recent, home_home, away_away, direct)
    market_suggestions, avoid_markets = _market_suggestions(
        home_team,
        away_team,
        probabilities,
        goals_projection,
    )

    advanced_markets, advanced_context = [], {}
    if include_advanced:
        advanced_markets, advanced_context = _advanced_markets(
            matches,
            home_team,
            away_team,
            competition,
            model_config,
        )

    market_suggestions = sorted(
        market_suggestions + advanced_markets,
        key=lambda item: item["probability"],
        reverse=True,
    )[:7]

    return {
        "home_team": home_team,
        "away_team": away_team,
        "competition": competition,
        "probabilities": probabilities,
        "goals_projection": goals_projection,
        "confidence": confidence,
        "recommendation": _recommendation(probabilities, goals_projection, confidence),
        "market_suggestions": market_suggestions,
        "avoid_markets": avoid_markets,
        "probable_scores": _probable_scores(goals["top_scores"]),
        "standings": match_standings(matches, home_team, away_team, competition),
        "advanced_context": advanced_context,
        "signals": _signals(
            home_team,
            away_team,
            home_recent,
            away_recent,
            home_home,
            away_away,
            direct,
            goals_projection,
            goals["top_scores"],
        ),
        "metrics": {
            "home_recent": home_recent,
            "away_recent": away_recent,
            "home_home": home_home,
            "away_away": away_away,
            "head_to_head": direct,
        },
    }


def format_prediction(prediction):
    probabilities = prediction["probabilities"]
    goals = prediction["goals_projection"]

    lines = [
        f"Pronostico: {prediction['home_team']} vs {prediction['away_team']}",
        "",
        "Probabilidades estimadas:",
        f"- Gana {prediction['home_team']}: {probabilities['home_win']}%",
        f"- Empate: {probabilities['draw']}%",
        f"- Gana {prediction['away_team']}: {probabilities['away_win']}%",
        "",
        "Goles:",
        f"- Proyeccion total: {goals['expected_total_goals']}",
        f"- Over 1.5: {goals['over_15']}%",
        f"- Over 2.5: {goals['over_25']}%",
        f"- Ambos marcan: {goals['both_teams_score']}%",
        "",
        "Tabla:",
        f"- {format_standing_line(prediction['standings']['home'])}",
        f"- {format_standing_line(prediction['standings']['away'])}",
        "",
        "Mercados sugeridos:",
    ]

    if prediction["market_suggestions"]:
        lines.extend(
            f"{index}. {market['name']} - {market['probability']}% - confianza {market['confidence']}"
            for index, market in enumerate(prediction["market_suggestions"], start=1)
        )
    else:
        lines.append("- No hay mercados con ventaja clara.")

    lines.append("")
    lines.append("Evitar:")
    if prediction["avoid_markets"]:
        lines.extend(
            f"- {market['name']} - {market['probability']}% - confianza {market['confidence']}"
            for market in prediction["avoid_markets"]
        )
    else:
        lines.append("- No hay alertas fuertes de mercados a evitar.")

    lines.append("")
    lines.append("Marcadores mas probables:")
    lines.extend(
        f"{index}. {item['score']} - {item['probability']}%"
        for index, item in enumerate(prediction["probable_scores"], start=1)
    )

    lines.extend(
        [
            "",
            f"Recomendacion general: {prediction['recommendation']}",
            f"Confianza: {prediction['confidence']}",
            "",
            "Senales principales:",
        ]
    )

    lines.extend(f"- {signal}" for signal in prediction["signals"])
    return "\n".join(lines)


def _confidence(home_recent, away_recent, home_home, away_away, direct):
    sample = (
        home_recent["matches"]
        + away_recent["matches"]
        + home_home["matches"]
        + away_away["matches"]
        + direct["matches"]
    )
    if sample >= 35:
        return "media-alta"
    if sample >= 22:
        return "media"
    return "baja"


def _recommendation(probabilities, goals, confidence):
    home = probabilities["home_win"]
    draw = probabilities["draw"]
    away = probabilities["away_win"]

    picks = []
    if home >= 48:
        picks.append("gana local")
    elif away >= 48:
        picks.append("gana visitante")
    elif home + draw >= 68:
        picks.append("doble oportunidad local o empate")
    elif away + draw >= 68:
        picks.append("doble oportunidad visitante o empate")
    else:
        picks.append("mercado 1X2 parejo")

    if goals["over_15"] >= 65:
        picks.append("over 1.5 goles")
    if goals["over_25"] >= 58:
        picks.append("over 2.5 goles")
    if goals["both_teams_score"] >= 58:
        picks.append("ambos equipos marcan")

    if confidence == "baja":
        picks.append("usar stake bajo")

    return " / ".join(picks)


def _market_suggestions(home_team, away_team, probabilities, goals):
    candidates = [
        {"name": f"{home_team} gana", "probability": probabilities["home_win"], "min_probability": 62},
        {"name": "empate", "probability": probabilities["draw"], "min_probability": 62},
        {"name": f"{away_team} gana", "probability": probabilities["away_win"], "min_probability": 62},
        {
            "name": f"{home_team} o empate",
            "probability": round(probabilities["home_win"] + probabilities["draw"], 1),
            "min_probability": 64,
        },
        {
            "name": f"{away_team} o empate",
            "probability": round(probabilities["away_win"] + probabilities["draw"], 1),
            "min_probability": 64,
        },
        {"name": "Over 1.5 goles", "probability": goals["over_15"], "min_probability": 70},
        {"name": "Over 2.5 goles", "probability": goals["over_25"], "min_probability": 72},
        {"name": "Ambos equipos marcan", "probability": goals["both_teams_score"], "min_probability": 62},
    ]

    for candidate in candidates:
        candidate["confidence"] = _market_confidence(candidate["probability"])

    suggested = [
        candidate
        for candidate in candidates
        if candidate["probability"] >= candidate["min_probability"]
        and candidate["confidence"] != "baja"
    ]
    avoid = [
        candidate
        for candidate in candidates
        if candidate["probability"] < 54
        and candidate["name"] in ["empate", "Over 2.5 goles", "Ambos equipos marcan"]
    ]

    suggested.sort(key=lambda item: item["probability"], reverse=True)
    avoid.sort(key=lambda item: item["probability"])
    return suggested[:5], avoid[:3]


def _market_confidence(probability):
    if probability >= 72:
        return "alta"
    if probability >= 62:
        return "media-alta"
    if probability >= 55:
        return "media"
    return "baja"


def _probable_scores(top_scores):
    return [
        {"score": f"{home_goals}-{away_goals}", "probability": round(probability * 100, 1)}
        for home_goals, away_goals, probability in top_scores
    ]


def _advanced_markets(matches, home_team, away_team, competition, model_config=None):
    markets = []
    context = {}

    corners = poisson_model.predict_stat_total(
        matches,
        home_team,
        away_team,
        "corners_local",
        "corners_visitante",
        competition=competition,
        config=model_config,
        line=8.5,
    )
    context["corners"] = corners
    if corners.get("available") and corners["over_probability"] >= 62:
        markets.append(
            {
                "name": "Over 8.5 corners",
                "probability": corners["over_probability"],
                "confidence": _market_confidence(corners["over_probability"]),
                "min_probability": 62,
            }
        )

    yellow_cards = poisson_model.predict_stat_total(
        matches,
        home_team,
        away_team,
        "amarillas_local",
        "amarillas_visitante",
        competition=competition,
        config=model_config,
        line=3.5,
    )
    context["yellow_cards"] = yellow_cards
    if yellow_cards.get("available") and yellow_cards["over_probability"] >= 62:
        markets.append(
            {
                "name": "Over 3.5 tarjetas amarillas",
                "probability": yellow_cards["over_probability"],
                "confidence": _market_confidence(yellow_cards["over_probability"]),
                "min_probability": 62,
            }
        )

    return markets, context


def _signals(home_team, away_team, home_recent, away_recent, home_home, away_away, direct, goals, top_scores):
    signals = [
        f"{home_team}: {home_recent['wins']}G-{home_recent['draws']}E-{home_recent['losses']}P en sus ultimos {home_recent['matches']} partidos.",
        f"{away_team}: {away_recent['wins']}G-{away_recent['draws']}E-{away_recent['losses']}P en sus ultimos {away_recent['matches']} partidos.",
        f"{home_team} como local promedia {home_home['goals_for_avg']} goles a favor y {home_home['goals_against_avg']} en contra.",
        f"{away_team} como visitante promedia {away_away['goals_for_avg']} goles a favor y {away_away['goals_against_avg']} en contra.",
        f"El modelo Poisson estima {goals['home_expected_goals']} goles locales y {goals['away_expected_goals']} visitantes.",
    ]

    if top_scores:
        best_home, best_away, best_probability = top_scores[0]
        signals.append(
            f"Marcador mas probable segun el modelo: {best_home}-{best_away} con {round(best_probability * 100, 1)}%."
        )

    if direct["matches"]:
        signals.append(
            f"Historial directo reciente: {direct['home_team_wins']} victorias de {home_team}, "
            f"{direct['away_team_wins']} de {away_team} y {direct['draws']} empates."
        )
    else:
        signals.append("No hay historial directo reciente suficiente en el dataset.")

    return signals
