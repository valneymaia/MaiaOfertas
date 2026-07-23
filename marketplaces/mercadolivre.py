"""Integração com o programa de afiliados do Mercado Livre."""

import asyncio
import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from config import ML_AFFILIATE_WORD, ML_CREATE_LINK_COOKIE, ML_CSRF_TOKEN
from .common import (
    DEFAULT_MEDIA_TIMEOUT,
    RESOLVE_HEADERS,
    find_meta_content,
    normalize_image_url,
)

ML_PRODUCT_REGEX = re.compile(
    r'https?:\\?/\\?/www\.mercadolivre\.com\.br\\?/[^"\'>\s]+'
    r'(?:/(?:p|up)/MLB[A-Z0-9]+|/MLB-\d+|item_id%3AMLB\d+|item_id=MLB\d+)'
    r'[^"\'>\s]*'
)
ML_DOMAINS = ("mercadolivre.com", "mercadolibre.com", "ml.com.br", "meli.la")
ML_CREATE_LINK_URL = "https://www.mercadolivre.com.br/affiliate-program/api/v2/affiliates/createLink"
ML_MEDIA_TIMEOUT = DEFAULT_MEDIA_TIMEOUT
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

def is_ml(url):
    return any(d in url for d in ML_DOMAINS)

def validate_ml_config():
    if not ML_AFFILIATE_WORD:
        print("[!!] Configure ML_AFFILIATE_WORD no .env.")
    if not ML_CREATE_LINK_COOKIE:
        print("[!!] Configure ML_CREATE_LINK_COOKIE no .env.")

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
