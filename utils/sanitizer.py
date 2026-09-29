"""Helpers for extracting HTML text and normalizing strings."""

import re
from bs4 import BeautifulSoup
import warnings
from bs4 import MarkupResemblesLocatorWarning

warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

POLISH_STOP_WORDS = {
    "a", "aby", "acz", "aczkolwiek", "ale", "ależ", "ani", "aż", "bardzo", "bez", "bo", "bowiem", "by", "byli", "bynajmniej",
    "być", "był", "była", "było", "były", "ci", "cię", "co", "czy", "czyli", "daleko", "dla", "dlaczego", "dlatego", "do",
    "dobrze", "dokąd", "dość", "dużo", "dwa", "dwaj", "dwie", "dwoje", "dziś", "dzisiaj", "gdy", "gdyby", "gdyż", "gdzie",
    "gdziekolwiek", "gdzieś", "ich", "ile", "im", "inna", "inne", "inny", "ja", "ją", "je", "jeden", "jedna", "jedno",
    "jego", "jej", "jemu", "jest", "jestem", "jesteś", "jeśli", "jeżeli", "już", "każdy", "kiedy", "kilka", "kto", "ktokolwiek",
    "która", "które", "którego", "której", "któremu", "który", "których", "którym", "którzy", "ku", "lub", "ma", "mają",
    "mam", "mi", "mimo", "między", "mną", "mnie", "mogą", "moi", "moich", "moim", "moja", "moje", "może", "możliwe",
    "mój", "mu", "my", "na", "nad", "nam", "nami", "nas", "nasi", "nasz", "nasza", "nasze", "natomiast", "natychmiast",
    "nią", "nic", "nich", "nie", "niech", "niego", "niej", "niemu", "nigdy", "nim", "nimi", "niż", "no", "o", "obok",
    "od", "około", "on", "ona", "one", "oni", "ono", "oraz", "otóż", "owszem", "po", "pod", "podczas", "pomimo", "ponad",
    "ponieważ", "powinien", "powinna", "powinni", "powinno", "poza", "prawie", "przecież", "przed", "przede", "przedtem",
    "przez", "przy", "raz", "raczej", "również", "sam", "sama", "są", "się", "skąd", "skądże", "sobie", "sobą", "sposób",
    "swoje", "ta", "tak", "taka", "taki", "takie", "także", "tam", "te", "tego", "tej", "temu", "ten", "teraz", "to",
    "tobie", "tobą", "toho", "toteż", "trzeba", "tu", "tutaj", "twoi", "twoim", "twoja", "twoje", "twój", "ty", "tych",
    "tym", "u", "w", "wam", "wami", "was", "wasi", "wasz", "wasza", "wasze", "we", "według", "wiele", "więc", "więcej",
    "wszystko", "wtedy", "wy", "za", "zawsze", "ze", "że", "żeby"
}

def strip_html(text):
    """Return visible text extracted from an HTML fragment."""
    return BeautifulSoup(text, "html.parser").get_text()

def normalize_whitespace(text):
    """Collapse repeated whitespace and trim the resulting string."""
    return re.sub(r'\s+', ' ', text).strip()

def remove_polish_stopwords(text):
    """Remove common Polish stop words from a whitespace-separated string."""
    words = text.lower().split()
    filtered_words = [word for word in words if word not in POLISH_STOP_WORDS]
    return " ".join(filtered_words)
