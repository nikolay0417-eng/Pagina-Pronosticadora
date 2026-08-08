import argparse
from datetime import date

from backtester import (
    brier_score,
    calibrate_model,
    evaluate_predictions,
    format_backtest,
    summarize_backtest,
    summarize_by_confidence,
)
from competitions import competition_label, resolve_competition
from data_loader import (
    find_team,
    finished_matches,
    load_matches,
    team_competitions,
    team_names,
    upcoming_matches,
)
from metrics import team_summary
from predictor import format_prediction, predict_match
from standings import format_standing_line, latest_competition_for_team, match_standings


def main():
    args = parse_args()
    matches = load_matches(args.data)

    if args.action == "teams":
        print_teams(matches, args.search)
    elif args.action == "team":
        team = find_team(matches, args.team)
        print_team_summary(matches, team, args.last)
    elif args.action == "upcoming":
        print_upcoming(matches, args.limit, args.date, resolve_competition_input(args.competition))
    elif args.action == "date":
        print_matches_by_date(matches, args.date, resolve_competition_input(args.competition), args.limit)
    elif args.action == "results":
        print_results_by_date(matches, args.date, resolve_competition_input(args.competition), args.limit)
    elif args.action == "picks":
        print_picks(
            matches,
            args.date,
            resolve_competition_input(args.competition),
            args.limit,
            args.market,
            args.last,
        )
    elif args.action == "backtest":
        print_backtest(
            matches,
            resolve_competition_input(args.competition),
            args.date_from,
            args.date_to,
            args.limit,
            args.last,
        )
    elif args.action == "calibrate":
        print_calibrate(matches, resolve_competition_input(args.competition), args.limit)
    elif args.action == "data-health":
        print_data_health(matches)
    elif args.action == "profile":
        team = find_team(matches, args.team)
        print_team_profile(matches, team, resolve_competition_input(args.competition), args.last)
    elif args.action == "predict":
        competition = resolve_competition_input(args.competition)
        preferred = [competition] if competition else None
        home_team = find_team(matches, args.home, preferred_competitions=preferred)
        away_preferred = preferred or team_competitions(matches, home_team)
        away_team = find_team(matches, args.away, preferred_competitions=away_preferred)
        prediction = predict_match(
            matches,
            home_team,
            away_team,
            competition=competition,
            last_n=args.last,
        )
        print(format_prediction(prediction))
    else:
        interactive_mode(matches, args.last)


def interactive_mode(matches, last_n):
    print("Agente de pronosticos deportivos")
    print("")

    while True:
        print("Que quieres hacer?")
        print("1. Pronosticar partido especifico")
        print("2. Ver partidos por fecha")
        print("3. Ver resultados por fecha")
        print("4. Ver mejores picks")
        print("5. Ver ficha completa de equipo")
        print("6. Buscar equipos")
        print("7. Medir precision con backtest")
        print("8. Revisar datos avanzados")
        print("9. Calibrar modelo con historicos")
        print("0. Salir")
        option = input("Opcion: ").strip()

        if option in ["0", "salir", "exit"]:
            break
        if option == "1":
            interactive_predict(matches, last_n)
        elif option == "2":
            target_date = input("Fecha (YYYY-MM-DD): ").strip()
            competition = ask_competition()
            print("")
            print_matches_by_date(matches, target_date, competition)
            print("")
        elif option == "3":
            target_date = input("Fecha (YYYY-MM-DD): ").strip()
            competition = ask_competition()
            print("")
            print_results_by_date(matches, target_date, competition)
            print("")
        elif option == "4":
            target_date = input("Fecha opcional (YYYY-MM-DD): ").strip() or None
            competition = ask_competition()
            market = input("Mercado opcional (ej: Over, empate, marcan): ").strip() or None
            limit_text = input("Cuantos picks? (Enter = 10): ").strip()
            limit = int(limit_text) if limit_text else 10
            print("")
            print_picks(matches, target_date, competition, limit, market, last_n)
            print("")
        elif option == "5":
            team = input("Equipo: ").strip()
            competition = ask_competition("Liga opcional (Enter = detectar automaticamente): ")
            print("")
            try:
                team_name = find_team(matches, team)
                print_team_profile(matches, team_name, competition, last_n)
            except ValueError as error:
                print(error)
            print("")
        elif option == "6":
            search = input("Buscar equipo: ").strip()
            print("")
            print_teams(matches, search)
            print("")
        elif option == "7":
            competition = ask_competition()
            date_from = input("Desde fecha opcional (YYYY-MM-DD): ").strip() or None
            date_to = input("Hasta fecha opcional (YYYY-MM-DD): ").strip() or None
            limit_text = input("Ultimos cuantos partidos? (Enter = 300): ").strip()
            limit = int(limit_text) if limit_text else 300
            print("")
            print_backtest(matches, competition, date_from, date_to, limit, last_n)
            print("")
        elif option == "8":
            print("")
            print_data_health(matches)
            print("")
        elif option == "9":
            competition = ask_competition()
            limit_text = input("Cuantos partidos usar para calibrar? (Enter = 70): ").strip()
            limit = int(limit_text) if limit_text else 70
            print("")
            print_calibrate(matches, competition, limit)
            print("")
        else:
            print("Opcion no valida.")
            print("")


def interactive_predict(matches, last_n):
    home = input("Local: ").strip()
    away = input("Visitante: ").strip()
    competition = ask_competition()

    try:
        preferred = [competition] if competition else None
        home_team = find_team(matches, home, preferred_competitions=preferred)
        away_preferred = preferred or team_competitions(matches, home_team)
        away_team = find_team(matches, away, preferred_competitions=away_preferred)
        prediction = predict_match(
            matches,
            home_team,
            away_team,
            competition=competition,
            last_n=last_n,
        )
        print("")
        print(format_prediction(prediction))
        print("")
    except ValueError as error:
        print(error)
        print("Usa la opcion 5 para revisar nombres disponibles.")


def print_teams(matches, search=None):
    teams = team_names(matches)
    if search:
        normalized = search.casefold()
        teams = [team for team in teams if normalized in team.casefold()]

    for team in teams:
        print(team)

    print(f"\nTotal equipos: {len(teams)}")


def print_team_summary(matches, team, last_n):
    summary = team_summary(matches, team, last_n=last_n)
    print(f"Equipo: {team}")
    print(f"Partidos analizados: {summary['matches']}")
    print(f"Record: {summary['wins']}G-{summary['draws']}E-{summary['losses']}P")
    print(f"Puntos por partido: {summary['points_per_match']}")
    print(f"Goles a favor promedio: {summary['goals_for_avg']}")
    print(f"Goles en contra promedio: {summary['goals_against_avg']}")
    print(f"Over 1.5: {summary['over_15_rate']}%")
    print(f"Over 2.5: {summary['over_25_rate']}%")
    print(f"Ambos marcan: {summary['both_score_rate']}%")


def print_upcoming(matches, limit, target_date=None, competition=None):
    games = filter_games(upcoming_matches(matches), target_date, competition)
    games = games.sort_values("fecha_utc").head(limit)
    if games.empty:
        print("No encontre partidos programados en el dataset actual.")
        return

    print_games(games)


def print_matches_by_date(matches, target_date=None, competition=None, limit=50):
    games = filter_games(upcoming_matches(matches), target_date or str(date.today()), competition)
    games = games.sort_values("fecha_utc").head(limit)
    if games.empty:
        print("No encontre partidos para esa fecha en el dataset actual.")
        return

    print_games(games)


def print_results_by_date(matches, target_date=None, competition=None, limit=50):
    games = filter_games(finished_matches(matches), target_date or str(date.today()), competition)
    games = games.sort_values("fecha_utc").head(limit)
    if games.empty:
        print("No encontre resultados finalizados para esa fecha en el dataset actual.")
        print("Si la fecha es hoy, ejecuta API-Football.py para actualizar datos antes de consultar.")
        return

    print_result_games(games)


def print_games(games):
    for index, (_, row) in enumerate(games.iterrows(), start=1):
        print(
            f"{index}. {format_local(row['fecha_local'])} | {row['competicion_codigo']} | "
            f"{row['equipo_local']} vs {row['equipo_visitante']}"
        )


def print_result_games(games):
    for index, (_, row) in enumerate(games.iterrows(), start=1):
        home_goals = int(row["goles_local_final"])
        away_goals = int(row["goles_visitante_final"])
        print(
            f"{index}. {format_local(row['fecha_local'])} | {row['competicion_codigo']} | "
            f"{row['equipo_local']} {home_goals}-{away_goals} {row['equipo_visitante']}"
        )


def print_picks(matches, target_date=None, competition=None, limit=10, market=None, last_n=10):
    games = filter_games(upcoming_matches(matches), target_date, competition)
    games = games.sort_values("fecha_utc")
    if games.empty:
        print("No encontre partidos programados para esos filtros.")
        return

    picks = []
    for _, row in games.iterrows():
        prediction = predict_match(
            matches,
            row["equipo_local"],
            row["equipo_visitante"],
            competition=row["competicion_codigo"],
            last_n=last_n,
        )
        for suggestion in prediction["market_suggestions"]:
            if market and market.casefold() not in suggestion["name"].casefold():
                continue
            picks.append(
                {
                    "date": format_local(row["fecha_local"]),
                    "competition": row["competicion_codigo"],
                    "home": row["equipo_local"],
                    "away": row["equipo_visitante"],
                    "market": suggestion["name"],
                    "probability": suggestion["probability"],
                    "confidence": suggestion["confidence"],
                    "short_sample": suggestion.get("muestra_corta", False),
                    "recommendation": prediction["recommendation"],
                }
            )

    picks.sort(key=lambda item: item["probability"], reverse=True)
    if not picks:
        print("No encontre mercados que cumplan esos filtros.")
        return

    print("Top oportunidades:")
    for index, pick in enumerate(picks[:limit], start=1):
        aviso = " (muestra corta)" if pick.get("short_sample") else ""
        print(
            f"{index}. {pick['date']} | {pick['competition']} | "
            f"{pick['home']} vs {pick['away']} | {pick['market']} "
            f"- {pick['probability']}% - confianza {pick['confidence']}{aviso}"
        )


def print_backtest(matches, competition=None, date_from=None, date_to=None, limit=300, last_n=10):
    results, probabilities = evaluate_predictions(
        matches,
        competition=competition,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        last_n=last_n,
    )
    summary = summarize_backtest(results)
    confidence_summary = summarize_by_confidence(results)
    brier = brier_score(probabilities)
    print(format_backtest(summary, confidence_summary, len(results), brier))


def print_calibrate(matches, competition=None, limit=70):
    print(
        "Calibrando el modelo contra el historico (probando 25 combinaciones de "
        "decaimiento temporal y correlacion Dixon-Coles). Esto puede tardar 10-15 minutos, "
        "dejalo corriendo..."
    )
    best = calibrate_model(matches, competition=competition, limit=limit)
    if not best:
        print("No hubo suficientes partidos para calibrar con esos filtros.")
        return

    print("")
    print("Mejor configuracion encontrada:")
    print(f"- Decaimiento temporal (half_life_days): {best['half_life_days']} dias")
    print(f"- Correlacion Dixon-Coles (rho): {best['rho']}")
    print(f"- Regularizacion (shrinkage_k): {best['shrinkage_k']}")
    print(f"- Brier score: {best['brier_score']} sobre {best['sample_size']} partidos")
    print("")
    print("Guardado en data/model_config.json. El agente y el dashboard ya lo usaran en los proximos pronosticos.")


def print_data_health(matches):
    columns = [
        "corners_local",
        "corners_visitante",
        "amarillas_local",
        "amarillas_visitante",
        "rojas_local",
        "rojas_visitante",
        "faltas_local",
        "faltas_visitante",
        "tiros_local",
        "tiros_visitante",
        "posesion_local",
        "posesion_visitante",
        "cantidad_tarjetas",
    ]
    existing = [column for column in columns if column in matches.columns]

    print("Disponibilidad de datos avanzados:")
    for column in existing:
        non_empty = int(matches[column].notna().sum())
        non_zero = int(matches[column].fillna(0).ne(0).sum())
        print(f"- {column}: {non_empty} con dato, {non_zero} con valor distinto de 0")

    useful_corners = all(
        column in matches.columns and matches[column].notna().sum() > 0
        for column in ["corners_local", "corners_visitante"]
    )
    useful_cards = all(
        column in matches.columns and matches[column].notna().sum() > 0
        for column in ["amarillas_local", "amarillas_visitante"]
    )

    print("")
    if useful_corners:
        print("Corners: disponible para pronosticos.")
    else:
        print("Corners: no disponible todavia en el CSV.")

    if useful_cards:
        print("Tarjetas amarillas: disponible para pronosticos.")
    else:
        print("Tarjetas amarillas: no disponible todavia en el CSV.")

    if not useful_corners or not useful_cards:
        print(
            "La API no esta entregando esos campos en el listado actual. "
            "Para intentar obtenerlos, el siguiente paso es consultar detalle partido por partido."
        )


def print_team_profile(matches, team, competition=None, last_n=10):
    if not competition:
        competition = latest_competition_for_team(matches, team)

    standings = match_standings(matches, team, team, competition)
    recent_5 = team_summary(matches, team, last_n=5, competition=competition)
    recent = team_summary(matches, team, last_n=last_n, competition=competition)
    home = team_summary(matches, team, last_n=last_n, side="home", competition=competition)
    away = team_summary(matches, team, last_n=last_n, side="away", competition=competition)
    team_games = matches[
        matches["equipo_local"].eq(team) | matches["equipo_visitante"].eq(team)
    ].copy()
    if competition:
        team_games = team_games[team_games["competicion_codigo"].eq(competition)]

    recent_games = team_games[team_games["estado"].eq("FINISHED")].sort_values("fecha_utc").tail(5)
    next_games = team_games[team_games["estado"].isin(["SCHEDULED", "TIMED"])].sort_values("fecha_utc").head(5)

    print(f"Ficha de equipo: {team}")
    print(f"Liga usada: {competition_label(competition)}")
    print("")
    print("Tabla:")
    print(f"- {format_standing_line(standings['home'])}")
    print("")
    print("Forma:")
    print_summary_line("Ultimos 5", recent_5)
    print_summary_line(f"Ultimos {last_n}", recent)
    print_summary_line("Como local", home)
    print_summary_line("Como visitante", away)
    print("")
    print("Ultimos partidos:")
    print_team_games(recent_games)
    print("")
    print("Proximos partidos:")
    print_team_games(next_games)


def print_summary_line(label, summary):
    print(
        f"- {label}: {summary['wins']}G-{summary['draws']}E-{summary['losses']}P, "
        f"GF {summary['goals_for_avg']}, GC {summary['goals_against_avg']}, "
        f"Over 2.5 {summary['over_25_rate']}%, ambos marcan {summary['both_score_rate']}%"
    )


def print_team_games(games):
    if games.empty:
        print("- No hay partidos para mostrar.")
        return

    for _, row in games.iterrows():
        score = ""
        if row["estado"] == "FINISHED":
            score = f" {int(row['goles_local_final'])}-{int(row['goles_visitante_final'])}"
        print(
            f"- {format_local(row['fecha_local'])} | {row['competicion_codigo']} | "
            f"{row['equipo_local']} vs {row['equipo_visitante']}{score} | {row['estado']}"
        )


def format_local(value):
    return value.strftime("%Y-%m-%d %H:%M")


def filter_games(games, target_date=None, competition=None):
    filtered = games.copy()
    if target_date:
        filtered = filtered[filtered["fecha_local"].dt.date.astype(str).eq(target_date)]
    if competition:
        filtered = filtered[filtered["competicion_codigo"].eq(competition)]
    return filtered


def ask_competition(prompt="Liga opcional (Enter = automatico, ej: LaLiga, Premier, Francia): "):
    value = input(prompt).strip()
    return resolve_competition_input(value)


def resolve_competition_input(value):
    if not value:
        return None

    competition = resolve_competition(value)
    if competition:
        return competition

    print(
        f"No reconozco la liga '{value}'. La dejo en automatico. "
        "Puedes escribir: LaLiga, Premier, Serie A, Bundesliga, Ligue 1, Champions."
    )
    return None


def parse_args():
    parser = argparse.ArgumentParser(
        description="Agente local para analizar partidos y generar pronosticos explicables."
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=[
            "chat",
            "predict",
            "team",
            "teams",
            "upcoming",
            "date",
            "results",
            "picks",
            "profile",
            "backtest",
            "calibrate",
            "data-health",
        ],
        default="chat",
    )
    parser.add_argument("--data", default="data/partidos.csv")
    parser.add_argument("--home", help="Equipo local para pronosticar.")
    parser.add_argument("--away", help="Equipo visitante para pronosticar.")
    parser.add_argument("--team", help="Equipo a analizar.")
    parser.add_argument("--search", help="Texto para filtrar equipos.")
    parser.add_argument(
        "--competition",
        help="Liga o codigo. Ejemplos: LaLiga, Premier, Serie A, Bundesliga, Ligue 1, Champions, PD, PL.",
    )
    parser.add_argument("--date", help="Fecha en formato YYYY-MM-DD.")
    parser.add_argument("--date-from", help="Fecha inicial para backtest en formato YYYY-MM-DD.")
    parser.add_argument("--date-to", help="Fecha final para backtest en formato YYYY-MM-DD.")
    parser.add_argument("--market", help="Filtra picks por mercado, ejemplo: Over, empate, marcan.")
    parser.add_argument("--last", type=int, default=10, help="Numero de partidos recientes a analizar.")
    parser.add_argument("--limit", type=int, default=20, help="Limite de partidos a mostrar.")

    args = parser.parse_args()
    if args.action == "predict" and (not args.home or not args.away):
        parser.error("predict requiere --home y --away")
    if args.action in ["team", "profile"] and not args.team:
        parser.error(f"{args.action} requiere --team")

    return args


if __name__ == "__main__":
    main()
