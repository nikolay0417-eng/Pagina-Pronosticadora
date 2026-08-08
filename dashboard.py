import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from backtester import brier_score, evaluate_predictions, summarize_backtest
from competitions import competition_label
from data_loader import LOCAL_TZ, finished_matches, load_matches, upcoming_matches
from metrics import team_summary
from poisson_model import load_model_config, stat_strengths
from predictor import predict_match
from standings import build_table, latest_season_for_competition


OUTPUT_FILE = Path("dashboard.html")


def main():
    matches = load_matches()
    payload = build_payload(matches)
    html = HTML_TEMPLATE.replace("__DASHBOARD_DATA__", json.dumps(payload, ensure_ascii=False))
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"Dashboard generado: {OUTPUT_FILE.resolve()}")


def build_payload(matches):
    finished = finished_matches(matches)
    upcoming = upcoming_matches(matches)
    competitions = competition_options(matches)
    model_config = load_model_config()

    return {
        "generatedAt": datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M"),
        "summary": summary_metrics(matches, finished, upcoming),
        "competitions": competitions,
        "teamsByCompetition": teams_by_competition(matches),
        "teamMetrics": team_metrics(matches),
        "teamStrengths": team_strengths_payload(matches, model_config),
        "statStrengths": stat_strengths_payload(matches, model_config),
        "modelConfig": model_config,
        "standings": standings_payload(matches),
        "upcoming": fixture_rows(upcoming),
        "results": result_rows(finished.tail(300)),
        "picks": top_picks(matches, upcoming),
        "leagueStats": league_stats(finished),
        "monthlyGoals": monthly_goals(finished),
        "resultSplit": result_split(finished),
        "backtest": backtest_payload(matches),
        "dataHealth": data_health(matches),
    }


def team_strengths_payload(matches, model_config):
    payload = {}
    for competition in sorted(matches["competicion_codigo"].dropna().unique().tolist()):
        strengths = stat_strengths(
            matches,
            "goles_local_final",
            "goles_visitante_final",
            competition=competition,
            half_life_days=model_config["half_life_days"],
            shrinkage_k=model_config["shrinkage_k"],
        )
        if not strengths["available"]:
            continue

        payload[competition] = {
            "leagueAvgHome": round(strengths["league_avg_home"], 3),
            "leagueAvgAway": round(strengths["league_avg_away"], 3),
            "teams": {
                team: {"attack": round(values["attack"], 3), "defense": round(values["defense"], 3)}
                for team, values in strengths["teams"].items()
            },
        }
    return payload


# Estadisticas extra que el predictor visual puede proyectar, con la muestra
# minima que exige poisson_model para considerarlas utilizables.
EXTRA_STATS = [
    ("corners", "corners_local", "corners_visitante"),
    ("cards", "amarillas_local", "amarillas_visitante"),
]
MIN_STAT_SAMPLE = 8


def stat_strengths_payload(matches, model_config):
    """Fuerzas de corners y tarjetas por liga, para que el predictor del panel
    proyecte esas lineas con el mismo modelo que usa el CLI."""
    payload = {}
    competitions = sorted(matches["competicion_codigo"].dropna().unique().tolist())

    for key, home_col, away_col in EXTRA_STATS:
        if home_col not in matches.columns:
            continue

        by_competition = {}
        for competition in competitions:
            strengths = stat_strengths(
                matches,
                home_col,
                away_col,
                competition=competition,
                half_life_days=model_config["half_life_days"],
                shrinkage_k=model_config["shrinkage_k"],
            )
            if not strengths["available"] or strengths["sample"] < MIN_STAT_SAMPLE:
                continue

            by_competition[competition] = {
                "leagueAvgHome": round(strengths["league_avg_home"], 3),
                "leagueAvgAway": round(strengths["league_avg_away"], 3),
                "sample": strengths["sample"],
                "teams": {
                    team: {
                        "attack": round(values["attack"], 3),
                        "defense": round(values["defense"], 3),
                    }
                    for team, values in strengths["teams"].items()
                },
            }

        if by_competition:
            payload[key] = by_competition

    return payload


def competition_options(matches):
    codes = sorted(matches["competicion_codigo"].dropna().unique().tolist())
    return [{"code": code, "label": competition_label(code)} for code in codes]


def teams_by_competition(matches):
    output = {}
    for competition, group in matches.groupby("competicion_codigo"):
        teams = sorted(
            set(group["equipo_local"].dropna().tolist())
            | set(group["equipo_visitante"].dropna().tolist())
        )
        output[competition] = teams
    output["ALL"] = sorted(
        set(matches["equipo_local"].dropna().tolist())
        | set(matches["equipo_visitante"].dropna().tolist())
    )
    return output


def team_metrics(matches):
    metrics = {}
    for competition, teams in teams_by_competition(matches).items():
        if competition == "ALL":
            continue
        for team in teams:
            key = f"{competition}::{team}"
            metrics[key] = {
                "recent5": team_summary(matches, team, last_n=5, competition=competition),
                "recent10": team_summary(matches, team, last_n=10, competition=competition),
                "home": team_summary(matches, team, last_n=10, side="home", competition=competition),
                "away": team_summary(matches, team, last_n=10, side="away", competition=competition),
            }
    return metrics


def standings_payload(matches):
    payload = {}
    for competition in sorted(matches["competicion_codigo"].dropna().unique().tolist()):
        season = latest_season_for_competition(matches, competition)
        table = build_table(matches, competition, season)
        payload[competition] = table
    return payload


def summary_metrics(matches, finished, upcoming):
    total_goals = finished["goles_local_final"] + finished["goles_visitante_final"]
    both_score = finished["goles_local_final"].gt(0) & finished["goles_visitante_final"].gt(0)
    return {
        "totalMatches": int(len(matches)),
        "finishedMatches": int(len(finished)),
        "upcomingMatches": int(len(upcoming)),
        "competitions": int(matches["competicion_codigo"].nunique()),
        "avgGoals": round(float(total_goals.mean()), 2) if not total_goals.empty else 0,
        "over25": round(float(total_goals.gt(2.5).mean() * 100), 1) if not total_goals.empty else 0,
        "bothScore": round(float(both_score.mean() * 100), 1) if not both_score.empty else 0,
    }


def fixture_rows(rows):
    rows = rows.sort_values("fecha_utc")
    return [
        {
            "date": format_date(row["fecha_local"]),
            "dateOnly": format_date_only(row["fecha_local"]),
            "competition": row["competicion_codigo"],
            "competitionLabel": competition_label(row["competicion_codigo"]),
            "home": row["equipo_local"],
            "away": row["equipo_visitante"],
            "status": row["estado"],
        }
        for _, row in rows.iterrows()
    ]


def result_rows(rows):
    rows = rows.sort_values("fecha_utc", ascending=False)
    return [
        {
            "date": format_date(row["fecha_local"]),
            "dateOnly": format_date_only(row["fecha_local"]),
            "competition": row["competicion_codigo"],
            "competitionLabel": competition_label(row["competicion_codigo"]),
            "home": row["equipo_local"],
            "away": row["equipo_visitante"],
            "score": f"{int(row['goles_local_final'])}-{int(row['goles_visitante_final'])}",
        }
        for _, row in rows.iterrows()
    ]


def top_picks(matches, upcoming):
    picks = []
    for _, row in upcoming.sort_values("fecha_utc").head(100).iterrows():
        try:
            prediction = predict_match(
                matches,
                row["equipo_local"],
                row["equipo_visitante"],
                competition=row["competicion_codigo"],
            )
        except Exception:
            continue
        for market in prediction["market_suggestions"]:
            picks.append(
                {
                    "date": format_date(row["fecha_local"]),
                    "dateOnly": format_date_only(row["fecha_local"]),
                    "competition": row["competicion_codigo"],
                    "competitionLabel": competition_label(row["competicion_codigo"]),
                    "home": row["equipo_local"],
                    "away": row["equipo_visitante"],
                    "market": market["name"],
                    "probability": market["probability"],
                    "confidence": market["confidence"],
                }
            )
    return sorted(picks, key=lambda item: item["probability"], reverse=True)[:60]


def league_stats(finished):
    rows = []
    for competition, group in finished.groupby("competicion_codigo"):
        total_goals = group["goles_local_final"] + group["goles_visitante_final"]
        both_score = group["goles_local_final"].gt(0) & group["goles_visitante_final"].gt(0)
        rows.append(
            {
                "competition": competition,
                "competitionLabel": competition_label(competition),
                "matches": int(len(group)),
                "avgGoals": round(float(total_goals.mean()), 2),
                "over25": round(float(total_goals.gt(2.5).mean() * 100), 1),
                "bothScore": round(float(both_score.mean() * 100), 1),
            }
        )
    return sorted(rows, key=lambda item: item["matches"], reverse=True)


def monthly_goals(finished):
    data = finished.dropna(subset=["fecha_local"]).copy()
    data["month"] = data["fecha_local"].dt.strftime("%Y-%m")
    data["total_goals"] = data["goles_local_final"] + data["goles_visitante_final"]
    grouped = data.groupby("month")["total_goals"].mean().tail(18)
    return [{"label": index, "value": round(float(value), 2)} for index, value in grouped.items()]


def result_split(finished):
    return [
        {"label": "Local", "value": int(finished["ganador"].eq("HOME_TEAM").sum())},
        {"label": "Empate", "value": int(finished["ganador"].eq("DRAW").sum())},
        {"label": "Visitante", "value": int(finished["ganador"].eq("AWAY_TEAM").sum())},
    ]


def backtest_payload(matches):
    try:
        results, probabilities = evaluate_predictions(matches, limit=120)
        summary = summarize_backtest(results)
        hits = int(results["acierto"].sum()) if not results.empty else 0
        total = int(len(results))
        accuracy = round((hits / total) * 100, 1) if total else 0
        brier = brier_score(probabilities)
        return {
            "sampleSize": total,
            "hits": hits,
            "accuracy": accuracy,
            "brier": brier,
            "summary": summary.to_dict(orient="records"),
            "details": backtest_details(results.tail(120)),
        }
    except Exception as error:
        return {"sampleSize": 0, "hits": 0, "accuracy": 0, "brier": None, "summary": [], "details": [], "error": str(error)}


def backtest_details(results):
    if results.empty:
        return []

    rows = results.sort_values("fecha", ascending=False)
    output = []
    for _, row in rows.iterrows():
        output.append(
            {
                "date": format_date(row["fecha"]),
                "competition": row["competicion"],
                "competitionLabel": competition_label(row["competicion"]),
                "match": f"{row['local']} vs {row['visitante']}",
                "prediction": row["mercado"],
                "probability": float(row["probabilidad"]),
                "confidence": row["confianza"],
                "score": row["marcador"],
                "hit": bool(row["acierto"]),
            }
        )
    return output


def data_health(matches):
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
    rows = []
    for column in columns:
        if column not in matches.columns:
            continue
        rows.append(
            {
                "column": column,
                "nonEmpty": int(matches[column].notna().sum()),
                "nonZero": int(matches[column].fillna(0).ne(0).sum()),
            }
        )
    return rows


def format_date(value):
    if pd.isna(value):
        return ""
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M")


def format_date_only(value):
    if pd.isna(value):
        return ""
    return pd.Timestamp(value).strftime("%Y-%m-%d")


HTML_TEMPLATE = r"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Agente Deportivo</title>
  <style>
    :root {
      --bg: #eef2f7;
      --panel: #ffffff;
      --ink: #172033;
      --muted: #667085;
      --line: #d7dde8;
      --nav: #111827;
      --accent: #0f766e;
      --accent2: #2563eb;
      --warn: #b45309;
      --good: #15803d;
      --bad: #b91c1c;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      grid-template-columns: 290px minmax(0, 1fr);
      background: var(--bg);
      color: var(--ink);
      font-family: Segoe UI, Arial, sans-serif;
    }
    aside {
      background: var(--nav);
      color: white;
      padding: 22px 16px;
      min-height: 100vh;
      position: sticky;
      top: 0;
    }
    aside h1 { margin: 0 0 4px; font-size: 24px; }
    aside p { margin: 0 0 18px; color: #cbd5e1; font-size: 13px; line-height: 1.4; }
    nav { display: grid; gap: 8px; }
    nav button {
      width: 100%;
      min-height: 42px;
      border: 1px solid #334155;
      background: #1f2937;
      color: white;
      border-radius: 7px;
      text-align: left;
      padding: 9px 11px;
      cursor: pointer;
      font-size: 14px;
    }
    nav button.active { background: var(--accent); border-color: var(--accent); }
    main { padding: 22px; max-width: 1500px; width: 100%; }
    .topbar {
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: center;
      margin-bottom: 16px;
    }
    .topbar h2 { margin: 0; font-size: 26px; }
    .topbar span { color: var(--muted); font-size: 13px; }
    .view { display: none; }
    .view.active { display: block; }
    .controls {
      display: grid;
      grid-template-columns: repeat(4, minmax(160px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
      align-items: end;
    }
    label { display: block; color: var(--muted); font-size: 12px; margin-bottom: 6px; }
    select, input {
      width: 100%;
      height: 40px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: white;
      color: var(--ink);
      padding: 0 10px;
      font-size: 14px;
    }
    .action {
      height: 40px;
      border: 0;
      border-radius: 7px;
      background: var(--accent);
      color: white;
      font-weight: 650;
      cursor: pointer;
    }
    .cards {
      display: grid;
      grid-template-columns: repeat(6, minmax(120px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }
    .card, .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .card { padding: 14px; min-height: 82px; }
    .card span { display: block; color: var(--muted); font-size: 12px; margin-bottom: 8px; }
    .card strong { font-size: 24px; line-height: 1; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
    .panel { padding: 16px; min-width: 0; }
    .panel h3 { margin: 0 0 12px; font-size: 17px; }
    .table-wrap { max-height: 420px; overflow: auto; border: 1px solid var(--line); border-radius: 7px; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { padding: 9px 8px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
    th { background: #f8fafc; color: var(--muted); position: sticky; top: 0; }
    canvas { width: 100%; height: 260px; display: block; }
    .pill { display: inline-block; padding: 3px 8px; border-radius: 999px; background: #e0f2fe; color: #075985; font-size: 12px; white-space: nowrap; }
    .alta { background: #dcfce7; color: var(--good); }
    .media-alta { background: #e0f2fe; color: #0369a1; }
    .media { background: #fef3c7; color: var(--warn); }
    .prediction {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin-top: 8px;
    }
    .big-prob { display: grid; gap: 10px; }
    .bar-row { display: grid; grid-template-columns: 120px 1fr 54px; gap: 8px; align-items: center; }
    .bar { height: 12px; background: #e5e7eb; border-radius: 999px; overflow: hidden; }
    .bar div { height: 100%; background: var(--accent2); }
    .empty { color: var(--muted); padding: 18px; }
    @media (max-width: 980px) {
      body { grid-template-columns: 1fr; }
      aside { position: relative; min-height: auto; }
      .controls, .grid, .prediction { grid-template-columns: 1fr; }
      .cards { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
      main { padding: 14px; }
    }
  </style>
</head>
<body>
  <aside>
    <h1>Agente Deportivo</h1>
    <p>Selecciona que quieres analizar. Todo corre local con los datos descargados.</p>
    <nav id="menu"></nav>
  </aside>
  <main>
    <div class="topbar">
      <div>
        <h2 id="viewTitle">Panel</h2>
        <span id="viewHint">Metricas y pronosticos visuales</span>
      </div>
      <span id="updatedAt"></span>
    </div>

    <section id="view-predict" class="view"></section>
    <section id="view-date" class="view"></section>
    <section id="view-results" class="view"></section>
    <section id="view-picks" class="view"></section>
    <section id="view-profile" class="view"></section>
    <section id="view-search" class="view"></section>
    <section id="view-backtest" class="view"></section>
    <section id="view-health" class="view"></section>
  </main>

  <script>
    const DATA = __DASHBOARD_DATA__;
    const MENU = [
      ["predict", "1. Pronosticar partido especifico", "Elige liga, local y visitante para ver probabilidades y mercados."],
      ["date", "2. Ver partidos por fecha", "Calendario de partidos programados."],
      ["results", "3. Ver resultados por fecha", "Marcadores finalizados por dia y liga."],
      ["picks", "4. Ver mejores picks", "Oportunidades ordenadas por probabilidad."],
      ["profile", "5. Ver ficha completa de equipo", "Forma, tabla y tendencias del equipo."],
      ["search", "6. Buscar equipos", "Encuentra nombres oficiales en la data."],
      ["backtest", "7. Medir precision con backtest", "Precision historica de mercados sugeridos."],
      ["health", "8. Revisar datos avanzados", "Disponibilidad de corners, tarjetas y estadisticas extra."]
    ];
    const COLORS = ["#0f766e", "#2563eb", "#b45309", "#7c3aed", "#be123c", "#15803d", "#475569"];
    let activeView = "predict";

    init();

    function init() {
      document.getElementById("menu").innerHTML = MENU.map(([id, label]) =>
        `<button data-view="${id}">${label}</button>`
      ).join("");
      document.querySelectorAll("nav button").forEach(btn => {
        btn.addEventListener("click", () => showView(btn.dataset.view));
      });
      document.getElementById("updatedAt").textContent = `Actualizado: ${DATA.generatedAt}`;
      renderAll();
      showView("predict");
    }

    function renderAll() {
      renderPredict();
      renderDate();
      renderResults();
      renderPicks();
      renderProfile();
      renderSearch();
      renderBacktest();
      renderHealth();
    }

    function showView(id) {
      activeView = id;
      document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
      document.getElementById(`view-${id}`).classList.add("active");
      document.querySelectorAll("nav button").forEach(b => b.classList.toggle("active", b.dataset.view === id));
      const meta = MENU.find(item => item[0] === id);
      document.getElementById("viewTitle").textContent = meta[1];
      document.getElementById("viewHint").textContent = meta[2];
      setTimeout(redrawCharts, 20);
    }

    function competitionSelect(id, includeAll = false) {
      const options = includeAll ? [`<option value="ALL">Todas las ligas</option>`] : "";
      return `<select id="${id}">${options}${DATA.competitions.map(c => `<option value="${c.code}">${c.label}</option>`).join("")}</select>`;
    }

    function teamSelect(id, competition = "ALL") {
      const teams = DATA.teamsByCompetition[competition] || DATA.teamsByCompetition.ALL;
      return `<select id="${id}">${teams.map(team => `<option value="${escapeHtml(team)}">${escapeHtml(team)}</option>`).join("")}</select>`;
    }

    function renderPredict() {
      const el = document.getElementById("view-predict");
      el.innerHTML = `
        <div class="controls">
          <div><label>Liga</label>${competitionSelect("predictCompetition")}</div>
          <div><label>Local</label><span id="homeSlot"></span></div>
          <div><label>Visitante</label><span id="awaySlot"></span></div>
          <button class="action" id="predictBtn">Analizar partido</button>
        </div>
        <div id="predictionOutput"></div>
      `;
      const comp = document.getElementById("predictCompetition");
      const refreshTeams = () => {
        document.getElementById("homeSlot").innerHTML = teamSelect("homeTeam", comp.value);
        document.getElementById("awaySlot").innerHTML = teamSelect("awayTeam", comp.value);
      };
      comp.addEventListener("change", refreshTeams);
      refreshTeams();
      document.getElementById("predictBtn").addEventListener("click", updatePrediction);
      updatePrediction();
    }

    function updatePrediction() {
      const competition = document.getElementById("predictCompetition").value;
      const home = document.getElementById("homeTeam").value;
      const away = document.getElementById("awayTeam").value;
      const prediction = predictVisual(competition, home, away);
      const output = document.getElementById("predictionOutput");
      output.innerHTML = `
        <div class="cards">
          <article class="card"><span>Gana local</span><strong>${prediction.homeWin}%</strong></article>
          <article class="card"><span>Empate</span><strong>${prediction.draw}%</strong></article>
          <article class="card"><span>Gana visitante</span><strong>${prediction.awayWin}%</strong></article>
          <article class="card"><span>Goles esperados</span><strong>${prediction.totalGoals}</strong></article>
          <article class="card"><span>Over 1.5</span><strong>${prediction.over15}%</strong></article>
          <article class="card"><span>Over 2.5</span><strong>${prediction.over25}%</strong></article>
          <article class="card"><span>Marcador probable</span><strong style="font-size:18px">${prediction.topScore}</strong></article>
        </div>
        <div class="prediction">
          <div class="panel">
            <h3>Probabilidades</h3>
            <div class="big-prob">
              ${probBar(home, prediction.homeWin)}
              ${probBar("Empate", prediction.draw)}
              ${probBar(away, prediction.awayWin)}
            </div>
          </div>
          <div class="panel">
            <h3>Mercados sugeridos</h3>
            ${prediction.markets.length ? prediction.markets.map((m, i) => `<p>${i + 1}. ${m.name} - <b>${m.prob}%</b> <span class="pill ${m.confidence}">${m.confidence}</span></p>`).join("") : "<p class='empty'>No hay mercado fuerte con estos datos.</p>"}
          </div>
        </div>
        <div class="panel">
          <h3>Marcadores mas probables</h3>
          <p class="empty" style="padding:0 0 10px">Son ~100 marcadores posibles, por eso cada uno individual da un porcentaje bajo (normal). Para decisiones conviene mirar los mercados agrupados de arriba (1X2, over/under, ambos marcan), no un marcador exacto solo.</p>
          ${prediction.topScores.map((s, i) => `<p>${i + 1}. ${s.score} - <b>${s.prob}%</b></p>`).join("")}
        </div>
        <div class="grid">
          ${statPanel("Corners", "corners", predictStat("corners", competition, home, away, CORNER_LINES))}
          ${statPanel("Tarjetas amarillas", "amarillas", predictStat("cards", competition, home, away, CARD_LINES))}
        </div>
        <div class="grid">
          <div class="panel"><h3>Local</h3>${teamBlock(competition, home, "home")}</div>
          <div class="panel"><h3>Visitante</h3>${teamBlock(competition, away, "away")}</div>
        </div>
      `;
    }

    function factorial(n) {
      let result = 1;
      for (let i = 2; i <= n; i++) result *= i;
      return result;
    }

    function poissonPmf(k, lambda) {
      if (lambda <= 0) return k === 0 ? 1 : 0;
      return Math.exp(-lambda) * Math.pow(lambda, k) / factorial(k);
    }

    function dixonColesTau(x, y, lambdaHome, lambdaAway, rho) {
      if (x === 0 && y === 0) return 1 - (lambdaHome * lambdaAway * rho);
      if (x === 0 && y === 1) return 1 + (lambdaHome * rho);
      if (x === 1 && y === 0) return 1 + (lambdaAway * rho);
      if (x === 1 && y === 1) return 1 - rho;
      return 1;
    }

    function scoreMatrix(lambdaHome, lambdaAway, rho, maxGoals = 10) {
      const size = maxGoals + 1;
      const matrix = [];
      let total = 0;
      for (let i = 0; i < size; i++) {
        const row = [];
        for (let j = 0; j < size; j++) {
          let p = poissonPmf(i, lambdaHome) * poissonPmf(j, lambdaAway);
          if (i <= 1 && j <= 1) p *= dixonColesTau(i, j, lambdaHome, lambdaAway, rho);
          p = Math.max(0, p);
          row.push(p);
          total += p;
        }
        matrix.push(row);
      }
      if (total > 0) {
        for (let i = 0; i < size; i++) for (let j = 0; j < size; j++) matrix[i][j] /= total;
      }
      return matrix;
    }

    function marketsFromMatrix(matrix) {
      const size = matrix.length;
      let homeWin = 0, draw = 0, awayWin = 0, over15 = 0, over25 = 0;
      let homeZero = 0, awayZero = 0;
      const scores = [];
      for (let j = 0; j < size; j++) homeZero += matrix[0][j];
      for (let i = 0; i < size; i++) awayZero += matrix[i][0];
      const bothZero = matrix[0][0];
      for (let i = 0; i < size; i++) {
        for (let j = 0; j < size; j++) {
          const p = matrix[i][j];
          scores.push([i, j, p]);
          if (i > j) homeWin += p; else if (i === j) draw += p; else awayWin += p;
          if (i + j >= 2) over15 += p;
          if (i + j >= 3) over25 += p;
        }
      }
      const btts = Math.max(0, 1 - homeZero - awayZero + bothZero);
      scores.sort((a, b) => b[2] - a[2]);
      return { homeWin, draw, awayWin, over15, over25, btts, topScores: scores.slice(0, 5) };
    }

    function getStrength(competition, team) {
      const comp = DATA.teamStrengths[competition];
      if (comp && comp.teams[team]) return comp.teams[team];
      return { attack: 1, defense: 1 };
    }

    // Mismas lineas y misma muestra minima confiable que usa predictor.py.
    const CORNER_LINES = [7.5, 8.5, 9.5, 10.5, 11.5];
    const CARD_LINES = [2.5, 3.5, 4.5, 5.5];
    const RELIABLE_STAT_SAMPLE = 60;

    function poissonCdf(k, lambda) {
      let total = 0;
      for (let i = 0; i <= k; i++) total += poissonPmf(i, lambda);
      return Math.min(1, total);
    }

    function predictStat(statKey, competition, home, away, lines) {
      const byCompetition = DATA.statStrengths[statKey];
      const comp = byCompetition ? byCompetition[competition] : null;
      if (!comp) return null;

      const h = comp.teams[home] || { attack: 1, defense: 1 };
      const a = comp.teams[away] || { attack: 1, defense: 1 };
      const lambdaHome = Math.max(0.1, h.attack * a.defense * comp.leagueAvgHome);
      const lambdaAway = Math.max(0.1, a.attack * h.defense * comp.leagueAvgAway);
      const total = lambdaHome + lambdaAway;

      const rows = lines.map(line => {
        const over = Math.max(0, Math.min(1, 1 - poissonCdf(Math.floor(line), total)));
        return { line, over: round(over * 100, 1), under: round((1 - over) * 100, 1) };
      });

      let best = null;
      rows.forEach(r => {
        [["Over", r.over], ["Under", r.under]].forEach(([side, prob]) => {
          if (!best || prob > best.prob) best = { name: `${side} ${r.line}`, prob };
        });
      });

      return {
        expectedTotal: round(total, 2),
        expectedHome: round(lambdaHome, 2),
        expectedAway: round(lambdaAway, 2),
        sample: comp.sample,
        shortSample: comp.sample < RELIABLE_STAT_SAMPLE,
        lines: rows,
        best,
      };
    }

    function statPanel(title, unit, projection) {
      if (!projection) {
        return `<div class="panel"><h3>${title}</h3>
          <p class="empty">Sin datos suficientes todavia en esta liga.<br>
          Para habilitarlo corre: <code>python api_football.py --mode stats</code></p></div>`;
      }
      const aviso = projection.shortSample
        ? `<p class="empty" style="padding:0 0 8px">Muestra corta (${projection.sample} partidos): tomar con pinzas.</p>`
        : `<p class="empty" style="padding:0 0 8px">Muestra: ${projection.sample} partidos.</p>`;
      const ladder = projection.lines
        .map(r => `<p>Over ${r.line} ${unit} - <b>${r.over}%</b> <span style="opacity:.6">/ Under ${r.under}%</span></p>`)
        .join("");
      return `<div class="panel"><h3>${title}</h3>
        <p style="margin:0 0 6px">Proyeccion: <b>${projection.expectedTotal}</b>
        (${projection.expectedHome} local + ${projection.expectedAway} visitante)</p>
        ${aviso}${ladder}
        <p style="margin-top:8px">Mejor mercado: <b>${projection.best.name} ${unit} - ${projection.best.prob}%</b></p>
      </div>`;
    }

    function predictVisual(competition, home, away) {
      const comp = DATA.teamStrengths[competition];
      const rho = DATA.modelConfig.rho;
      const leagueHome = comp ? comp.leagueAvgHome : 1.45;
      const leagueAway = comp ? comp.leagueAvgAway : 1.15;
      const homeStrength = getStrength(competition, home);
      const awayStrength = getStrength(competition, away);
      const lambdaHome = Math.max(0.08, homeStrength.attack * awayStrength.defense * leagueHome);
      const lambdaAway = Math.max(0.08, awayStrength.attack * homeStrength.defense * leagueAway);
      const matrix = scoreMatrix(lambdaHome, lambdaAway, rho);
      const result = marketsFromMatrix(matrix);

      const homeWin = round(result.homeWin * 100, 1);
      const draw = round(result.draw * 100, 1);
      const awayWin = round(result.awayWin * 100, 1);
      const totalGoals = round(lambdaHome + lambdaAway, 2);
      const over15 = round(result.over15 * 100, 1);
      const over25 = round(result.over25 * 100, 1);
      const btts = round(result.btts * 100, 1);
      const topScores = result.topScores.map(s => ({ score: `${s[0]}-${s[1]}`, prob: round(s[2] * 100, 1) }));
      const topScore = topScores.length ? `${topScores[0].score} (${topScores[0].prob}%)` : "-";

      const markets = [];
      addMarket(markets, "Over 1.5 goles", over15, 70);
      addMarket(markets, "Over 2.5 goles", over25, 72);
      addMarket(markets, `${home} o empate`, round(homeWin + draw, 1), 64);
      addMarket(markets, `${away} o empate`, round(awayWin + draw, 1), 64);
      addMarket(markets, "Ambos equipos marcan", btts, 62);
      return { homeWin, draw, awayWin, totalGoals, over15, over25, btts, topScore, topScores, markets: markets.sort((x, y) => y.prob - x.prob) };
    }

    function renderDate() {
      const el = document.getElementById("view-date");
      el.innerHTML = controlsDate("dateCompetition", "dateInput", "Ver partidos") + `<div class="panel"><div class="table-wrap"><table id="dateTable"></table></div></div>`;
      document.getElementById("dateBtn").addEventListener("click", updateDate);
      setDefaultDate("dateInput", DATA.upcoming[0]?.dateOnly);
      updateDate();
    }

    function updateDate() {
      const comp = document.getElementById("dateCompetition").value;
      const date = document.getElementById("dateInput").value;
      const rows = DATA.upcoming.filter(r => (comp === "ALL" || r.competition === comp) && (!date || r.dateOnly === date));
      table("dateTable", ["Fecha", "Liga", "Partido", "Estado"], rows.map(r => [r.date, r.competitionLabel, `${r.home} vs ${r.away}`, r.status]));
    }

    function renderResults() {
      const el = document.getElementById("view-results");
      el.innerHTML = controlsDate("resultsCompetition", "resultsInput", "Ver resultados", "resultsBtn") + `<div class="panel"><div class="table-wrap"><table id="resultsTable"></table></div></div>`;
      document.getElementById("resultsBtn").addEventListener("click", updateResults);
      setDefaultDate("resultsInput", DATA.results[0]?.dateOnly);
      updateResults();
    }

    function updateResults() {
      const comp = document.getElementById("resultsCompetition").value;
      const date = document.getElementById("resultsInput").value;
      const rows = DATA.results.filter(r => (comp === "ALL" || r.competition === comp) && (!date || r.dateOnly === date));
      table("resultsTable", ["Fecha", "Liga", "Partido", "Marcador"], rows.map(r => [r.date, r.competitionLabel, `${r.home} vs ${r.away}`, r.score]));
    }

    function renderPicks() {
      const el = document.getElementById("view-picks");
      el.innerHTML = `
        <div class="controls">
          <div><label>Liga</label>${competitionSelect("picksCompetition", true)}</div>
          <div><label>Fecha</label><input id="picksDate" type="date"></div>
          <div><label>Mercado</label><input id="picksMarket" placeholder="Over, empate, marcan..."></div>
          <button class="action" id="picksBtn">Filtrar picks</button>
        </div>
        <div class="grid">
          <div class="panel"><h3>Top picks</h3><div class="table-wrap"><table id="picksTable"></table></div></div>
          <div class="panel"><h3>Probabilidad por pick</h3><canvas id="picksChart"></canvas></div>
        </div>`;
      document.getElementById("picksBtn").addEventListener("click", updatePicks);
      updatePicks();
    }

    function updatePicks() {
      const comp = document.getElementById("picksCompetition").value;
      const date = document.getElementById("picksDate").value;
      const market = document.getElementById("picksMarket").value.toLowerCase();
      const rows = DATA.picks.filter(r =>
        (comp === "ALL" || r.competition === comp) &&
        (!date || r.dateOnly === date) &&
        (!market || r.market.toLowerCase().includes(market))
      ).slice(0, 20);
      table("picksTable", ["Fecha", "Liga", "Partido", "Mercado", "Prob.", "Conf."], rows.map(r => [r.date, r.competitionLabel, `${r.home} vs ${r.away}`, r.market, `${r.probability}%`, pill(r.confidence)]));
      drawBar("picksChart", rows.map(r => r.market), rows.map(r => r.probability), "#0f766e");
    }

    function renderProfile() {
      const el = document.getElementById("view-profile");
      el.innerHTML = `
        <div class="controls">
          <div><label>Liga</label>${competitionSelect("profileCompetition")}</div>
          <div><label>Equipo</label><span id="profileTeamSlot"></span></div>
          <button class="action" id="profileBtn">Ver ficha</button>
        </div>
        <div id="profileOutput"></div>`;
      const comp = document.getElementById("profileCompetition");
      const refresh = () => { document.getElementById("profileTeamSlot").innerHTML = teamSelect("profileTeam", comp.value); };
      comp.addEventListener("change", refresh);
      refresh();
      document.getElementById("profileBtn").addEventListener("click", updateProfile);
      updateProfile();
    }

    function updateProfile() {
      const comp = document.getElementById("profileCompetition").value;
      const team = document.getElementById("profileTeam").value;
      const metrics = getMetric(comp, team);
      const standing = findStanding(comp, team);
      document.getElementById("profileOutput").innerHTML = `
        <div class="cards">
          <article class="card"><span>Posicion</span><strong>${standing ? standing.position + "/" + standing.teams : "-"}</strong></article>
          <article class="card"><span>Puntos</span><strong>${standing ? standing.points : "-"}</strong></article>
          <article class="card"><span>Zona</span><strong style="font-size:16px">${standing ? standing.zone : "-"}</strong></article>
          <article class="card"><span>Ultimos 10</span><strong>${metrics.recent10.wins}G-${metrics.recent10.draws}E-${metrics.recent10.losses}P</strong></article>
          <article class="card"><span>GF prom.</span><strong>${metrics.recent10.goals_for_avg}</strong></article>
          <article class="card"><span>GC prom.</span><strong>${metrics.recent10.goals_against_avg}</strong></article>
        </div>
        <div class="grid">
          <div class="panel"><h3>Forma</h3>${teamBlock(comp, team, "home")}</div>
          <div class="panel"><h3>Tendencias</h3><canvas id="profileChart"></canvas></div>
        </div>`;
      drawBar("profileChart", ["Over 1.5", "Over 2.5", "Ambos marcan"], [metrics.recent10.over_15_rate, metrics.recent10.over_25_rate, metrics.recent10.both_score_rate], "#2563eb");
    }

    function renderSearch() {
      const el = document.getElementById("view-search");
      el.innerHTML = `<div class="controls"><div><label>Buscar equipo</label><input id="searchTeam" placeholder="Barcelona, Madrid, Monaco..."></div></div><div class="panel"><div class="table-wrap"><table id="searchTable"></table></div></div>`;
      document.getElementById("searchTeam").addEventListener("input", updateSearch);
      updateSearch();
    }

    function updateSearch() {
      const q = document.getElementById("searchTeam").value.toLowerCase();
      const rows = DATA.teamsByCompetition.ALL.filter(t => !q || t.toLowerCase().includes(q)).slice(0, 80);
      table("searchTable", ["Equipo"], rows.map(r => [r]));
    }

    function renderBacktest() {
      const el = document.getElementById("view-backtest");
      el.innerHTML = `
        <div class="cards">
          <article class="card"><span>Precision total</span><strong>${DATA.backtest.accuracy}%</strong></article>
          <article class="card"><span>Pronosticos evaluados</span><strong>${DATA.backtest.sampleSize}</strong></article>
          <article class="card"><span>Aciertos</span><strong>${DATA.backtest.hits}</strong></article>
          <article class="card"><span>Fallos</span><strong>${DATA.backtest.sampleSize - DATA.backtest.hits}</strong></article>
          <article class="card"><span>Brier score (1X2)</span><strong>${DATA.backtest.brier ?? "-"}</strong></article>
        </div>
        <p class="empty" style="padding:0 0 4px">Brier score: 0 es perfecto, 0.667 equivale a adivinar al azar. Mide que tan bien calibradas estan las probabilidades, no solo los aciertos.</p>
        <div class="grid">
          <div class="panel"><h3>Precision por mercado</h3><div class="table-wrap"><table id="backtestTable"></table></div></div>
          <div class="panel"><h3>Precision visual</h3><canvas id="backtestChart"></canvas></div>
        </div>
        <div class="panel">
          <h3>Detalle auditable</h3>
          <div class="table-wrap"><table id="backtestDetailsTable"></table></div>
        </div>`;
      table("backtestTable", ["Mercado", "Pronosticos", "Aciertos", "Precision", "Prob. prom."], DATA.backtest.summary.map(r => [r.grupo, r.pronosticos, r.aciertos, `${r.precision}%`, `${r.prob_promedio}%`]));
      drawBar("backtestChart", DATA.backtest.summary.map(r => r.grupo), DATA.backtest.summary.map(r => r.precision), "#7c3aed");
      table("backtestDetailsTable", ["Fecha", "Liga", "Partido", "Prediccion", "Prob.", "Resultado", "Estado"], DATA.backtest.details.map(r => [
        r.date,
        r.competitionLabel,
        r.match,
        r.prediction,
        `${r.probability}%`,
        r.score,
        r.hit ? `<span class="pill alta">Acerto</span>` : `<span class="pill media">Fallo</span>`
      ]));
    }

    function renderHealth() {
      const el = document.getElementById("view-health");
      el.innerHTML = `<div class="panel"><h3>Datos avanzados disponibles</h3><div class="table-wrap"><table id="healthTable"></table></div></div>`;
      table("healthTable", ["Campo", "Con dato", "Distinto de 0"], DATA.dataHealth.map(r => [r.column, r.nonEmpty, r.nonZero]));
    }

    function controlsDate(compId, dateId, buttonText, buttonId = "dateBtn") {
      return `<div class="controls"><div><label>Liga</label>${competitionSelect(compId, true)}</div><div><label>Fecha</label><input id="${dateId}" type="date"></div><button class="action" id="${buttonId}">${buttonText}</button></div>`;
    }

    function setDefaultDate(id, value) {
      if (value) document.getElementById(id).value = value;
    }

    function getMetric(comp, team) {
      return DATA.teamMetrics[`${comp}::${team}`] || { recent10: emptySummary(), recent5: emptySummary(), home: emptySummary(), away: emptySummary() };
    }

    function emptySummary() {
      return { matches: 0, wins: 0, draws: 0, losses: 0, points_per_match: 0, goals_for_avg: 0, goals_against_avg: 0, over_15_rate: 0, over_25_rate: 0, both_score_rate: 0 };
    }

    function findStanding(comp, team) {
      return (DATA.standings[comp] || []).find(r => r.team === team);
    }

    function addMarket(markets, name, prob, threshold) {
      if (prob >= threshold) markets.push({ name, prob, confidence: confidence(prob) });
    }

    function confidence(prob) {
      if (prob >= 72) return "alta";
      if (prob >= 62) return "media-alta";
      if (prob >= 55) return "media";
      return "baja";
    }

    function teamBlock(comp, team) {
      const m = getMetric(comp, team);
      return `<p><b>${team}</b></p>
        <p>Ultimos 5: ${m.recent5.wins}G-${m.recent5.draws}E-${m.recent5.losses}P</p>
        <p>Ultimos 10: ${m.recent10.wins}G-${m.recent10.draws}E-${m.recent10.losses}P</p>
        <p>Local: GF ${m.home.goals_for_avg}, GC ${m.home.goals_against_avg}</p>
        <p>Visitante: GF ${m.away.goals_for_avg}, GC ${m.away.goals_against_avg}</p>`;
    }

    function probBar(label, value) {
      return `<div class="bar-row"><span>${escapeHtml(label)}</span><div class="bar"><div style="width:${value}%"></div></div><b>${value}%</b></div>`;
    }

    function table(id, headers, rows) {
      const el = document.getElementById(id);
      el.innerHTML = `<thead><tr>${headers.map(h => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody>`;
      if (!rows.length) el.innerHTML += `<tbody><tr><td colspan="${headers.length}" class="empty">No hay datos para mostrar.</td></tr></tbody>`;
    }

    function drawBar(id, labels, values, color) {
      const canvas = document.getElementById(id);
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(320, Math.floor(rect.width));
      canvas.height = 260;
      const ctx = canvas.getContext("2d");
      const width = canvas.width, height = canvas.height, pad = 38;
      const max = Math.max(...values, 1);
      ctx.clearRect(0, 0, width, height);
      const step = (width - pad - 16) / Math.max(labels.length, 1);
      const bw = Math.max(8, step - 8);
      values.forEach((v, i) => {
        const x = pad + i * step;
        const h = (height - pad * 2) * (v / max);
        ctx.fillStyle = color;
        ctx.fillRect(x, height - pad - h, bw, h);
        ctx.fillStyle = "#667085";
        ctx.font = "11px Segoe UI";
        ctx.save();
        ctx.translate(x, height - 8);
        ctx.rotate(-0.45);
        ctx.fillText(short(labels[i]), 0, 0);
        ctx.restore();
      });
    }

    function redrawCharts() {
      if (activeView === "picks") updatePicks();
      if (activeView === "profile") updateProfile();
      if (activeView === "backtest") renderBacktest();
    }

    function pill(text) { return `<span class="pill ${text}">${text}</span>`; }
    function clamp(v, min, max) { return Math.max(min, Math.min(max, v)); }
    function round(v, d) { return Number(v.toFixed(d)); }
    function short(v) { return String(v || "").length > 16 ? String(v).slice(0, 15) + "." : String(v || ""); }
    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[c]));
    }
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
