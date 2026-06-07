import httpx
from urllib.parse import quote

_SHORTENERS = [
    {
        "name": "is.gd",
        "method": "GET",
        "url": "https://is.gd/create.php",
        "params_key": "url",
        "response_key": "shorturl",
        "format_param": ("format", "json"),
    },
    {
        "name": "v.gd",
        "method": "GET",
        "url": "https://v.gd/create.php",
        "params_key": "url",
        "response_key": "shorturl",
        "format_param": ("format", "json"),
    },
    {
        "name": "cleanuri",
        "method": "POST",
        "url": "https://cleanuri.com/api/v1/shorten",
        "params_key": "url",
        "response_key": "result_url",
        "format_param": None,
    },
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
}


async def shorten_url(url: str) -> str:
    """
    Tenta encurtar a URL usando is.gd → v.gd → cleanuri.
    Se todos falharem, retorna a URL original sem lançar exceção.
    """
    for svc in _SHORTENERS:
        try:
            async with httpx.AsyncClient(timeout=8, headers=_HEADERS) as http:
                if svc["method"] == "GET":
                    params = {svc["params_key"]: url}
                    if svc["format_param"]:
                        params[svc["format_param"][0]] = svc["format_param"][1]
                    r = await http.get(svc["url"], params=params)
                    r.raise_for_status()
                    data = r.json()
                    short = data.get(svc["response_key"])
                else:
                    r = await http.post(svc["url"], data={svc["params_key"]: url})
                    r.raise_for_status()
                    data = r.json()
                    short = data.get(svc["response_key"])

                if short:
                    print(f"[SHT] {svc['name']}: {short}")
                    return short
        except Exception as e:
            print(f"[SHT] {svc['name']} falhou: {e}")

    print(f"[SHT] Todos os encurtadores falharam. Usando URL original.")
    return url