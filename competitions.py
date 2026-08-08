from data_loader import normalize_text


COMPETITION_ALIASES = {
    "premier": "PL",
    "premier league": "PL",
    "inglaterra": "PL",
    "inglaterra primera": "PL",
    "england": "PL",
    "laliga": "PD",
    "la liga": "PD",
    "liga española": "PD",
    "liga espanola": "PD",
    "españa": "PD",
    "espana": "PD",
    "spain": "PD",
    "serie a": "SA",
    "italia": "SA",
    "italy": "SA",
    "bundesliga": "BL1",
    "alemania": "BL1",
    "germany": "BL1",
    "ligue 1": "FL1",
    "francia": "FL1",
    "france": "FL1",
    "eredivisie": "DED",
    "holanda": "DED",
    "netherlands": "DED",
    "portugal": "PPL",
    "primeira liga": "PPL",
    "brasil": "BSA",
    "brasileirao": "BSA",
    "brasileirão": "BSA",
    "champions": "CL",
    "champions league": "CL",
    "ucl": "CL",
    "libertadores": "CLI",
    "copa libertadores": "CLI",
    "championship": "ELC",
    "colombia": "COL",
    "primera a": "COL",
    "liga betplay": "COL",
    "betplay": "COL",
    "dimayor": "COL",
    "liga colombiana": "COL",
    "primera b": "COLB",
    "argentina": "ARG",
    "liga argentina": "ARG",
    "liga profesional": "ARG",
    "mexico": "MEX",
    "méxico": "MEX",
    "liga mx": "MEX",
    "mls": "MLS",
    "estados unidos": "MLS",
    "europa league": "EL",
    "europa": "EL",
    "uel": "EL",
    "sudamericana": "CSU",
    "copa sudamericana": "CSU",
    "belgica": "JPL",
    "bélgica": "JPL",
    "escocia": "SPFL",
    "2 bundesliga": "BL2",
    "segunda bundesliga": "BL2",
}


COMPETITION_LABELS = {
    "COL": "Primera A (Colombia)",
    "COLB": "Primera B (Colombia)",
    "PL": "Premier League",
    "ELC": "Championship",
    "PD": "LaLiga",
    "SA": "Serie A",
    "BL1": "Bundesliga",
    "BL2": "2. Bundesliga",
    "FL1": "Ligue 1",
    "DED": "Eredivisie",
    "PPL": "Primeira Liga",
    "JPL": "Jupiler Pro League",
    "SPFL": "Scottish Premiership",
    "BSA": "Brasileirao",
    "ARG": "Liga Profesional Argentina",
    "MEX": "Liga MX",
    "MLS": "Major League Soccer",
    "CL": "Champions League",
    "EL": "Europa League",
    "CLI": "Copa Libertadores",
    "CSU": "Copa Sudamericana",
}


def resolve_competition(value):
    if not value:
        return None

    normalized = normalize_text(value)
    upper = value.strip().upper()
    if upper in COMPETITION_LABELS:
        return upper

    return COMPETITION_ALIASES.get(normalized)


def competition_label(code):
    if not code:
        return "automatica"
    return COMPETITION_LABELS.get(code, code)
