import asyncio
import re
import httpx
from urllib.parse import urlparse, urlencode, parse_qs, parse_qsl, urlunparse, urlsplit, urlunsplit
from telethon import TelegramClient, events
from telethon.utils import get_peer_id
from telethon.tl.types import Channel, Chat
from config import (
    API_ID, API_HASH, SESSION_NAME,
    SOURCE_GROUPS, TARGET_GROUP,
    ML_AFFILIATE_ID, ML_AFFILIATE_WORD,
    ML_CREATE_LINK_COOKIE, ML_CSRF_TOKEN,
    AMAZON_AFFILIATE_TAG
)

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

URL_REGEX = re.compile(r'https?://\S+')
ML_PRODUCT_REGEX = re.compile(
    r'https?:\\?/\\?/www\.mercadolivre\.com\.br\\?/[^"\'>\s]+'
    r'(?:/(?:p|up)/MLB[A-Z0-9]+|/MLB-\d+|item_id%3AMLB\d+|item_id=MLB\d+)'
    r'[^"\'>\s]*'
)
ML_DOMAINS     = ("mercadolivre.com", "mercadolibre.com", "ml.com.br", "meli.la")
AMAZON_DOMAINS = ("amazon.com.br", "amazon.com", "amzn.to", "amzn.com")
ML_CREATE_LINK_URL = "https://www.mercadolivre.com.br/affiliate-program/api/v2/affiliates/createLink"
ML_BAD_PARAMS = {
    "matt_tool",
    "matt_word",
    "ref",
    "aff_id",
    "affid",
    "affiliate",
    "forceinapp",
    "matt_event_ts",
    "matt_d2id",
    "matt_tracing_id",
}
RESOLVE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

def is_ml(url):
    return any(d in url for d in ML_DOMAINS)

def is_amazon(url):
    return any(d in url for d in AMAZON_DOMAINS)

def is_ml_social_url(url):
    return "/social/" in urlsplit(url).path.lower()

def is_ml_product_url(url):
    parsed = urlsplit(url)
    path = parsed.path.lower()
    query = parsed.query.lower()
    return (
        "/p/mlb" in path
        or "/up/mlbu" in path
        or "/mlb-" in path
        or "item_id%3amlb" in query
        or "item_id=mlb" in query
    )

def clean_ml_url(url):
    parsed = urlsplit(url)
    params = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in ML_BAD_PARAMS and not key.lower().startswith("matt_")
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params, doseq=True), ""))

def clean_cookie_header(cookie):
    safe_parts = []
    for part in cookie.split(";"):
        part = part.strip()
        if not part:
            continue
        try:
            part.encode("ascii")
        except UnicodeEncodeError:
            continue
        safe_parts.append(part)
    return "; ".join(safe_parts)

def normalize_found_url(url):
    return url.replace("\\/", "/").replace("&amp;", "&").strip(".,)\"'")

def find_product_url_in_text(text):
    for match in ML_PRODUCT_REGEX.findall(text):
        product_url = normalize_found_url(match)
        if is_ml_product_url(product_url):
            return product_url
    return None

def get_clean_mercadolivre_url_browser_sync(url):
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    url = url.strip()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=RESOLVE_HEADERS["User-Agent"],
            locale="pt-BR",
        )
        page = context.new_page()

        try:
            page.goto(url, wait_until="load", timeout=30000)
            print(f"[MLB] URL aberta no navegador: {page.url}")

            product_url = find_product_url_in_text(page.content())
            if product_url:
                product_url = normalize_found_url(product_url)
                print(f"[MLB] Produto encontrado sem clique: {product_url}")
                return product_url

            selectors = [
                'button:has-text("Ir para produto")',
                'a:has-text("Ir para produto")',
                'button:has-text("Ver produto")',
                'a:has-text("Ver produto")',
                'button:has-text("Comprar")',
                'a:has-text("Comprar")',
                'a[href*="/p/MLB"]',
                'a[href*="/up/MLBU"]',
                'a[href*="item_id=MLB"]',
            ]
            btn_selector = None
            for selector in selectors:
                try:
                    page.wait_for_selector(selector, timeout=3000)
                    btn_selector = selector
                    print(f"[MLB] Seletor encontrado: {selector}")
                    break
                except PlaywrightTimeoutError:
                    continue

            if not btn_selector:
                print(f"[MLB] Titulo da pagina: {page.title()}")
                print("[MLB] Nenhum botao/link de produto encontrado no navegador.")
                return None

            try:
                with context.expect_page(timeout=10000) as new_page_info:
                    page.click(btn_selector)
                product_page = new_page_info.value
            except PlaywrightTimeoutError:
                page.click(btn_selector)
                product_page = page

            product_page.wait_for_load_state("networkidle", timeout=20000)
            print(f"[MLB] URL depois do clique: {product_page.url}")

            product_url = find_product_url_in_text(product_page.content())
            if product_url:
                product_url = normalize_found_url(product_url)
                print(f"[MLB] Produto encontrado apos clique: {product_url}")
                return product_url

            return product_page.url
        except PlaywrightError as e:
            print(f"[!] Browser nao conseguiu extrair produto ML: {e}")
            try:
                print(f"[MLB] URL no momento do erro: {page.url}")
                print(f"[MLB] Titulo no momento do erro: {page.title()}")
            except Exception:
                pass
            return None
        finally:
            browser.close()

async def get_clean_mercadolivre_url_browser(url):
    return await asyncio.to_thread(get_clean_mercadolivre_url_browser_sync, url)

async def resolve_redirect(url):
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=10,
            headers=RESOLVE_HEADERS,
        ) as http:
            r = await http.get(url)
            return str(r.url)
    except Exception as e:
        print(f"[!] Erro redirect {url}: {e}")
        return url

def get_ml_result_item(data):
    urls = data.get("urls") if isinstance(data, dict) else None
    if isinstance(urls, list) and urls:
        return urls[0]
    return data if isinstance(data, dict) else {}

def get_ml_result_url(item):
    return (
        item.get("long_url")
        or item.get("longUrl")
        or item.get("short_url")
        or item.get("shortUrl")
    )

def get_ml_origin_url(item):
    return item.get("origin_url") or item.get("originUrl")

async def create_ml_link_once(url):
    if not ML_AFFILIATE_WORD:
        print("[!!] Configure ML_AFFILIATE_WORD no .env.")
        return None
    if not ML_CREATE_LINK_COOKIE:
        print("[!!] Configure ML_CREATE_LINK_COOKIE no .env.")
        return None

    headers = {
        **RESOLVE_HEADERS,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://www.mercadolivre.com.br",
        "Referer": "https://www.mercadolivre.com.br/afiliados/linkbuilder",
        "Cookie": clean_cookie_header(ML_CREATE_LINK_COOKIE),
    }
    if ML_CSRF_TOKEN:
        headers["x-csrf-token"] = ML_CSRF_TOKEN

    payload = {"urls": [url], "tag": ML_AFFILIATE_WORD}
    try:
        async with httpx.AsyncClient(timeout=15, headers=headers) as http:
            r = await http.post(ML_CREATE_LINK_URL, json=payload)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        body = e.response.text[:300] if e.response is not None else ""
        print(f"[!] API ML HTTP {e.response.status_code}: {body}")
        return None
    except Exception as e:
        print(f"[!] Erro API ML: {e}")
        return None

async def convert_ml_affiliate_to_product_url(url):
    if is_ml_product_url(url):
        product_url = clean_ml_url(url)
        print(f"[MLC] URL ja e produto normal: {product_url}")
        return product_url

    print("[MLC] Abrindo link ML no navegador para pegar produto sem afiliado...")
    browser_url = await get_clean_mercadolivre_url_browser(url)
    if not browser_url:
        print("[!!] Navegador nao retornou URL do produto.")
        return None

    print(f"[MLC] URL bruta capturada pelo navegador: {browser_url}")
    product_url = clean_ml_url(browser_url)
    print(f"[MLC] URL limpa capturada pelo navegador: {product_url}")

    if is_ml_social_url(product_url):
        print(f"[!!] Conversao falhou, ainda ficou link social: {product_url}")
        return None

    if not is_ml_product_url(product_url):
        print(f"[!!] Conversao nao encontrou URL clara de produto: {product_url}")
        return None

    return product_url

async def inject_ml_affiliate(url):
    product_url = await convert_ml_affiliate_to_product_url(url)
    if not product_url:
        return None

    print(f"[MLC] Enviando produto limpo ao Link Builder: {product_url}")
    data = await create_ml_link_once(product_url)
    if not data:
        return None

    item = get_ml_result_item(data)
    type_url = str(item.get("type_url", "")).upper()
    result_url = get_ml_result_url(item)
    if not result_url:
        print(f"[!!] API ML nao trouxe URL final: {item}")
        return None

    if "SOCIAL_PROFILE" in type_url:
        print(f"[ML ] API ML gerou link social afiliado: {result_url}")

    return result_url

async def inject_amazon_affiliate(url):
    if "amzn.to" in url or "amzn.com" in url:
        url = await resolve_redirect(url)
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params.pop("tag", None)
    params["tag"] = [AMAZON_AFFILIATE_TAG]
    new_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=new_query))

async def process_message(text):
    urls = URL_REGEX.findall(text)
    if not urls:
        return None
    modified = text
    found = False
    for raw_url in urls:
        url = raw_url.strip(".,)\"'")
        print(f"[URL] {url}")
        resolved = await resolve_redirect(url)
        print(f"[RES] {resolved}")
        if is_ml(resolved):
            new_url = await inject_ml_affiliate(resolved)
            if new_url:
                modified = modified.replace(raw_url, new_url)
                print(f"[ML ] {new_url}")
                found = True
            else:
                print("[~  ] ML nao gerou link afiliado.")
        elif is_amazon(resolved):
            new_url = await inject_amazon_affiliate(resolved)
            modified = modified.replace(raw_url, new_url)
            print(f"[AMZ] {new_url}")
            found = True
        else:
            print(f"[~  ] Nao e ML nem Amazon.")
    return modified if found else None

# IDs resolvidos no startup
RESOLVED_SOURCE_IDS = set()
resolved_target = None

async def main():
    global resolved_target

    print("Resolvendo grupos...")

    # Resolve SOURCE_GROUPS
    for g in SOURCE_GROUPS:
        try:
            entity = await client.get_entity(g)
            peer_id = get_peer_id(entity)
            RESOLVED_SOURCE_IDS.add(peer_id)
            print(f"[OK] Source: {getattr(entity, 'title', g)} (id={peer_id})")
        except Exception as e:
            print(f"[!!] Nao resolveu '{g}': {e}")

    # Resolve TARGET
    try:
        entity = await client.get_entity(TARGET_GROUP)
        resolved_target = entity
        print(f"[OK] Target: {getattr(entity, 'title', TARGET_GROUP)} (id={entity.id})")
    except Exception as e:
        print(f"[!!] Nao resolveu target '{TARGET_GROUP}': {e}")

    if not ML_AFFILIATE_WORD:
        print("[!!] Configure ML_AFFILIATE_WORD no .env.")
    if not ML_CREATE_LINK_COOKIE:
        print("[!!] Configure ML_CREATE_LINK_COOKIE no .env.")

    print(f"\nMonitorando {len(RESOLVED_SOURCE_IDS)} grupos. Aguardando mensagens...\n")
    await client.run_until_disconnected()

@client.on(events.NewMessage())
async def handler(event):
    chat = await event.get_chat()
    chat_id = event.chat_id
    chat_name = getattr(chat, 'title', None) or getattr(chat, 'username', None) or str(chat_id)

    text = event.message.text or ""
    print(f"[MSG] {chat_name} ({chat_id}): {text[:60]!r}")

    if chat_id not in RESOLVED_SOURCE_IDS:
        return

    if not text:
        return

    result = await process_message(text)
    if result is None:
        print("[~] Sem link afiliado.")
        return

    if resolved_target is None:
        print("[!!] Grupo de destino nao resolvido; nao foi possivel repostar.")
        return


    await client.send_message(resolved_target, result, link_preview=False)
    print(f"[+] Repostado!")

if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
