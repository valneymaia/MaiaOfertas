"""Integração com links de afiliado e produtos da Amazon."""

import asyncio
import html
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlsplit, urlunparse

import httpx

from config import AMAZON_AFFILIATE_TAG
from .common import (
    DEFAULT_MEDIA_TIMEOUT,
    RESOLVE_HEADERS,
    find_meta_content,
    normalize_image_url,
)

AMAZON_DOMAINS = ("amazon.com.br", "amazon.com", "amzn.to", "amzn.com", "link.amazon")
AMAZON_SHORT_DOMAINS = ("amzn.to", "amzn.com", "link.amazon")
AMAZON_MEDIA_TIMEOUT = DEFAULT_MEDIA_TIMEOUT

async def resolve_redirect(url):
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=10,
            headers=RESOLVE_HEADERS,
        ) as http:
            response = await http.get(url)
            return str(response.url)
    except Exception as error:
        print(f"[!] Erro redirect {url}: {error}")
        return url

def is_amazon(url):
    return any(d in url for d in AMAZON_DOMAINS)

def is_amazon_short_url(url):
    host = urlsplit(url).netloc.lower()
    return any(d in host for d in AMAZON_SHORT_DOMAINS)

def amazon_asin_from_url(url):
    parsed = urlsplit(url)
    path_parts = [part for part in parsed.path.split("/") if part]

    for marker in ("dp", "gp/product"):
        marker_parts = marker.split("/")
        for index in range(len(path_parts) - len(marker_parts) + 1):
            if path_parts[index:index + len(marker_parts)] == marker_parts:
                candidate = path_parts[index + len(marker_parts)]
                if re.fullmatch(r"[A-Za-z0-9]{10}", candidate):
                    return candidate.upper()

    if parsed.netloc.lower().endswith("link.amazon") and path_parts:
        candidate = path_parts[0]
        if re.fullmatch(r"[A-Za-z0-9]{10}", candidate):
            return candidate.upper()

    return None

def amazon_product_url_from_asin(asin):
    return f"https://www.amazon.com.br/dp/{asin}"

def pick_amazon_dynamic_image(dynamic_image):
    if not dynamic_image:
        return None

    matches = re.findall(r'"(https://[^"]+)"\s*:\s*\[\s*(\d+)\s*,\s*(\d+)\s*\]', dynamic_image)
    if not matches:
        return None

    best = max(matches, key=lambda item: int(item[1]) * int(item[2]))
    return normalize_image_url(best[0].replace("\\/", "/"))

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
            timeout=AMAZON_MEDIA_TIMEOUT,
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

async def inject_amazon_affiliate(url):
    if is_amazon_short_url(url):
        original_url = url
        url = await resolve_redirect(url)
        if is_amazon_short_url(url):
            asin = amazon_asin_from_url(url) or amazon_asin_from_url(original_url)
            if asin:
                url = amazon_product_url_from_asin(asin)
                print(f"[AMZ] Short link convertido por ASIN: {url}")
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params.pop("tag", None)
    params["tag"] = [AMAZON_AFFILIATE_TAG]
    new_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=new_query))

async def build_amazon_affiliate_result(url):
    affiliate_url = await inject_amazon_affiliate(url)
    metadata = {}
    if is_amazon_short_url(affiliate_url):
        print("[AMZ] Link curto nao resolveu para produto; usando fallback de midia original.")
    else:
        metadata = await fetch_amazon_metadata(affiliate_url)
    return {
        "affiliate_url": affiliate_url,
        "metadata": metadata,
    }
