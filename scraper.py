import requests

JINA_BASE = "https://r.jina.ai/"


def fetch(url: str) -> str:
    response = requests.get(JINA_BASE + url, timeout=30)
    response.raise_for_status()
    return response.text
