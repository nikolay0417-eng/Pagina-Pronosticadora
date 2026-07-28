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
}


COMPETITION_LABELS = {
    "PL": "Premier League",
    "PD": "LaLiga",
    "SA": "Serie A",
    "BL1": "Bundesliga",
    "FL1": "Ligue 1",
    "DED": "Eredivisie",
    "PPL": "Primeira Liga",
    "BSA": "Brasileirao",
    "CL": "Champions League",
    "CLI": "Copa Libertadores",
    "ELC": "Championship",
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
