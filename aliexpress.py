import asyncio
import hashlib
import html
import time
from urllib.parse import urlsplit, urlunsplit, urlencode, parse_qsl

import httpx
from config import ALIEXPRESS_APP_KEY, ALIEXPRESS_APP_SECRET, ALIEXPRESS_TRACKING_ID

ALIEXPRESS_DOMAINS = ("aliexpress.com", "s.click.aliexpress.com", "a.aliexpress.com", "ali.ski", "aliexpress.us")
ALIEXPRESS_BAD_PARAMS = {"aff_fcid", "aff_trace_key", "algo_expid", "algo_pvid", "btsid", "ws_ab_test", "scm"}
ALIEXPRESS_GATEWAY = "https://api-sg.aliexpress.com/sync"
RESOLVE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}


def is_aliexpress(url: str) -> bool:
    return any(d in url for d in ALIEXPRESS_DOMAINS)


def clean_aliexpress_url(url: str) -> str:
    parsed = urlsplit(url)
    params = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() not in ALIEXPRESS_BAD_PARAMS]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params, doseq=True), ""))


async def resolve_aliexpress_shortlink(url: str) -> str:
    if "ali.ski" not in url:
        return url
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10, headers=RESOLVE_HEADERS) as http:
            r = await http.get(url)
            resolved = str(r.url)
            print(f"[ALI] ali.ski resolvido: {resolved}")
            return resolved
    except Exception as e:
        print(f"[ALI] Erro ao resolver ali.ski: {e}")
        return url


def _sign_aliexpress_request(params: dict, secret: str) -> str:
    sorted_keys = sorted(params.keys())
    sign_str = secret + "".join(f"{k}{params[k]}" for k in sorted_keys) + secret
    return hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()


async def generate_aliexpress_affiliate_link(product_url: str) -> str | None:
    if not ALIEXPRESS_APP_KEY or not ALIEXPRESS_APP_SECRET:
        print("[ALI] Credenciais da API não configuradas. Configure ALIEXPRESS_APP_KEY e ALIEXPRESS_APP_SECRET no .env.")
        return None

    timestamp = str(int(time.time() * 1000))
    params = {
        "method": "aliexpress.affiliate.link.generate",
        "app_key": ALIEXPRESS_APP_KEY,
        "timestamp": timestamp,
        "sign_method": "md5",
        "v": "2.0",
        "promotion_link_type": "0",
        "source_values": product_url,
        "tracking_id": ALIEXPRESS_TRACKING_ID or "default",
    }
    params["sign"] = _sign_aliexpress_request(params, ALIEXPRESS_APP_SECRET)

    try:
        async with httpx.AsyncClient(timeout=15, headers=RESOLVE_HEADERS) as http:
            r = await http.post(ALIEXPRESS_GATEWAY, data=params, headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"})
            r.raise_for_status()
            data = r.json()

        resp = data.get("aliexpress_affiliate_link_generate_response", {})
        result = resp.get("resp_result", {})
        if result.get("resp_code") != 200:
            print(f"[ALI] API retornou erro: {result.get('resp_msg')}")
            return None

        links = result.get("result", {}).get("promotion_links", {}).get("promotion_link", [])
        if links:
            promotion_link = links[0].get("promotion_link")
            print(f"[ALI] Link de afiliado gerado: {promotion_link}")
            return promotion_link

        print("[ALI] API não retornou links.")
        return None
    except httpx.HTTPStatusError as e:
        print(f"[ALI] API HTTP {e.response.status_code}: {e.response.text[:200]}")
        return None
    except Exception as e:
        print(f"[ALI] Erro na API: {e}")
        return None


def get_aliexpress_metadata_browser_sync(product_url: str) -> dict:
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
            for selector in ["h1.product-title-text", ".product-title h1", "h1", 'meta[property="og:title"]']:
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
            for selector in ['meta[property="og:image"]', ".magnifier-image", ".slider-item img", 'img[src*="ae01.alicdn.com"]', 'img[src*="alicdn.com"]']:
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
                print(f"[ALI] Título: {title}")
            if image_url:
                print(f"[ALI] Imagem: {image_url}")
            else:
                print("[ALI] Imagem não encontrada.")
            return {"title": title, "image_url": image_url}
        except PlaywrightError as e:
            print(f"[ALI] Browser erro: {e}")
            return {}
        finally:
            browser.close()


async def fetch_aliexpress_metadata(product_url: str) -> dict:
    return await asyncio.to_thread(get_aliexpress_metadata_browser_sync, product_url)


async def build_aliexpress_affiliate_result(url: str) -> dict | None:
    resolved = await resolve_aliexpress_shortlink(url)
    clean_url = clean_aliexpress_url(resolved)
    print(f"[ALI] URL limpa: {clean_url}")
    affiliate_url = await generate_aliexpress_affiliate_link(clean_url)
    if not affiliate_url:
        print("[ALI] Sem link de afiliado. Repostando sem modificação.")
        return None
    print(f"[ALI] Link final: {affiliate_url}")
    metadata = await fetch_aliexpress_metadata(clean_url)
    return {"affiliate_url": affiliate_url, "product_url": clean_url, "metadata": metadata}
