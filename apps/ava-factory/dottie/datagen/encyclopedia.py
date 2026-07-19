"""Phase-2 fact corpus with heavy paraphrase coverage of the canonical
J-space eval entities (spider/ant leg counts, France/China facts, soccer vs
rugby, Spanish/French parallel sentences) plus general animal, country and
sport coverage. All facts live in a single fixed table per domain -- there
is exactly one source of truth per entity, so no doc can contradict another.
"""

from __future__ import annotations

from typing import Iterator

from dottie.datagen.base import Generator

# ---------------------------------------------------------------------------
# Fixed fact tables (single source of truth -- internally consistent)
# ---------------------------------------------------------------------------

# category -> (leg_count, habitat, diet, class_label)
_CATEGORY_INFO = {
    "insect": (6, "gardens, forests, and grasslands", "plants, nectar, and smaller insects", "insect"),
    "arachnid": (8, "webs, burrows, and dark corners", "insects and other small invertebrates", "arachnid"),
    "crustacean": (10, "oceans, rivers, and lakes", "algae and small aquatic creatures", "crustacean"),
    "mammal": (4, "forests, grasslands, and other terrestrial habitats", "plants and/or other animals depending on the species", "mammal"),
    "bird": (2, "trees, wetlands, and open skies", "seeds, insects, and/or small animals depending on the species", "bird"),
    "reptile": (4, "warm terrestrial and freshwater habitats", "insects and small animals", "reptile"),
    "snake": (0, "forests, deserts, and grasslands", "small animals swallowed whole", "reptile"),
    "amphibian": (4, "freshwater ponds and moist land habitats", "insects and other small invertebrates", "amphibian"),
    "fish": (0, "oceans, rivers, and lakes", "plankton, smaller fish, or aquatic plants depending on the species", "fish"),
}

_ANIMALS = {
    # insects (6 legs)
    "ant": "insect", "bee": "insect", "fly": "insect", "butterfly": "insect", "beetle": "insect",
    "grasshopper": "insect", "cockroach": "insect", "mosquito": "insect", "ladybug": "insect",
    "dragonfly": "insect", "wasp": "insect", "moth": "insect", "cricket": "insect", "termite": "insect",
    "aphid": "insect",
    # arachnids (8 legs)
    "spider": "arachnid", "scorpion": "arachnid", "tick": "arachnid", "mite": "arachnid", "harvestman": "arachnid",
    # crustaceans (10 legs)
    "crab": "crustacean", "lobster": "crustacean", "crayfish": "crustacean",
    # mammals (4 legs)
    "dog": "mammal", "cat": "mammal", "horse": "mammal", "cow": "mammal", "pig": "mammal", "sheep": "mammal",
    "goat": "mammal", "lion": "mammal", "tiger": "mammal", "elephant": "mammal", "zebra": "mammal",
    "giraffe": "mammal", "bear": "mammal", "wolf": "mammal", "fox": "mammal", "deer": "mammal",
    "rabbit": "mammal", "squirrel": "mammal", "kangaroo": "mammal", "koala": "mammal", "panda": "mammal",
    # birds (2 legs)
    "chicken": "bird", "duck": "bird", "goose": "bird", "eagle": "bird", "owl": "bird", "sparrow": "bird",
    "penguin": "bird", "ostrich": "bird", "flamingo": "bird", "parrot": "bird", "crow": "bird", "pigeon": "bird",
    # reptiles (4 legs)
    "lizard": "reptile", "turtle": "reptile", "crocodile": "reptile", "alligator": "reptile",
    "iguana": "reptile", "gecko": "reptile", "chameleon": "reptile",
    # snake (0 legs)
    "snake": "snake",
    # amphibians (4 legs)
    "frog": "amphibian", "toad": "amphibian", "salamander": "amphibian", "newt": "amphibian",
    # fish (0 legs)
    "goldfish": "fish", "shark": "fish", "salmon": "fish", "tuna": "fish", "trout": "fish",
}
assert len(_ANIMALS) >= 60, len(_ANIMALS)
assert _ANIMALS["spider"] == "arachnid" and _CATEGORY_INFO["arachnid"][0] == 8
assert _ANIMALS["ant"] == "insect" and _CATEGORY_INFO["insect"][0] == 6

# country -> (capital, language, currency, continent)
_COUNTRIES = {
    "france": ("Paris", "French", "Euro", "Europe"),
    "china": ("Beijing", "Mandarin", "Yuan", "Asia"),
    "germany": ("Berlin", "German", "Euro", "Europe"),
    "italy": ("Rome", "Italian", "Euro", "Europe"),
    "spain": ("Madrid", "Spanish", "Euro", "Europe"),
    "portugal": ("Lisbon", "Portuguese", "Euro", "Europe"),
    "netherlands": ("Amsterdam", "Dutch", "Euro", "Europe"),
    "belgium": ("Brussels", "Dutch", "Euro", "Europe"),
    "greece": ("Athens", "Greek", "Euro", "Europe"),
    "poland": ("Warsaw", "Polish", "Zloty", "Europe"),
    "sweden": ("Stockholm", "Swedish", "Krona", "Europe"),
    "norway": ("Oslo", "Norwegian", "Krone", "Europe"),
    "denmark": ("Copenhagen", "Danish", "Krone", "Europe"),
    "finland": ("Helsinki", "Finnish", "Euro", "Europe"),
    "switzerland": ("Bern", "German", "Franc", "Europe"),
    "austria": ("Vienna", "German", "Euro", "Europe"),
    "ireland": ("Dublin", "English", "Euro", "Europe"),
    "united_kingdom": ("London", "English", "Pound", "Europe"),
    "russia": ("Moscow", "Russian", "Ruble", "Europe"),
    "ukraine": ("Kyiv", "Ukrainian", "Hryvnia", "Europe"),
    "turkey": ("Ankara", "Turkish", "Lira", "Asia"),
    "japan": ("Tokyo", "Japanese", "Yen", "Asia"),
    "south_korea": ("Seoul", "Korean", "Won", "Asia"),
    "north_korea": ("Pyongyang", "Korean", "Won", "Asia"),
    "india": ("New Delhi", "Hindi", "Rupee", "Asia"),
    "pakistan": ("Islamabad", "Urdu", "Rupee", "Asia"),
    "bangladesh": ("Dhaka", "Bengali", "Taka", "Asia"),
    "indonesia": ("Jakarta", "Indonesian", "Rupiah", "Asia"),
    "thailand": ("Bangkok", "Thai", "Baht", "Asia"),
    "vietnam": ("Hanoi", "Vietnamese", "Dong", "Asia"),
    "philippines": ("Manila", "Filipino", "Peso", "Asia"),
    "malaysia": ("Kuala Lumpur", "Malay", "Ringgit", "Asia"),
    "singapore": ("Singapore", "English", "Dollar", "Asia"),
    "saudi_arabia": ("Riyadh", "Arabic", "Riyal", "Asia"),
    "united_arab_emirates": ("Abu Dhabi", "Arabic", "Dirham", "Asia"),
    "israel": ("Jerusalem", "Hebrew", "Shekel", "Asia"),
    "iran": ("Tehran", "Persian", "Rial", "Asia"),
    "iraq": ("Baghdad", "Arabic", "Dinar", "Asia"),
    "egypt": ("Cairo", "Arabic", "Pound", "Africa"),
    "nigeria": ("Abuja", "English", "Naira", "Africa"),
    "kenya": ("Nairobi", "Swahili", "Shilling", "Africa"),
    "ethiopia": ("Addis Ababa", "Amharic", "Birr", "Africa"),
    "south_africa": ("Pretoria", "English", "Rand", "Africa"),
    "morocco": ("Rabat", "Arabic", "Dirham", "Africa"),
    "algeria": ("Algiers", "Arabic", "Dinar", "Africa"),
    "ghana": ("Accra", "English", "Cedi", "Africa"),
    "tanzania": ("Dodoma", "Swahili", "Shilling", "Africa"),
    "uganda": ("Kampala", "English", "Shilling", "Africa"),
    "united_states": ("Washington", "English", "Dollar", "North America"),
    "canada": ("Ottawa", "English", "Dollar", "North America"),
    "mexico": ("Mexico City", "Spanish", "Peso", "North America"),
    "cuba": ("Havana", "Spanish", "Peso", "North America"),
    "guatemala": ("Guatemala City", "Spanish", "Quetzal", "North America"),
    "jamaica": ("Kingston", "English", "Dollar", "North America"),
    "brazil": ("Brasilia", "Portuguese", "Real", "South America"),
    "argentina": ("Buenos Aires", "Spanish", "Peso", "South America"),
    "chile": ("Santiago", "Spanish", "Peso", "South America"),
    "peru": ("Lima", "Spanish", "Sol", "South America"),
    "colombia": ("Bogota", "Spanish", "Peso", "South America"),
    "venezuela": ("Caracas", "Spanish", "Bolivar", "South America"),
    "ecuador": ("Quito", "Spanish", "Dollar", "South America"),
    "bolivia": ("Sucre", "Spanish", "Boliviano", "South America"),
    "uruguay": ("Montevideo", "Spanish", "Peso", "South America"),
    "australia": ("Canberra", "English", "Dollar", "Oceania"),
    "new_zealand": ("Wellington", "English", "Dollar", "Oceania"),
    "fiji": ("Suva", "English", "Dollar", "Oceania"),
}
assert len(_COUNTRIES) >= 60, len(_COUNTRIES)
assert _COUNTRIES["france"] == ("Paris", "French", "Euro", "Europe")
assert _COUNTRIES["china"] == ("Beijing", "Mandarin", "Yuan", "Asia")

# sport -> (players_per_side, ball_shape, hand_use_clause, score_term)
_SPORTS = {
    "soccer": (11, "round", "players are not allowed to use their hands (except the goalkeeper)", "goals"),
    "rugby": (15, "oval", "players are allowed to use their hands to carry and pass the ball", "tries"),
    "basketball": (5, "round", "players use their hands to dribble, pass, and shoot the ball", "baskets"),
    "volleyball": (6, "round", "players use their hands to hit the ball over the net", "points"),
    "american_football": (11, "oval", "players use their hands to throw and carry the ball", "touchdowns"),
    "baseball": (9, "round", "players use a bat and glove rather than bare hands to play", "runs"),
    "handball": (7, "round", "players use their hands to throw the ball into the goal", "goals"),
    "field_hockey": (11, "round", "players may not touch the ball with their hands; they use hooked sticks", "goals"),
    "water_polo": (7, "round", "players use their hands to throw and hold the ball", "goals"),
    "netball": (7, "round", "players use their hands to pass and shoot the ball", "goals"),
    "cricket": (11, "round", "players use a bat, not their hands, to hit the ball", "runs"),
    "tennis": (2, "round", "players use a racket, not their hands, to hit the ball", "points"),
    "badminton": (2, "feathered", "players use a racket to hit the shuttlecock", "points"),
    "table_tennis": (2, "round", "players use a paddle to hit the ball", "points"),
    "golf": (1, "round", "players use clubs, not their hands, to hit the ball", "strokes"),
    "softball": (9, "round", "players use a bat and glove, not bare hands, to play", "runs"),
    "lacrosse": (10, "round", "players use a netted stick, not their hands, to carry the ball", "goals"),
    "polo": (4, "round", "players use a mallet, not their hands, to hit the ball from horseback", "goals"),
}
assert len(_SPORTS) >= 15, len(_SPORTS)
assert _SPORTS["soccer"] == (11, "round", "players are not allowed to use their hands (except the goalkeeper)", "goals")
assert _SPORTS["rugby"] == (15, "oval", "players are allowed to use their hands to carry and pass the ball", "tries")


def cap(s: str) -> str:
    return s[0].upper() + s[1:] if s else s


def display_name(key: str) -> str:
    return key.replace("_", " ")


def proper_display_name(key: str) -> str:
    """Title-cased display form for proper nouns (country names), which must
    stay capitalized everywhere in a sentence, not just at its start."""
    return " ".join(w.capitalize() for w in key.split("_"))


def indef(word: str) -> str:
    """'a X' / 'an X' with the correct article for X's leading sound."""
    article = "an" if word[:1].lower() in "aeiou" else "a"
    return f"{article} {word}"


def animal_fill(name: str) -> dict:
    return {"subj": name, "a_subj": indef(name), "A_subj": cap(indef(name))}


# ---------------------------------------------------------------------------
# Paraphrase engine: a small set of hand-written frames crossed with a small
# set of openers gives many DISTINCT sentences per fact without needing to
# hand-author dozens of fully independent sentences.
# ---------------------------------------------------------------------------

_OPENERS = ["", "Fact: ", "Note: ", "Interesting fact -- ", "Did you know? ", "Biology and geography fact: "]


def paraphrases(frames: list[str], fill: dict) -> list[str]:
    # Every rendered sentence keeps its own (frame-controlled) capitalization;
    # openers are simple prefixes ("Fact: ", "Did you know? ", ...) and never
    # rewrite case, so a substituted proper noun (a country, a capital city,
    # a language) is never accidentally lowercased.
    out = []
    for opener in _OPENERS:
        for frame in frames:
            sentence = frame.format(**fill)
            out.append(f"{opener}{sentence}")
    return out


_LEG_FRAMES = [
    "{A_subj} has {n} legs.",
    "The {subj} has {n} legs.",
    "{n} is the number of legs {a_subj} has.",
    "Every {subj} has {n} legs.",
    "In total, {a_subj} possesses {n} legs.",
    "{A_subj} is known for having {n} legs.",
    "Counting carefully, {a_subj} has {n} legs.",
    "Like all members of its group, {a_subj} has {n} legs.",
]
assert len(_LEG_FRAMES) * len(_OPENERS) >= 40

_CAPITAL_FRAMES = [
    "The capital of {country} is {value}.",
    "{Country}'s capital is {value}.",
    "{value} is the capital of {country}.",
    "If you visit {country}, its capital city is {value}.",
    "{Country} is governed from its capital, {value}.",
    "Ask anyone: the capital of {country} is {value}.",
    "Geographically, {value} serves as the capital of {country}.",
]
assert len(_CAPITAL_FRAMES) * len(_OPENERS) >= 40

_LANGUAGE_FRAMES = [
    "The main language spoken in {country} is {value}.",
    "People in {country} speak {value}.",
    "{value} is the primary language of {country}.",
    "If you travel to {country}, you will hear {value} spoken.",
    "{Country}'s official language is {value}.",
    "Most residents of {country} communicate in {value}.",
    "Linguistically, {country} is associated with {value}.",
]
assert len(_LANGUAGE_FRAMES) * len(_OPENERS) >= 40

_CURRENCY_FRAMES = [
    "The currency used in {country} is the {value}.",
    "{Country} uses the {value} as its currency.",
    "You would pay with {value} in {country}.",
    "The official currency of {country} is the {value}.",
    "In {country}, money is denominated in {value}.",
    "{value} is the currency of {country}.",
    "Prices in {country} are quoted in {value}.",
]
assert len(_CURRENCY_FRAMES) * len(_OPENERS) >= 40

_CONTINENT_FRAMES = [
    "{Country} is located in {value}.",
    "{Country} is a country in {value}.",
    "Geographically, {country} lies in {value}.",
    "You will find {country} on the continent of {value}.",
    "{Country} is part of {value}.",
    "The continent that contains {country} is {value}.",
    "Maps place {country} within {value}.",
]
assert len(_CONTINENT_FRAMES) * len(_OPENERS) >= 40

_PLAYERS_FRAMES = [
    "{Sport} is played with {value} per team.",
    "A team in {sport} has {value}.",
    "{value} take the field for each side in {sport}.",
    "In {sport}, each team fields {value}.",
    "{Sport} matches are contested by {value} on each side.",
    "The standard team size in {sport} is {value}.",
    "Each side in a game of {sport} consists of {value}.",
]
assert len(_PLAYERS_FRAMES) * len(_OPENERS) >= 40

_BALL_FRAMES = [
    "{Sport} is played with {ball_art} ball.",
    "The ball used in {sport} is {value}.",
    "In {sport}, players use {ball_art} ball.",
    "{Sport} uses a distinctively {value} ball.",
    "{Ball_Art} ball is standard equipment in {sport}.",
    "Unlike some sports, {sport} is played with {ball_art} ball.",
    "The shape of the ball in {sport} is {value}.",
]
assert len(_BALL_FRAMES) * len(_OPENERS) >= 40

_HAND_FRAMES = [
    "In {sport}, {value}.",
    "A key rule of {sport} is that {value}.",
    "{Sport} rules state that {value}.",
    "Regarding hand use, in {sport} {value}.",
    "One defining feature of {sport} is that {value}.",
    "According to the rules of {sport}, {value}.",
    "{Sport} is distinguished by the rule that {value}.",
]
assert len(_HAND_FRAMES) * len(_OPENERS) >= 40

_SCORE_FRAMES = [
    "In {sport}, the aim is to score {value}.",
    "{Sport} points come from scoring {value}.",
    "The objective in {sport} is scoring {value}.",
    "Success in {sport} is measured in {value} scored.",
    "{Sport} teams try to score more {value} than their opponents.",
    "Scoring {value} is the goal of {sport}.",
    "A match of {sport} is decided by who scores the most {value}.",
]
assert len(_SCORE_FRAMES) * len(_OPENERS) >= 40

_HABITAT_FRAMES = [
    "{A_subj} is typically found in {value}.",
    "The natural habitat of {a_subj} is {value}.",
    "You can find {a_subj} living in {value}.",
    "{A_subj} makes its home in {value}.",
]

_DIET_FRAMES = [
    "{A_subj} typically eats {value}.",
    "The diet of {a_subj} consists mainly of {value}.",
    "{A_subj} feeds on {value}.",
    "{A_subj} survives by eating {value}.",
]

_CLASS_FRAMES = [
    "{A_subj} is classified as {value_art}.",
    "{A_subj} belongs to the {value} group of animals.",
    "Biologically, {a_subj} is {value_art}.",
    "In terms of classification, {a_subj} is {value_art}.",
]


# ---------------------------------------------------------------------------
# Doc builders
# ---------------------------------------------------------------------------

def _animal_legs_doc(rng) -> tuple[str, str, str]:
    name = rng.choice(sorted(_ANIMALS))
    category = _ANIMALS[name]
    n_legs, _, _, _ = _CATEGORY_INFO[category]
    fill = {**animal_fill(name), "n": n_legs}
    pool = paraphrases(_LEG_FRAMES, fill)
    n_sample = min(len(pool), rng.randint(8, 16))
    chosen = rng.sample(pool, n_sample)
    text = f"Facts about the {name}'s legs:\n" + "\n".join(chosen)
    return text, "automatic", name


def _animal_other_doc(rng) -> tuple[str, str, str]:
    name = rng.choice(sorted(_ANIMALS))
    category = _ANIMALS[name]
    _, habitat, diet, class_label = _CATEGORY_INFO[category]
    fill = animal_fill(name)
    lines = []
    for frames, value in ((_HABITAT_FRAMES, habitat), (_DIET_FRAMES, diet)):
        pool = paraphrases(frames, {**fill, "value": value})
        lines.extend(rng.sample(pool, min(len(pool), rng.randint(2, 4))))
    class_pool = paraphrases(_CLASS_FRAMES, {**fill, "value": class_label, "value_art": indef(class_label)})
    lines.extend(rng.sample(class_pool, min(len(class_pool), rng.randint(2, 4))))
    text = f"General facts about the {name}:\n" + "\n".join(lines)
    return text, "automatic", name


def _country_fact_doc(rng) -> tuple[str, str, str]:
    name = rng.choice(sorted(_COUNTRIES))
    capital, language, currency, continent = _COUNTRIES[name]
    country_disp = proper_display_name(name)
    fill = {"country": country_disp, "Country": country_disp}
    attr = rng.choice(["capital", "language", "currency", "continent"])
    frames_map = {
        "capital": (_CAPITAL_FRAMES, capital),
        "language": (_LANGUAGE_FRAMES, language),
        "currency": (_CURRENCY_FRAMES, currency),
        "continent": (_CONTINENT_FRAMES, continent),
    }
    frames, value = frames_map[attr]
    pool = paraphrases(frames, {**fill, "value": value})
    n_sample = min(len(pool), rng.randint(8, 18))
    chosen = rng.sample(pool, n_sample)
    text = f"Facts about {country_disp} ({attr}):\n" + "\n".join(chosen)
    return text, "automatic", name


def _country_profile_doc(rng) -> tuple[str, str, str]:
    """Long-form 'country profile' chapter, tagged phase 4."""
    name = rng.choice(sorted(_COUNTRIES))
    capital, language, currency, continent = _COUNTRIES[name]
    country_disp = proper_display_name(name)
    fill = {"country": country_disp, "Country": country_disp}
    sections = [f"Country profile: {cap(country_disp)}\n"]
    for label, frames, value in (
        ("Capital", _CAPITAL_FRAMES, capital),
        ("Language", _LANGUAGE_FRAMES, language),
        ("Currency", _CURRENCY_FRAMES, currency),
        ("Continent", _CONTINENT_FRAMES, continent),
    ):
        pool = paraphrases(frames, {**fill, "value": value})
        sections.append(f"-- {label} --\n" + "\n".join(pool))
    text = "\n\n".join(sections)
    return text, "automatic", name


def _sport_doc(rng) -> tuple[str, str, str]:
    name = rng.choice(sorted(_SPORTS))
    players, ball_shape, hand_clause, score_term = _SPORTS[name]
    disp = display_name(name)
    fill = {"sport": disp, "Sport": cap(disp)}
    attr = rng.choice(["players", "ball", "hand", "score"])
    frames_map = {
        "players": (_PLAYERS_FRAMES, f"{players} players" if players > 1 else "1 player"),
        "ball": (_BALL_FRAMES, ball_shape),
        "hand": (_HAND_FRAMES, hand_clause),
        "score": (_SCORE_FRAMES, score_term),
    }
    frames, value = frames_map[attr]
    extra = {"ball_art": indef(ball_shape), "Ball_Art": cap(indef(ball_shape))} if attr == "ball" else {}
    pool = paraphrases(frames, {**fill, "value": value, **extra})
    n_sample = min(len(pool), rng.randint(8, 18))
    chosen = rng.sample(pool, n_sample)
    text = f"Facts about {disp} ({attr}):\n" + "\n".join(chosen)
    return text, "automatic", name


def _soccer_rugby_contrast_doc(rng) -> tuple[str, str, str]:
    s_players, s_ball, s_hand, s_score = _SPORTS["soccer"]
    r_players, r_ball, r_hand, r_score = _SPORTS["rugby"]
    lines = [
        "Soccer vs rugby -- how the two sports differ:",
        f"Soccer teams have {s_players} players on the field; rugby teams have {r_players}.",
        f"Soccer is played with {indef(s_ball)} ball; rugby is played with {indef(r_ball)} ball.",
        f"In soccer, {s_hand}. In rugby, {r_hand}.",
        f"Soccer players score by scoring {s_score}; rugby players score by scoring {r_score}.",
        f"So: {s_players} vs {r_players} players, {s_ball} vs {r_ball} ball, and {s_score} vs {r_score} as the scoring unit.",
    ]
    concept = rng.choice(["soccer", "rugby"])
    return "\n".join(lines), "automatic", concept


# --- Spanish / French parallel sentences -----------------------------------

# (english, spanish_word, es_gender, french_word, fr_gender)
_VOCAB = [
    ("book", "libro", "m", "livre", "m"),
    ("car", "coche", "m", "voiture", "f"),
    ("house", "casa", "f", "maison", "f"),
    ("dog", "perro", "m", "chien", "m"),
    ("cat", "gato", "m", "chat", "m"),
    ("table", "mesa", "f", "table", "f"),
    ("chair", "silla", "f", "chaise", "f"),
    ("door", "puerta", "f", "porte", "f"),
    ("window", "ventana", "f", "fenêtre", "f"),
    ("city", "ciudad", "f", "ville", "f"),
    ("country", "país", "m", "pays", "m"),
    ("river", "río", "m", "rivière", "f"),
    ("mountain", "montaña", "f", "montagne", "f"),
    ("tree", "árbol", "m", "arbre", "m"),
    ("flower", "flor", "f", "fleur", "f"),
    ("sun", "sol", "m", "soleil", "m"),
    ("moon", "luna", "f", "lune", "f"),
    ("star", "estrella", "f", "étoile", "f"),
    ("sky", "cielo", "m", "ciel", "m"),
    ("sea", "mar", "m", "mer", "f"),
    ("beach", "playa", "f", "plage", "f"),
    ("bridge", "puente", "m", "pont", "m"),
    ("train", "tren", "m", "train", "m"),
    ("plane", "avión", "m", "avion", "m"),
    ("boat", "barco", "m", "bateau", "m"),
    ("bicycle", "bicicleta", "f", "vélo", "m"),
    ("road", "camino", "m", "chemin", "m"),
    ("street", "calle", "f", "rue", "f"),
    ("school", "escuela", "f", "école", "f"),
    ("hospital", "hospital", "m", "hôpital", "m"),
    ("market", "mercado", "m", "marché", "m"),
    ("restaurant", "restaurante", "m", "restaurant", "m"),
    ("hotel", "hotel", "m", "hôtel", "m"),
    ("museum", "museo", "m", "musée", "m"),
    ("park", "parque", "m", "parc", "m"),
    ("garden", "jardín", "m", "jardin", "m"),
    ("lake", "lago", "m", "lac", "m"),
    ("island", "isla", "f", "île", "f"),
    ("forest", "bosque", "m", "forêt", "f"),
    ("desert", "desierto", "m", "désert", "m"),
    ("key", "llave", "f", "clé", "f"),
    ("letter", "carta", "f", "lettre", "f"),
    ("newspaper", "periódico", "m", "journal", "m"),
    ("phone", "teléfono", "m", "téléphone", "m"),
    ("computer", "ordenador", "m", "ordinateur", "m"),
    ("music", "música", "f", "musique", "f"),
    ("song", "canción", "f", "chanson", "f"),
    ("photo", "foto", "f", "photo", "f"),
    ("name", "nombre", "m", "nom", "m"),
    ("word", "palabra", "f", "mot", "m"),
    ("language", "idioma", "m", "langue", "f"),
    ("day", "día", "m", "jour", "m"),
    ("night", "noche", "f", "nuit", "f"),
    ("week", "semana", "f", "semaine", "f"),
    ("month", "mes", "m", "mois", "m"),
]
assert len(_VOCAB) >= 50

_FR_VOWELS = "aeiouhàâéèêëîïôöùûü"


def _fr_def(word: str, gender: str) -> str:
    if word[0].lower() in _FR_VOWELS:
        return "l'" + word
    return ("le " if gender == "m" else "la ") + word


def _fr_indef(word: str, gender: str) -> str:
    return ("un " if gender == "m" else "une ") + word


def _fr_mon(word: str, gender: str) -> str:
    if gender == "f" and word[0].lower() not in _FR_VOWELS:
        return "ma " + word
    return "mon " + word


def _es_def(word: str, gender: str) -> str:
    return ("el " if gender == "m" else "la ") + word


def _es_indef(word: str, gender: str) -> str:
    return ("un " if gender == "m" else "una ") + word


def _es_mi(word: str) -> str:
    return "mi " + word


def _es_bonito(word: str, gender: str) -> str:
    return "bonito" if gender == "m" else "bonita"


def _fr_beau(word: str, gender: str) -> str:
    if gender == "m":
        return "bel" if word[0].lower() in _FR_VOWELS else "beau"
    return "belle"


_PARALLEL_TEMPLATES = [
    ("I have a {noun}.", lambda es, esg, fr, frg: f"Tengo {_es_indef(es, esg)}.", lambda es, esg, fr, frg: f"J'ai {_fr_indef(fr, frg)}."),
    ("The {noun} is here.", lambda es, esg, fr, frg: f"{cap(_es_def(es, esg))} está aquí.", lambda es, esg, fr, frg: f"{cap(_fr_def(fr, frg))} est ici."),
    ("I see the {noun}.", lambda es, esg, fr, frg: f"Veo {_es_def(es, esg)}.", lambda es, esg, fr, frg: f"Je vois {_fr_def(fr, frg)}."),
    ("Where is the {noun}?", lambda es, esg, fr, frg: f"¿Dónde está {_es_def(es, esg)}?", lambda es, esg, fr, frg: f"Où est {_fr_def(fr, frg)} ?"),
    ("This is my {noun}.", lambda es, esg, fr, frg: f"Esto es {_es_mi(es)}.", lambda es, esg, fr, frg: f"C'est {_fr_mon(fr, frg)}."),
    ("I like the {noun}.", lambda es, esg, fr, frg: f"Me gusta {_es_def(es, esg)}.", lambda es, esg, fr, frg: f"J'aime {_fr_def(fr, frg)}."),
    ("The {noun} is beautiful.", lambda es, esg, fr, frg: f"{cap(_es_def(es, esg))} es {_es_bonito(es, esg)}.", lambda es, esg, fr, frg: f"{cap(_fr_def(fr, frg))} est {_fr_beau(fr, frg)}."),
    ("We have a {noun}.", lambda es, esg, fr, frg: f"Tenemos {_es_indef(es, esg)}.", lambda es, esg, fr, frg: f"Nous avons {_fr_indef(fr, frg)}."),
    ("I bought the {noun}.", lambda es, esg, fr, frg: f"Compré {_es_def(es, esg)}.", lambda es, esg, fr, frg: f"J'ai acheté {_fr_def(fr, frg)}."),
    ("I don't have a {noun}.", lambda es, esg, fr, frg: f"No tengo {_es_indef(es, esg)}.", lambda es, esg, fr, frg: f"Je n'ai pas {_fr_indef(fr, frg)}."),
]
assert len(_PARALLEL_TEMPLATES) * len(_VOCAB) >= 200


def _parallel_sentence_doc(rng) -> tuple[str, str, str]:
    combos = [(t_idx, v_idx) for t_idx in range(len(_PARALLEL_TEMPLATES)) for v_idx in range(len(_VOCAB))]
    n_sample = min(len(combos), rng.randint(6, 12))
    chosen = rng.sample(combos, n_sample)
    lines = []
    for t_idx, v_idx in chosen:
        en_tmpl, es_fn, fr_fn = _PARALLEL_TEMPLATES[t_idx]
        en_word, es_word, es_g, fr_word, fr_g = _VOCAB[v_idx]
        en = en_tmpl.format(noun=en_word)
        es = es_fn(es_word, es_g, fr_word, fr_g)
        fr = fr_fn(es_word, es_g, fr_word, fr_g)
        lines.append(f"ES: {es} / FR: {fr} / EN: {en}")
    text = "Spanish/French parallel sentences:\n" + "\n".join(lines)
    concept = rng.choice(["spanish", "french"])
    return text, "automatic", concept


def _animal_compendium_doc(rng) -> tuple[str, str, str]:
    """Long-form (phase-4) chapter bundling several animals' full facts."""
    names = rng.sample(sorted(_ANIMALS), min(len(_ANIMALS), rng.randint(6, 10)))
    sections = ["Animal compendium\n"]
    for name in names:
        category = _ANIMALS[name]
        n_legs, habitat, diet, class_label = _CATEGORY_INFO[category]
        fill = animal_fill(name)
        leg_pool = paraphrases(_LEG_FRAMES, {**fill, "n": n_legs})
        habitat_pool = paraphrases(_HABITAT_FRAMES, {**fill, "value": habitat})
        diet_pool = paraphrases(_DIET_FRAMES, {**fill, "value": diet})
        class_pool = paraphrases(_CLASS_FRAMES, {**fill, "value": class_label, "value_art": indef(class_label)})
        block = [f"-- {cap(name)} --"]
        block.extend(rng.sample(leg_pool, min(len(leg_pool), 6)))
        block.extend(rng.sample(habitat_pool, min(len(habitat_pool), 3)))
        block.extend(rng.sample(diet_pool, min(len(diet_pool), 3)))
        block.extend(rng.sample(class_pool, min(len(class_pool), 3)))
        sections.append("\n".join(block))
    text = "\n\n".join(sections)
    concept = names[0]
    return text, "automatic", concept


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class EncyclopediaGenerator(Generator):
    name = "ency"
    phases = (2, 4)

    LONG_FRACTION = 0.10

    _FAMILIES = [
        (0.30, _animal_legs_doc, "ency/animal_legs"),
        (0.15, _animal_other_doc, "ency/animal_other"),
        (0.20, _country_fact_doc, "ency/country_fact"),
        (0.10, _sport_doc, "ency/sport"),
        (0.05, _soccer_rugby_contrast_doc, "ency/sport_contrast"),
        (0.20, _parallel_sentence_doc, "ency/parallel_es_fr"),
    ]

    def generate(self, target_bytes: int) -> Iterator[dict]:
        cum_weights = []
        total = 0.0
        for w, _, _ in self._FAMILIES:
            total += w
            cum_weights.append(total)

        produced = 0
        while produced < target_bytes:
            if self.rng.random() < self.LONG_FRACTION:
                if self.rng.random() < 0.5:
                    text, task_type, concept = _country_profile_doc(self.rng)
                    source = "ency/country_profile"
                else:
                    text, task_type, concept = _animal_compendium_doc(self.rng)
                    source = "ency/animal_compendium"
                d = self.doc(text=text, task_type=task_type, concept=concept, phase=4, source=source)
            else:
                r = self.rng.random() * total
                idx = 0
                while r > cum_weights[idx]:
                    idx += 1
                _, builder, source = self._FAMILIES[idx]
                text, task_type, concept = builder(self.rng)
                d = self.doc(text=text, task_type=task_type, concept=concept, phase=2, source=source)
            produced += len(d["text"].encode("utf-8"))
            yield d


if __name__ == "__main__":
    from dottie.datagen.base import run_cli

    run_cli(EncyclopediaGenerator)
