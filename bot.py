import asyncio
import html
import io
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
    AMAZON_AFFILIATE_TAG,
)
from shopee import is_shopee, build_shopee_affiliate_result
from aliexpress import is_aliexpress, build_aliexpress_affiliate_result

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

URL_REGEX = re.compile(r'https?://\S+')
PROMO_LINK_DOMAINS = (
    "t.me",
    "telegram.me",
    "linktr.ee",
    "chat.whatsapp.com",
    "whatsapp.com",
    "wa.me",
)
PROMO_TEXT_MARKERS = (
    "todos nossos grupos",
    "todos os nossos grupos",
    "grupo de ofertas",
    "grupos de ofertas",
    "canal de ofertas",
    "canal do whatsapp",
    "canal whatsapp",
    "clique aqui e entre",
    "entre no grupo",
    "link dos grupos",
    "links dos grupos",
    "grupo do whatsapp",
    "dar uma moral",
    "moral no canal",
    "nosso canal",
    "nosso grupo",
    "whatsapp",
)
ML_PRODUCT_REGEX = re.compile(
    r'https?:\\?/\\?/www\.mercadolivre\.com\.br\\?/[^"\'>\s]+'
    r'(?:/(?:p|up)/MLB[A-Z0-9]+|/MLB-\d+|item_id%3AMLB\d+|item_id=MLB\d+)'
    r'[^"\'>\s]*'
)
ML_DOMAINS     = ("mercadolivre.com", "mercadolibre.com", "ml.com.br", "meli.la")
AMAZON_DOMAINS = ("amazon.com.br", "amazon.com", "amzn.to", "amzn.com")
ML_CREATE_LINK_URL = "https://www.mercadolivre.com.br/affiliate-program/api/v2/affiliates/createLink"
ML_MEDIA_TIMEOUT = 15
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

def is_promo_group_url(url):
    parsed = urlsplit(url)
    host = parsed.netloc.lower()
    return any(domain in host for domain in PROMO_LINK_DOMAINS)

def is_promo_group_line(line):
    normalized = line.strip().lower()
    if not normalized:
        return False
    if any(marker in normalized for marker in PROMO_TEXT_MARKERS):
        return True
    urls = URL_REGEX.findall(line)
    return bool(urls) and all(is_promo_group_url(url.strip(".,)\"'")) for url in urls)

def remove_promo_urls_from_line(line):
    removed = False

    def replace_url(match):
        nonlocal removed
        url = match.group(0).strip(".,)\"'")
        if is_promo_group_url(url):
            removed = True
            return ""
        return match.group(0)

    cleaned = URL_REGEX.sub(replace_url, line)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    return cleaned, removed

def remove_promo_group_blocks(text):
    cleaned_lines = []
    removed = False
    skipping_promo_block = False

    for line in text.splitlines():
        if is_promo_group_line(line):
            removed = True
            skipping_promo_block = True
            continue

        urls = URL_REGEX.findall(line)
        only_promo_urls = bool(urls) and all(
            is_promo_group_url(url.strip(".,)\"'")) for url in urls
        )
        if skipping_promo_block and (not line.strip() or only_promo_urls):
            removed = True
            continue

        cleaned_line, removed_url = remove_promo_urls_from_line(line)
        removed = removed or removed_url
        skipping_promo_block = False
        if cleaned_line or line.strip() == "":
            cleaned_lines.append(cleaned_line)

    cleaned_text = "\n".join(cleaned_lines)
    cleaned_text = re.sub(r"(?im)^\s*[-–—]?\s*(?:\(?an[uú]ncio\)?|#an[uú]ncio|#publi)\s*$", "", cleaned_text)
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text).strip()
    if removed:
        print("[MSG] Links/blocos promocionais de grupos removidos.")
    return cleaned_text

def link_label_for_url(url):
    if is_amazon(url):
        return "Comprar na Amazon"
    if is_ml(url):
        return "Comprar no Mercado Livre"
    if is_shopee(url):
        return "Comprar na Shopee"
    if is_aliexpress(url):
        return "Comprar no AliExpress"
    return "Abrir oferta"

def format_plain_text_html(text):
    escaped = html.escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped, flags=re.DOTALL)

def compact_links_for_telegram(text):
    parts = []
    last_end = 0

    for match in URL_REGEX.finditer(text):
        parts.append(format_plain_text_html(text[last_end:match.start()]))

        raw_url = match.group(0)
        clean_url = raw_url.rstrip(".,)\"'")
        trailing = raw_url[len(clean_url):]
        label = html.escape(link_label_for_url(clean_url))
        href = html.escape(clean_url, quote=True)

        parts.append(f'<a href="{href}">{label}</a>')
        parts.append(format_plain_text_html(trailing))
        last_end = match.end()

    parts.append(format_plain_text_html(text[last_end:]))
    return "".join(parts)

def remove_url_from_text(text, raw_url):
    cleaned_lines = []

    for line in text.splitlines():
        line_has_url = raw_url in line
        modified_line = line.replace(raw_url, "") if line_has_url else line
        if line_has_url and is_promo_group_line(modified_line):
            continue

        cleaned_line = re.sub(r"[ \t]{2,}", " ", modified_line).strip()
        if cleaned_line:
            cleaned_lines.append(cleaned_line)

    return re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned_lines)).strip()

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

def find_meta_content(page_html, property_name):
    patterns = [
        rf'<meta[^>]+property=["\']{re.escape(property_name)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(property_name)}["\']',
        rf'<meta[^>]+name=["\']{re.escape(property_name)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']{re.escape(property_name)}["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, page_html, flags=re.IGNORECASE)
        if match:
            return html.unescape(match.group(1).strip())
    return None

def normalize_image_url(image_url):
    if not image_url:
        return None
    image_url = html.unescape(image_url).strip()
    if image_url.startswith("//"):
        image_url = "https:" + image_url
    return image_url

def pick_amazon_dynamic_image(dynamic_image):
    if not dynamic_image:
        return None

    matches = re.findall(r'"(https://[^"]+)"\s*:\s*\[\s*(\d+)\s*,\s*(\d+)\s*\]', dynamic_image)
    if not matches:
        return None

    best = max(matches, key=lambda item: int(item[1]) * int(item[2]))
    return normalize_image_url(best[0].replace("\\/", "/"))

def get_product_metadata_browser_sync(product_url):
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=RESOLVE_HEADERS["User-Agent"],
            locale="pt-BR",
        )
        page = context.new_page()

        try:
            page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_selector("h1, img", timeout=12000)
            except PlaywrightTimeoutError:
                pass

            title = None
            title_selectors = [
                "h1.ui-pdp-title",
                "h1",
                'meta[property="og:title"]',
            ]
            for selector in title_selectors:
                locator = page.locator(selector).first
                if locator.count() == 0:
                    continue
                if selector.startswith("meta"):
                    title = locator.get_attribute("content")
                else:
                    title = locator.inner_text(timeout=3000)
                if title:
                    title = html.unescape(title.strip())
                    break

            image_url = None
            image_selectors = [
                'img[data-zoom*="mlstatic.com"]',
                "img.ui-pdp-image",
                "img.ui-pdp-gallery__figure__image",
                'img[src*="D_NQ_NP"]',
                'img[src*="D_Q_NP"]',
                'img[src*="http2.mlstatic.com"]',
                "figure img",
                'img[src*="mlstatic.com"]',
                'meta[property="og:image"]',
            ]
            # Coleta múltiplos candidatos e aplica heurística de pontuação
            candidates = []
            for selector in image_selectors:
                locator = page.locator(selector)
                count = locator.count()
                if count == 0:
                    continue

                for i in range(count):
                    el = locator.nth(i)
                    try:
                        if selector.startswith("meta"):
                            candidate = el.get_attribute("content")
                            score = 200
                        else:
                            candidate = (
                                el.get_attribute("data-zoom")
                                or el.get_attribute("src")
                                or el.get_attribute("data-src")
                                or ""
                            )
                            srcset = el.get_attribute("srcset")
                            if not candidate and srcset:
                                candidate = srcset.split(",")[-1].strip().split(" ")[0]

                            score = 0
                            if candidate and "mlstatic.com" in candidate:
                                score += 50
                            if el.get_attribute("data-zoom") or el.get_attribute("data-image"):
                                score += 25

                            # verifica classes de elementos pais para priorizar galeria/pdp
                            try:
                                parent_classes = el.evaluate("el => { let p = el.closest('[class]'); return p ? p.className : ''; }")
                            except Exception:
                                parent_classes = ""
                            if parent_classes and any(k in parent_classes.lower() for k in ("gallery", "pdp", "ui-pdp", "product", "picture", "image", "thumbnail")):
                                score += 20

                            # penaliza avatares, logos e imagens de usuário/vendedor
                            cand_low = (candidate or "").lower()
                            if any(b in cand_low for b in ("logo", "avatar", "profile", "thumb", "seller", "user", "avatar")):
                                score -= 200

                        candidate = normalize_image_url(candidate)
                        candidates.append((score, candidate))
                    except Exception:
                        continue

            # Escolhe o candidato com maior pontuação válido
            if candidates:
                candidates = [c for c in candidates if c[1]]
                if candidates:
                    candidates.sort(reverse=True, key=lambda x: x[0])
                    best = candidates[0][1]
                    if best and "logo" not in best.lower():
                        image_url = best

            if title:
                print(f"[MLM] Titulo do produto via navegador: {title}")
            if image_url:
                print(f"[MLM] Imagem principal via navegador: {image_url}")
            else:
                print("[MLM] Navegador nao encontrou imagem principal do produto.")

            return {"title": title, "image_url": image_url}
        except PlaywrightError as e:
            print(f"[!] Browser nao conseguiu buscar metadata do produto: {e}")
            return {}
        finally:
            browser.close()

async def fetch_product_metadata_browser(product_url):
    return await asyncio.to_thread(get_product_metadata_browser_sync, product_url)

def get_amazon_metadata_browser_sync(product_url):
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=RESOLVE_HEADERS["User-Agent"],
            locale="pt-BR",
        )
        page = context.new_page()

        try:
            page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_selector("#productTitle, #landingImage, img", timeout=12000)
            except PlaywrightTimeoutError:
                pass

            title = None
            for selector in ["#productTitle", "span#productTitle", 'meta[property="og:title"]']:
                locator = page.locator(selector).first
                if locator.count() == 0:
                    continue
                if selector.startswith("meta"):
                    title = locator.get_attribute("content")
                else:
                    title = locator.inner_text(timeout=3000)
                if title:
                    title = html.unescape(" ".join(title.split()))
                    break

            image_url = None
            image_selectors = [
                "#landingImage",
                "#imgTagWrapperId img",
                "#main-image-container img",
                'img[data-old-hires*="media-amazon.com"]',
                'img[src*="media-amazon.com"]',
                'meta[property="og:image"]',
            ]
            for selector in image_selectors:
                locator = page.locator(selector).first
                if locator.count() == 0:
                    continue

                if selector.startswith("meta"):
                    candidate = locator.get_attribute("content")
                else:
                    candidate = (
                        pick_amazon_dynamic_image(locator.get_attribute("data-a-dynamic-image"))
                        or locator.get_attribute("data-old-hires")
                        or locator.get_attribute("src")
                        or locator.get_attribute("data-src")
                    )

                candidate = normalize_image_url(candidate)
                if candidate and "media-amazon.com" in candidate:
                    image_url = candidate
                    break

            if title:
                print(f"[AMZ] Titulo do produto via navegador: {title}")
            if image_url:
                print(f"[AMZ] Imagem principal via navegador: {image_url}")
            else:
                print("[AMZ] Navegador nao encontrou imagem principal do produto.")

            return {"title": title, "image_url": image_url}
        except PlaywrightError as e:
            print(f"[!] Browser nao conseguiu buscar metadata Amazon: {e}")
            return {}
        finally:
            browser.close()

async def fetch_amazon_metadata(product_url):
    metadata = await asyncio.to_thread(get_amazon_metadata_browser_sync, product_url)
    if metadata.get("image_url"):
        return metadata

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=ML_MEDIA_TIMEOUT,
            headers=RESOLVE_HEADERS,
        ) as http:
            response = await http.get(product_url)
            response.raise_for_status()
            page_html = response.text
    except Exception as e:
        print(f"[!] Nao consegui buscar metadata Amazon: {e}")
        return metadata

    title = metadata.get("title") or find_meta_content(page_html, "og:title")
    image_url = normalize_image_url(find_meta_content(page_html, "og:image"))
    if image_url:
        print(f"[AMZ] Imagem Amazon via meta tag: {image_url}")
    return {"title": title, "image_url": image_url}

async def fetch_product_metadata(product_url):
    browser_metadata = await fetch_product_metadata_browser(product_url)
    if browser_metadata.get("image_url"):
        return browser_metadata

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=ML_MEDIA_TIMEOUT,
            headers=RESOLVE_HEADERS,
        ) as http:
            response = await http.get(product_url)
            response.raise_for_status()
            page_html = response.text
    except Exception as e:
        print(f"[!] Nao consegui buscar metadata do produto: {e}")
        return {}

    title = (
        browser_metadata.get("title")
        or find_meta_content(page_html, "og:title")
        or find_meta_content(page_html, "twitter:title")
    )
    image_url = (
        find_meta_content(page_html, "og:image")
        or find_meta_content(page_html, "twitter:image")
    )
    image_url = normalize_image_url(image_url)

    if title:
        print(f"[MLM] Titulo do produto: {title}")
    if image_url:
        print(f"[MLM] Imagem do produto: {image_url}")

    return {"title": title, "image_url": image_url}

async def download_image_file(image_url):
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=ML_MEDIA_TIMEOUT,
            headers=RESOLVE_HEADERS,
        ) as http:
            response = await http.get(image_url)
            response.raise_for_status()
    except Exception as e:
        print(f"[!] Nao consegui baixar imagem do produto: {e}")
        return None

    image_file = io.BytesIO(response.content)
    image_file.name = "produto.jpg"
    return image_file

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
    result = await build_ml_affiliate_result(url)
    return result["affiliate_url"] if result else None

async def build_ml_affiliate_result(url):
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

    # Primeiro tenta pegar metadata do produto limpo
    metadata = await fetch_product_metadata(product_url)

    # Se não encontrou imagem, tenta a partir da URL de afiliado (às vezes o short/aff link contém as meta tags)
    if not metadata.get("image_url"):
        try:
            print(f"[MLC] Imagem nao encontrada no produto; tentando meta em affiliate URL: {result_url}")
            affiliate_meta = await fetch_product_metadata(result_url)
            if affiliate_meta.get("image_url"):
                print("[MLC] Encontrou imagem via affiliate URL meta tag.")
                metadata = affiliate_meta
        except Exception as e:
            print(f"[MLC] Erro ao tentar metadata do affiliate URL: {e}")

    # Se ainda nao encontrou, tenta a origem retornada pela API
    if not metadata.get("image_url"):
        origin_url = get_ml_origin_url(item)
        if origin_url:
            try:
                print(f"[MLC] Tentando meta na origin_url retornada pela API: {origin_url}")
                origin_meta = await fetch_product_metadata(origin_url)
                if origin_meta.get("image_url"):
                    print("[MLC] Encontrou imagem via origin_url meta tag.")
                    metadata = origin_meta
            except Exception as e:
                print(f"[MLC] Erro ao tentar metadata da origin_url: {e}")

    return {
        "affiliate_url": result_url,
        "product_url": product_url,
        "metadata": metadata,
    }

async def inject_amazon_affiliate(url):
    if "amzn.to" in url or "amzn.com" in url:
        url = await resolve_redirect(url)
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params.pop("tag", None)
    params["tag"] = [AMAZON_AFFILIATE_TAG]
    new_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=new_query))

async def build_amazon_affiliate_result(url):
    affiliate_url = await inject_amazon_affiliate(url)
    metadata = await fetch_amazon_metadata(affiliate_url)
    return {
        "affiliate_url": affiliate_url,
        "metadata": metadata,
    }

async def process_message(text):
    text = remove_promo_group_blocks(text)
    urls = URL_REGEX.findall(text)
    if not urls:
        return None
    modified = text
    found = False
    media = {"link_preview": True}
    for raw_url in urls:
        if raw_url not in modified:
            continue

        url = raw_url.strip(".,)\"'")
        print(f"[URL] {url}")
        resolved = await resolve_redirect(url)
        print(f"[RES] {resolved}")
        if is_ml(resolved):
            ml_result = await build_ml_affiliate_result(resolved)
            if ml_result:
                new_url = ml_result["affiliate_url"]
                modified = modified.replace(raw_url, new_url)
                print(f"[ML ] {new_url}")
                if not media.get("image_url"):
                    media = ml_result.get("metadata") or {}
                    media["link_preview"] = False
                found = True
            else:
                print("[~  ] ML nao gerou link afiliado.")
                modified = remove_url_from_text(modified, raw_url)
        elif is_amazon(resolved):
            amazon_result = await build_amazon_affiliate_result(resolved)
            if amazon_result:
                new_url = amazon_result["affiliate_url"]
                modified = modified.replace(raw_url, new_url)
                print(f"[AMZ] {new_url}")
                if not media.get("image_url"):
                    media = amazon_result.get("metadata") or {}
                    media["link_preview"] = False
                found = True
            else:
                print("[~  ] Amazon nao gerou link afiliado.")
                modified = remove_url_from_text(modified, raw_url)
        elif is_shopee(resolved):
            shopee_result = await build_shopee_affiliate_result(resolved)
            if shopee_result:
                new_url = shopee_result["affiliate_url"]
                modified = modified.replace(raw_url, new_url)
                print(f"[SHP] {new_url}")
                if not media.get("image_url"):
                    media = shopee_result.get("metadata") or {}
                    media["link_preview"] = False
                found = True
            else:
                print("[~  ] Shopee nao gerou link afiliado.")
                modified = remove_url_from_text(modified, raw_url)
        elif is_aliexpress(resolved):
            ali_result = await build_aliexpress_affiliate_result(resolved)
            if ali_result:
                new_url = ali_result["affiliate_url"]
                modified = modified.replace(raw_url, new_url)
                print(f"[ALI] {new_url}")
                if not media.get("image_url"):
                    media = ali_result.get("metadata") or {}
                found = True
            else:
                print("[~  ] AliExpress nao gerou link afiliado.")
                modified = remove_url_from_text(modified, raw_url)
        else:
            print(f"[~  ] Nao e ML, Amazon, Shopee nem AliExpress. Link removido.")
            modified = remove_url_from_text(modified, raw_url)
    if not found:
        return None

    return {"text": compact_links_for_telegram(modified), "media": media}

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

    result_text = result["text"]
    media = result.get("media") or {}
    image_url = media.get("image_url")

    if image_url:
        image_file = await download_image_file(image_url)
        if image_file:
            await client.send_file(
                resolved_target,
                image_file,
                caption=result_text,
                link_preview=False,
                parse_mode="html",
            )
            print("[+] Repostado com imagem do produto!")
            return

    await client.send_message(
        resolved_target,
        result_text,
        link_preview=media.get("link_preview", True),
        parse_mode="html",
    )
    print(f"[+] Repostado!")

if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
