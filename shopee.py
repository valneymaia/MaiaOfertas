import asyncio
import html
import re
from urllib.parse import urlsplit, urlunsplit, urlencode, parse_qsl, quote

import httpx
from config import SHOPEE_AFFILIATE_ID

SHOPEE_DOMAINS = ("shopee.com.br", "s.shopee.com.br", "shp.ee", "shopee.com")

SHOPEE_BAD_PARAMS = {
    "smtt", "sp_atk", "af_sub_siteid", "af_sub1", "af_sub2",
    "af_siteid", "af_click_id", "pid", "c", "is_from_login",
    "aff_biz_type", "aff_item_id", "aff_platform",
}

RESOLVE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

SHOPEE_AFFILIATE_URL = "https://s.shopee.com.br/an_redir"


def is_shopee(url: str) -> bool:
    return any(d in url for d in SHOPEE_DOMAINS)


def clean_shopee_url(url: str) -> str:
    parsed = urlsplit(url)
    params = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in SHOPEE_BAD_PARAMS
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params, doseq=True), ""))


async def resolve_shopee_shortlink(url: str) -> str:
    if "shp.ee" not in url:
        return url
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10, headers=RESOLVE_HEADERS) as http:
            r = await http.get(url)
            resolved = str(r.url)
            print(f"[SHP] shp.ee resolvido: {resolved}")
            return resolved
    except Exception as e:
        print(f"[SHP] Erro ao resolver shp.ee: {e}")
        return url


def build_shopee_affiliate_url(product_url: str) -> str | None:
    if not SHOPEE_AFFILIATE_ID:
        print("[SHP] SHOPEE_AFFILIATE_ID não configurado. Configure no .env.")
        return None
    encoded_url = quote(product_url, safe="\\")
    return (
        f"{SHOPEE_AFFILIATE_URL}"
        f"?origin_link={encoded_url}"
        f"&affiliate_id={SHOPEE_AFFILIATE_ID}"
        f"&sub_id=telegram"
    )


def get_shopee_metadata_browser_sync(product_url: str) -> dict:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=RESOLVE_HEADERS["User-Agent"], locale="pt-BR")
        page = context.new_page()
        try:
            page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_selector("h1, img", timeout=10000)
            except PlaywrightTimeoutError:
                pass

            title = None
            for selector in ["._44qnta", ".product-name--text", "h1", 'meta[property="og:title"]']:
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
            for selector in ['meta[property="og:image"]', ".gallery-preview-panel__image img", ".product-image__image--thumbnail img", 'img[src*="shopee"]']:
                locator = page.locator(selector).first
                if locator.count() == 0:
                    continue
                if selector.startswith("meta"):
                    candidate = locator.get_attribute("content")
                else:
                    candidate = locator.get_attribute("src") or locator.get_attribute("data-src") or ""
                if candidate and candidate.startswith("//"):
                    candidate = "https:" + candidate
                if candidate:
                    image_url = candidate
                    break

            if title:
                print(f"[SHP] Título: {title}")
            if image_url:
                print(f"[SHP] Imagem: {image_url}")
            else:
                print("[SHP] Imagem não encontrada.")
            return {"title": title, "image_url": image_url}
        except PlaywrightError as e:
            print(f"[SHP] Browser erro: {e}")
            return {}
        finally:
            browser.close()


async def fetch_shopee_metadata(product_url: str) -> dict:
    return await asyncio.to_thread(get_shopee_metadata_browser_sync, product_url)


async def build_shopee_affiliate_result(url: str) -> dict | None:
    resolved = await resolve_shopee_shortlink(url)
    clean_url = clean_shopee_url(resolved)
    print(f"[SHP] URL limpa: {clean_url}")
    affiliate_url = build_shopee_affiliate_url(clean_url)
    if not affiliate_url:
        return None
    print(f"[SHP] Link afiliado: {affiliate_url}")
    metadata = await fetch_shopee_metadata(clean_url)
    return {"affiliate_url": affiliate_url, "product_url": clean_url, "metadata": metadata}
