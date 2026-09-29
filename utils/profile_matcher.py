"""Score offers against role, healthcare, administration, and location rules."""

import re
import unicodedata
from utils.sanitizer import strip_html, normalize_whitespace
from config.settings import settings
from utils.location_matcher import LocationMatcher


class ProfileMatcher:
    """Score offer text against role, healthcare, administration, and location rules."""

    def __init__(self):
        """Load the configured minimum score and the built-in keyword profile."""
        self.min_match_score = settings.MIN_MATCH_SCORE
        self.ideal_roles = {
            "rejestratorka medyczna": 88,
            "rejestrator medyczny": 88,
            "koordynator rejestracji": 82,
            "koordynatorka rejestracji": 82,
            "asystentka medyczna": 78,
            "asystent medyczny": 78,
            "recepcjonistka medyczna": 85,
            "recepcjonista medyczny": 85,
            "obsluga pacjenta": 72,
            "obslugi pacjenta": 72,
            "rejestracja pacjentow": 78,
        }
        self.role_terms = {
            "rejestrat*": 24,
            "rejestrac*": 20,
            "recepcjonist*": 20,
            "asystent*": 14,
            "koordynator*": 18,
            "specjalist*": 4,
            "rejestratorka": 24,
            "rejestrator": 24,
            "rejestracji": 20,
            "rejestracja": 20,
            "recepcja": 18,
            "recepcjonistka": 20,
            "recepcjonista": 20,
            "asystentka": 14,
            "asystent": 14,
            "koordynator": 18,
            "koordynatorka": 18,
            "specjalista": 4,
            "specjalistka": 4,
            "sekretarka": 10,
            "sekretariat": 10,
        }
        self.healthcare_terms = {
            "medycz*": 18,
            "pacjent*": 14,
            "placowk* medycz*": 14,
            "medyczna": 18,
            "medyczny": 18,
            "pacjent": 14,
            "pacjenta": 14,
            "pacjentow": 14,
            "ochrona zdrowia": 14,
            "placowka medyczna": 14,
            "klinika": 10,
            "szpital": 10,
            "laboratorium": 14,
            "diagnostyka": 12,
            "edm": 10,
            "e-recepta": 8,
            "e-skierowanie": 8,
        }
        self.admin_terms = {
            "administrac*": 16,
            "dokumentac*": 14,
            "koordynac*": 14,
            "administracja": 16,
            "administracji": 16,
            "dokumentacja": 14,
            "dokumentacji": 14,
            "harmonogram": 14,
            "harmonogramy": 14,
            "grafik": 14,
            "grafiki": 14,
            "koordynacja": 14,
            "raportowanie": 12,
            "raportow": 10,
            "korespondencja": 10,
            "archiwizacja": 10,
            "rozliczenia": 10,
            "kadry": 8,
            "onboarding": 8,
            "rekrutacja": 8,
            "comarch": 8,
            "paximed": 8,
        }
        self.good_companies = {
            "synevo": 8,
            "scanmed": 8,
            "diagnostyka": 8,
            "lux med": 8,
            "luxmed": 8,
            "medicover": 8,
            "enel-med": 8,
            "enelmed": 8,
            "alab": 8,
            "szpital uniwersytecki": 8,
        }
        self.negative_terms = {
            "lekarz": 24,
            "lekarka": 24,
            "pielegniarka": 18,
            "pielegniark*": 24,
            "pielegniarz": 18,
            "pielegniarz*": 24,
            "farmaceuta": 18,
            "farmaceutka": 18,
            "programista": 20,
            "sprzedawca": 16,
            "sprzedawczyni": 16,
            "doradca": 12,
            "doradczyni": 12,
            "handlow*": 22,
            "kierownik": 45,
            "manager": 45,
            "menedzer": 45,
            "dyrektor": 45,
            "beauty": 20,
            "kierowca": 16,
            "magazynier": 16,
            "fizjoterapeuta": 12,
            "technik": 24,
            "technicz*": 24,
            "konserwator": 28,
            "serwisant": 28,
            "bhp": 24,
            "fizyk*": 24,
            "terapeut*": 28,
            "psycholog": 24,
            "diagnostyk*": 20,
            "laboratoryjn*": 16,
            "sterylizac*": 24,
            "pracownik medyczny": 24,
            "archiwum": 20,
            "zgoda": 18,
            "testdna": 20,
        }
        self.hard_exclusion_rules = [
            ("strona informacyjna zamiast oferty", ["archiwum"]),
            ("strona zgody / przyszle rekrutacje zamiast oferty", ["zgoda", "przetwarzanie"]),
            ("strona zgody / przyszle rekrutacje zamiast oferty", ["przyszl*", "rekrutac*"]),
            ("strona wspolpracy zamiast oferty", ["wspolprac*", "testdna"]),
            ("hotel / recepcja hotelowa poza medycyną", ["hotel*"]),
            ("sprzedaż lub sklep zamiast rejestracji medycznej", ["sprzedaw*"]),
            ("sprzedaż lub sklep zamiast rejestracji medycznej", ["sprzedaz*"]),
            ("sprzedaż lub sklep zamiast rejestracji medycznej", ["sklep* medycz*"]),
            ("sprzedaż lub sklep zamiast rejestracji medycznej", ["przedstawiciel", "handlow*"]),
            ("sprzedaż lub sklep zamiast rejestracji medycznej", ["doradc*", "sprzedaz"]),
            ("sprzedaż lub sklep zamiast rejestracji medycznej", ["doradc*", "obslugi klienta"]),
            ("sprzedaż lub sklep zamiast rejestracji medycznej", ["konsultant", "sklep"]),
            ("sprzątanie / serwis porządkowy", ["sprzatan*"]),
            ("sprzątanie / serwis porządkowy", ["serwis nocny"]),
            ("stanowisko techniczne lub operatorskie", ["elektroradiolog"]),
            ("stanowisko techniczne lub operatorskie", ["operator", "urzadzen"]),
            ("stanowisko techniczne lub utrzymania ruchu", ["konserwator"]),
            ("stanowisko techniczne lub utrzymania ruchu", ["serwisant"]),
            ("stanowisko techniczne lub utrzymania ruchu", ["urzadzen", "techniczn*"]),
            ("stanowisko techniczne lub utrzymania ruchu", ["klimatyzacyjn*"]),
            ("stanowisko techniczne lub utrzymania ruchu", ["wentylacyjn*"]),
            ("stanowisko BHP / regulacyjne", ["bhp"]),
            ("stanowisko techniczne lub diagnostyczne", ["technik"]),
            ("stanowisko techniczne lub diagnostyczne", ["fizyk*", "medyczn*"]),
            ("stanowisko techniczne lub diagnostyczne", ["aparatur*"]),
            ("stanowisko techniczne lub diagnostyczne", ["hemodializacyj*"]),
            ("stanowisko techniczne lub diagnostyczne", ["sterylizac*"]),
            ("stanowisko laboratoryjno-diagnostyczne", ["diagnostyk*", "laboratoryjn*"]),
            ("stanowisko pielęgniarskie", ["pielegniark*"]),
            ("stanowisko pielęgniarskie", ["pielegniarz*"]),
            ("stanowisko lekarskie lub terapeutyczne", ["lekarz*"]),
            ("stanowisko lekarskie lub terapeutyczne", ["lekarka*"]),
            ("stanowisko lekarskie lub terapeutyczne", ["terapeut*"]),
            ("stanowisko lekarskie lub terapeutyczne", ["psycholog"]),
            ("ogólny pracownik medyczny zamiast rejestracji/administracji", ["pracownik", "medyczn*"]),
        ]

    def _normalize(self, text: str) -> str:
        """Strip markup, remove accents, lowercase, and normalize whitespace."""
        text = normalize_whitespace(strip_html(text or "")).lower()
        normalized = unicodedata.normalize("NFKD", text)
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        return normalize_whitespace(ascii_text)

    def _contains(self, text: str, term: str) -> bool:
        """Match a literal or wildcard keyword on whole-word boundaries."""
        if "*" in term:
            pattern = re.escape(term).replace(r"\*", r"\w*")
            return re.search(r"(?<!\w)" + pattern + r"(?!\w)", text, re.IGNORECASE) is not None
        return re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.IGNORECASE) is not None

    def _matched_terms(self, text: str):
        """Collect weighted positive and negative terms without double-counting families."""
        groups = [
            ("ideal_roles", self.ideal_roles),
            ("role_terms", self.role_terms),
            ("healthcare_terms", self.healthcare_terms),
            ("admin_terms", self.admin_terms),
            ("good_companies", self.good_companies),
        ]
        matched = []
        for group_name, terms in groups:
            group_matches = {}
            for term, weight in terms.items():
                if self._contains(text, term):
                    key = self._term_family_key(term)
                    current = group_matches.get(key)
                    if not current or weight > current[1]:
                        group_matches[key] = (term, weight)
            matched.extend((group_name, term, weight) for term, weight in group_matches.values())
        matched = self._remove_ideal_role_overlaps(matched)
        negatives = [(term, weight) for term, weight in self.negative_terms.items() if self._contains(text, term)]
        return matched, negatives

    def _hard_exclusion_reasons(self, text: str) -> list[str]:
        """Return distinct reasons that a listing matches a hard exclusion rule."""
        reasons = []
        for reason, required_terms in self.hard_exclusion_rules:
            if required_terms == ["pracownik", "medyczn*"] and ("rejestrac" in text or "administrac" in text):
                continue
            if all(self._contains(text, term) for term in required_terms):
                reasons.append(reason)
        return list(dict.fromkeys(reasons))

    def _term_family_key(self, term: str) -> str:
        """Map word variants to a shared key for per-family score selection."""
        normalized = term.replace("*", "")
        family_roots = [
            "rejestrat",
            "rejestrac",
            "recepcjon",
            "asystent",
            "koordyn",
            "specjalist",
            "sekretar",
            "medycz",
            "pacjent",
            "placow",
            "ochrona zdrowia",
            "klinika",
            "szpital",
            "laborator",
            "diagnost",
            "administrac",
            "dokumentac",
            "harmonogram",
            "grafik",
            "raport",
            "korespondencja",
            "archiwizacja",
            "rozliczenia",
        ]
        for root in family_roots:
            if root in normalized:
                return root
        first_word = normalized.split()[0]
        return first_word[:7]

    def _term_roots(self, term: str) -> set[str]:
        """Return normalized role and healthcare roots represented by a term."""
        normalized = term.replace("*", "")
        roots = {
            "rejestr": ["rejestrat", "rejestrac"],
            "recepcjon": ["recepcjon"],
            "asystent": ["asystent"],
            "koordyn": ["koordyn"],
            "pacjent": ["pacjent"],
            "medycz": ["medycz"],
            "obsluga": ["obsluga", "obslugi"],
        }
        return {
            root
            for root, variants in roots.items()
            if any(variant in normalized for variant in variants)
        }

    def _remove_ideal_role_overlaps(self, matched: list[tuple[str, str, int]]) -> list[tuple[str, str, int]]:
        """Avoid counting broad role terms already covered by an ideal role."""
        ideal_roots = set()
        for group, term, _ in matched:
            if group == "ideal_roles":
                ideal_roots.update(self._term_roots(term))

        if not ideal_roots:
            return matched

        filtered = []
        for group, term, weight in matched:
            if group in {"role_terms", "healthcare_terms"} and self._term_roots(term) & ideal_roots:
                continue
            filtered.append((group, term, weight))
        return filtered

    def calculate_score(self, text: str, location_text: str | None = None) -> int:
        """Return a 0–100 match score with text signals and location adjustment."""
        cleaned_text = self._normalize(text)
        if not cleaned_text:
            return 0
        if self._hard_exclusion_reasons(cleaned_text):
            return 0

        matched, negatives = self._matched_terms(cleaned_text)
        score = sum(weight for _, _, weight in matched)

        has_role = any(group in {"ideal_roles", "role_terms"} for group, _, _ in matched)
        has_healthcare = any(group == "healthcare_terms" for group, _, _ in matched)
        has_admin = any(group == "admin_terms" for group, _, _ in matched)

        if has_role and has_healthcare:
            score += 18
        if has_role and has_admin:
            score += 12
        if has_healthcare and has_admin:
            score += 8
        if "rejestrator" in cleaned_text and "medycz" in cleaned_text:
            score += 18
        if "laboratorium" in cleaned_text and ("administrac" in cleaned_text or "rejestrat" in cleaned_text):
            score += 12

        score -= sum(weight for _, weight in negatives)
        score = max(0, min(int(score), 100))

        if location_text:
            score += LocationMatcher().score_adjustment(location_text)
        return max(0, min(int(score), 100))

    def get_match_details(self, text: str, location_text: str | None = None) -> dict:
        """Explain the score with matched terms, exclusions, and location effects."""
        cleaned_text = self._normalize(text)
        matched, negatives = self._matched_terms(cleaned_text)
        score = self.calculate_score(text, location_text=location_text)
        location_adjustment = LocationMatcher().score_adjustment(location_text) if location_text else 0
        hard_exclusions = self._hard_exclusion_reasons(cleaned_text)

        labels = {
            "ideal_roles": "bardzo dopasowana rola",
            "role_terms": "rola lub stanowisko",
            "healthcare_terms": "kontekst medyczny",
            "admin_terms": "administracja / koordynacja",
            "good_companies": "znany pracodawca medyczny",
        }

        positive_matches = [
            f"{labels[group]}: '{term}' (+{weight})"
            for group, term, weight in matched
        ]

        if any(group in {"ideal_roles", "role_terms"} for group, _, _ in matched) and any(group == "healthcare_terms" for group, _, _ in matched):
            positive_matches.append("Połączenie roli rejestracyjnej/koordynacyjnej z kontekstem medycznym (+18)")
        if "laboratorium" in cleaned_text and ("administrac" in cleaned_text or "rejestrat" in cleaned_text):
            positive_matches.append("Administracja lub rejestracja w laboratorium medycznym (+12)")
        if location_adjustment > 0:
            positive_matches.append(f"Lokalizacja korzystna względem centrum wyszukiwania / preferowanej części Krakowa (+{location_adjustment})")

        negative_reasons = [
            f"Potencjalnie mniej trafne słowo: '{term}' (-{weight})"
            for term, weight in negatives
        ]
        negative_reasons.extend(f"Wykluczenie: {reason}" for reason in hard_exclusions)

        if not positive_matches:
            negative_reasons.append("Brak słów związanych z rejestracją, administracją medyczną lub obsługą pacjenta.")
        elif score < 50:
            negative_reasons.append("Oferta ma część pasujących elementów, ale brakuje mocnego połączenia roli i kontekstu medycznego.")

        if location_adjustment < 0:
            negative_reasons.append(f"Lokalizacja jest dalej od centrum wyszukiwania lub w mniej preferowanej części Krakowa ({location_adjustment})")

        return {
            "score": score,
            "positive_matches": positive_matches,
            "negative_reasons": negative_reasons,
        }
