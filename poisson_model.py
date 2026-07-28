import json
import math
from pathlib import Path

import pandas as pd

from data_loader import finished_matches


CONFIG_PATH = Path("data") / "model_config.json"

DEFAULT_CONFIG = {
    "half_life_days": 200,
    "rho": -0.08,
    "shrinkage_k": 8,
}

DEFAULT_TEAM_STRENGTH = {"attack": 1.0, "defense": 1.0, "weight": 0.0}

FALLBACK_LEAGUE_AVG_HOME = 1.45
FALLBACK_LEAGUE_AVG_AWAY = 1.15

MAX_GOALS = 10


def load_model_config():
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return dict(DEFAULT_CONFIG)

        config = dict(DEFAULT_CONFIG)
        config.update({key: saved[key] for key in DEFAULT_CONFIG if key in saved})
        return config

    return dict(DEFAULT_CONFIG)


def save_model_config(config):
    CONFIG_PATH.parent.mkdir(exist_ok=True)
    payload = {key: config[key] for key in DEFAULT_CONFIG}
    CONFIG_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def poisson_pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def poisson_cdf(k, lam):
    return sum(poisson_pmf(i, lam) for i in range(0, k + 1))


def time_weight(days_ago, half_life_days):
    if half_life_days <= 0:
        return 1.0
    return 0.5 ** (max(0, days_ago) / half_life_days)


def dixon_coles_tau(x, y, lambda_home, lambda_away, rho):
    if x == 0 and y == 0:
        return 1 - (lambda_home * lambda_away * rho)
    if x == 0 and y == 1:
        return 1 + (lambda_home * rho)
    if x == 1 and y == 0:
        return 1 + (lambda_away * rho)
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


def _empty_strengths():
    return {
        "available": False,
        "teams": {},
        "league_avg_home": 0.0,
        "league_avg_away": 0.0,
        "sample": 0,
    }


def stat_strengths(matches, home_col, away_col, competition=None, half_life_days=200, shrinkage_k=8):
    data = finished_matches(matches)
    if competition:
        data = data[data["competicion_codigo"].eq(competition)]
    if home_col not in data.columns or away_col not in data.columns:
        return _empty_strengths()

    data = data.dropna(subset=[home_col, away_col])
    if data.empty:
        return _empty_strengths()

    as_of = data["fecha_utc"].max()
    days_ago = (as_of - data["fecha_utc"]).dt.days.clip(lower=0)
    weight = days_ago.apply(lambda days: time_weight(days, half_life_days))

    total_weight = weight.sum()
    if total_weight <= 0:
        return _empty_strengths()

    league_avg_home = float((data[home_col] * weight).sum() / total_weight)
    league_avg_away = float((data[away_col] * weight).sum() / total_weight)
    if league_avg_home <= 0 or league_avg_away <= 0:
        return _empty_strengths()

    home_rows = pd.DataFrame({
        "team": data["equipo_local"],
        "attack_ratio": data[home_col] / league_avg_home,
        "defense_ratio": data[away_col] / league_avg_away,
        "weight": weight,
    })
    away_rows = pd.DataFrame({
        "team": data["equipo_visitante"],
        "attack_ratio": data[away_col] / league_avg_away,
        "defense_ratio": data[home_col] / league_avg_home,
        "weight": weight,
    })
    combined = pd.concat([home_rows, away_rows], ignore_index=True)
    combined["weighted_attack"] = combined["attack_ratio"] * combined["weight"]
    combined["weighted_defense"] = combined["defense_ratio"] * combined["weight"]

    grouped = combined.groupby("team").agg(
        weight_sum=("weight", "sum"),
        attack_sum=("weighted_attack", "sum"),
        defense_sum=("weighted_defense", "sum"),
    )

    teams = {}
    for team, row in grouped.iterrows():
        weight_sum = row["weight_sum"]
        if weight_sum <= 0:
            continue

        raw_attack = row["attack_sum"] / weight_sum
        raw_defense = row["defense_sum"] / weight_sum
        attack = (raw_attack * weight_sum + shrinkage_k) / (weight_sum + shrinkage_k)
        defense = (raw_defense * weight_sum + shrinkage_k) / (weight_sum + shrinkage_k)
        teams[team] = {
            "attack": float(attack),
            "defense": float(defense),
            "weight": round(float(weight_sum), 2),
        }

    return {
        "available": True,
        "teams": teams,
        "league_avg_home": league_avg_home,
        "league_avg_away": league_avg_away,
        "sample": int(len(data)),
    }


def score_matrix(lambda_home, lambda_away, rho, max_goals=MAX_GOALS):
    size = max_goals + 1
    matrix = [[0.0] * size for _ in range(size)]
    total = 0.0

    for i in range(size):
        for j in range(size):
            probability = poisson_pmf(i, lambda_home) * poisson_pmf(j, lambda_away)
            if i <= 1 and j <= 1:
                probability *= dixon_coles_tau(i, j, lambda_home, lambda_away, rho)
            probability = max(0.0, probability)
            matrix[i][j] = probability
            total += probability

    if total > 0:
        matrix = [[value / total for value in row] for row in matrix]

    return matrix


def market_probabilities_from_matrix(matrix):
    size = len(matrix)
    home_win = draw = away_win = 0.0
    over_15 = over_25 = over_35 = 0.0
    score_probabilities = []

    home_zero = sum(matrix[0])
    away_zero = sum(matrix[i][0] for i in range(size))
    both_zero = matrix[0][0]

    for i in range(size):
        for j in range(size):
            probability = matrix[i][j]
            score_probabilities.append((i, j, probability))
            total_goals = i + j

            if i > j:
                home_win += probability
            elif i == j:
                draw += probability
            else:
                away_win += probability

            if total_goals >= 2:
                over_15 += probability
            if total_goals >= 3:
                over_25 += probability
            if total_goals >= 4:
                over_35 += probability

    both_teams_score = max(0.0, 1 - home_zero - away_zero + both_zero)
    score_probabilities.sort(key=lambda item: item[2], reverse=True)

    return {
        "home_win": home_win,
        "draw": draw,
        "away_win": away_win,
        "over_15": over_15,
        "over_25": over_25,
        "over_35": over_35,
        "both_teams_score": both_teams_score,
        "top_scores": score_probabilities[:5],
    }


def predict_goals(matches, home_team, away_team, competition=None, config=None):
    config = config or load_model_config()
    strengths = stat_strengths(
        matches,
        "goles_local_final",
        "goles_visitante_final",
        competition=competition,
        half_life_days=config["half_life_days"],
        shrinkage_k=config["shrinkage_k"],
    )

    if not strengths["available"]:
        strengths = {
            **strengths,
            "league_avg_home": FALLBACK_LEAGUE_AVG_HOME,
            "league_avg_away": FALLBACK_LEAGUE_AVG_AWAY,
        }

    home = strengths["teams"].get(home_team, DEFAULT_TEAM_STRENGTH)
    away = strengths["teams"].get(away_team, DEFAULT_TEAM_STRENGTH)

    lambda_home = max(0.08, home["attack"] * away["defense"] * strengths["league_avg_home"])
    lambda_away = max(0.08, away["attack"] * home["defense"] * strengths["league_avg_away"])

    matrix = score_matrix(lambda_home, lambda_away, config["rho"])
    markets = market_probabilities_from_matrix(matrix)

    return {
        "lambda_home": round(lambda_home, 2),
        "lambda_away": round(lambda_away, 2),
        "home_strength": home,
        "away_strength": away,
        "league_avg_home": round(strengths["league_avg_home"], 2),
        "league_avg_away": round(strengths["league_avg_away"], 2),
        **markets,
    }


def predict_stat_total(matches, home_team, away_team, home_col, away_col, competition=None, config=None, line=8.5, min_sample=8):
    config = config or load_model_config()
    strengths = stat_strengths(
        matches,
        home_col,
        away_col,
        competition=competition,
        half_life_days=config["half_life_days"],
        shrinkage_k=config["shrinkage_k"],
    )

    if not strengths["available"] or strengths["sample"] < min_sample:
        return {"available": False}

    home = strengths["teams"].get(home_team, DEFAULT_TEAM_STRENGTH)
    away = strengths["teams"].get(away_team, DEFAULT_TEAM_STRENGTH)

    lambda_home = max(0.1, home["attack"] * away["defense"] * strengths["league_avg_home"])
    lambda_away = max(0.1, away["attack"] * home["defense"] * strengths["league_avg_away"])
    expected_total = lambda_home + lambda_away

    over_probability = 1 - poisson_cdf(math.floor(line), expected_total)
    over_probability = max(0.0, min(1.0, over_probability))

    return {
        "available": True,
        "expected_total": round(expected_total, 2),
        "over_probability": round(over_probability * 100, 1),
        "sample": strengths["sample"],
    }
