import asyncio
import html
import re
from urllib.parse import parse_qs, parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

import httpx
from config import SHOPEE_AFFILIATE_ID

SHOPEE_DOMAINS = ("shopee.com.br", "s.shopee.com.br", "shp.ee", "shopee.com")
SHOPEE_SHORT_HOSTS = ("s.shopee.com.br", "shp.ee")
SHOPEE_PRODUCT_HOSTS = (
    "shopee.com.br",
    "www.shopee.com.br",
    "m.shopee.com.br",
    "shopee.com",
    "www.shopee.com",
    "m.shopee.com",
)
SHOPEE_ASSET_HOST_MARKERS = (
    "deo.shopeemobile.com",
    "shopee-pcmall",
    "assets/",
)
SHOPEE_PRODUCT_IMAGE_HOST_MARKERS = (
    "susercontent.com",
    "down-br.img.susercontent.com",
    "down-sg.img.susercontent.com",
    "cf.shopee.com.br/file/",
    "cf.shopee.com/file/",
    "down-cvs-br.img.susercontent.com",
    "down-cvs-sg.img.susercontent.com",
    "img.susercontent.com",
)
SHOPEE_LOGIN_TITLE_MARKERS = (
    "faça login",
    "faca login",
    "comece suas compras",
    "shopee brasil",
)

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
SHOPEE_ITEM_API_URL = "https://shopee.com.br/api/v4/item/get"
SHOPEE_ITEM_PATH_RE = re.compile(r"(?:^|-)i\.(\d+)\.(\d+)(?:[/?#]|$)", re.I)
META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.I)


def is_shopee(url: str) -> bool:
    return any(d in url for d in SHOPEE_DOMAINS)


def normalize_shopee_url(url: str) -> str:
    return html.unescape(url).replace("\\/", "/").strip(".,)\"'")


def get_shopee_origin_link(url: str) -> str | None:
    parsed = urlsplit(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    origin = (
        query.get("origin_link")
        or query.get("originLink")
        or query.get("url")
        or query.get("u")
    )
    if not origin or not origin[0]:
        return None
    return normalize_shopee_url(unquote(origin[0]))


def extract_shopee_item_ids(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url)
    host = parsed.netloc.lower()
    if not any(product_host in host for product_host in SHOPEE_PRODUCT_HOSTS):
        return None

    path_match = SHOPEE_ITEM_PATH_RE.search(parsed.path)
    if path_match:
        return path_match.group(1), path_match.group(2)

    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) >= 3 and path_parts[-3].lower() == "product":
        shop_id, item_id = path_parts[-2], path_parts[-1]
        if shop_id.isdigit() and item_id.isdigit():
            return shop_id, item_id

    if len(path_parts) >= 2:
        shop_id, item_id = path_parts[-2], path_parts[-1]
        if shop_id.isdigit() and item_id.isdigit():
            return shop_id, item_id

    query = parse_qs(parsed.query)
    shop_id = (query.get("shopid") or query.get("shop_id") or [None])[0]
    item_id = (query.get("itemid") or query.get("item_id") or [None])[0]
    if shop_id and item_id and shop_id.isdigit() and item_id.isdigit():
        return shop_id, item_id
    return None


def is_shopee_product_url(url: str) -> bool:
    return extract_shopee_item_ids(url) is not None


def is_bad_shopee_title(title: str | None) -> bool:
    if not title:
        return True
    normalized = title.strip().lower()
    return any(marker in normalized for marker in SHOPEE_LOGIN_TITLE_MARKERS)


def is_bad_shopee_image_url(image_url: str | None) -> bool:
    if not image_url:
        return True
    normalized = image_url.lower()
    if any(marker in normalized for marker in SHOPEE_ASSET_HOST_MARKERS):
        return True
    return not any(marker in normalized for marker in SHOPEE_PRODUCT_IMAGE_HOST_MARKERS)


def get_attr_from_tag(tag: str, attr: str) -> str | None:
    match = re.search(
        rf"""{attr}\s*=\s*(['"])(.*?)\1""",
        tag,
        flags=re.I | re.S,
    )
    if not match:
        return None
    return html.unescape(match.group(2).strip())


def find_meta_content(page_html: str, names: tuple[str, ...]) -> str | None:
    wanted = {name.lower() for name in names}
    for tag_match in META_TAG_RE.finditer(page_html):
        tag = tag_match.group(0)
        key = get_attr_from_tag(tag, "property") or get_attr_from_tag(tag, "name")
        if not key or key.lower() not in wanted:
            continue
        content = get_attr_from_tag(tag, "content")
        if content:
            return normalize_shopee_url(content)
    return None


def shopee_image_url_from_id(image_id: str | None) -> str | None:
    if not image_id:
        return None
    image_id = str(image_id).strip()
    if image_id.startswith("http://") or image_id.startswith("https://"):
        return normalize_shopee_url(image_id)
    return f"https://down-br.img.susercontent.com/file/{image_id}"


def first_shopee_image_from_item_data(item_data: dict) -> str | None:
    item_basic = item_data.get("item_basic") or {}
    candidates = [
        item_data.get("image"),
        item_basic.get("image"),
    ]

    for image_list in (item_data.get("images"), item_basic.get("images")):
        if isinstance(image_list, list):
            candidates.extend(image_list)

    for tier_variation in item_data.get("tier_variations") or item_basic.get("tier_variations") or []:
        if not isinstance(tier_variation, dict):
            continue
        for option in tier_variation.get("options") or []:
            if isinstance(option, dict):
                candidates.append(option.get("image"))

    for candidate in candidates:
        image_url = shopee_image_url_from_id(candidate)
        if image_url and not is_bad_shopee_image_url(image_url):
            return image_url
    return None


async def fetch_shopee_item_api_metadata(product_url: str) -> dict:
    ids = extract_shopee_item_ids(product_url)
    if not ids:
        return {}

    shop_id, item_id = ids
    headers = {
        **RESOLVE_HEADERS,
        "Accept": "application/json, text/plain, */*",
        "Referer": product_url,
        "X-Requested-With": "XMLHttpRequest",
    }
    params = {"shopid": shop_id, "itemid": item_id}

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15, headers=headers) as http:
            response = await http.get(SHOPEE_ITEM_API_URL, params=params)
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        print(f"[SHP] API item nao retornou imagem: {e}")
        return {}

    item_data = data.get("data") or {}
    if not isinstance(item_data, dict):
        return {}

    title = item_data.get("name") or (item_data.get("item_basic") or {}).get("name")
    image_url = first_shopee_image_from_item_data(item_data)
    if image_url:
        print(f"[SHP] Foto do produto via API item: {image_url}")
        return {"title": title, "image_url": image_url}
    return {}


def clean_shopee_url(url: str) -> str:
    parsed = urlsplit(url)
    params = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in SHOPEE_BAD_PARAMS
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params, doseq=True), ""))


async def resolve_shopee_shortlink(url: str) -> str:
    url = normalize_shopee_url(url)
    origin_link = get_shopee_origin_link(url)
    if origin_link and origin_link != url:
        print(f"[SHP] origin_link encontrado: {origin_link}")
        return await resolve_shopee_shortlink(origin_link)

    parsed = urlsplit(url)
    host = parsed.netloc.lower()
    is_short_url = any(short_host in host for short_host in SHOPEE_SHORT_HOSTS)
    if not is_short_url:
        return url
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10, headers=RESOLVE_HEADERS) as http:
            r = await http.get(url)
            resolved = normalize_shopee_url(str(r.url))
            print(f"[SHP] shp.ee resolvido: {resolved}")
            return await resolve_shopee_shortlink(resolved)
    except Exception as e:
        print(f"[SHP] Erro ao resolver shp.ee: {e}")
        return url


def build_shopee_affiliate_url(product_url: str) -> str | None:
    if not SHOPEE_AFFILIATE_ID:
        print("[SHP] SHOPEE_AFFILIATE_ID não configurado. Configure no .env.")
        return None
    encoded_url = quote(product_url, safe="")
    return (
        f"{SHOPEE_AFFILIATE_URL}"
        f"?origin_link={encoded_url}"
        f"&affiliate_id={SHOPEE_AFFILIATE_ID}"
        f"&sub_id=telegram"
    )


def get_shopee_metadata_browser_sync(product_url: str, meta_only: bool = False) -> dict:
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
            title_selectors = [
                "._44qnta",
                ".product-name--text",
                "h1",
                'meta[property="og:title"]',
                'meta[name="twitter:title"]',
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
            if is_bad_shopee_title(title):
                title = None

            image_url = None
            meta_image_selectors = [
                'meta[property="og:image"]',
                'meta[name="twitter:image"]',
                'meta[property="twitter:image"]',
            ]
            image_selectors = meta_image_selectors
            if not meta_only:
                image_selectors = [
                    ".gallery-preview-panel__image img",
                    ".product-image__image--thumbnail img",
                    'img[src*="down-br.img.susercontent.com"]',
                    'img[src*="cf.shopee.com.br/file"]',
                    'img[src*="img.susercontent.com"]',
                    *meta_image_selectors,
                ]
            for selector in image_selectors:
                locator = page.locator(selector).first
                if locator.count() == 0:
                    continue
                if selector.startswith("meta"):
                    candidate = locator.get_attribute("content")
                else:
                    candidate = locator.get_attribute("src") or locator.get_attribute("data-src") or ""
                if candidate and candidate.startswith("//"):
                    candidate = "https:" + candidate
                if candidate and not is_bad_shopee_image_url(candidate):
                    image_url = candidate
                    break

            if title:
                print(f"[SHP] Título: {title}")
            if image_url:
                source = "metatag" if meta_only else "pagina"
                print(f"[SHP] Imagem via {source}: {image_url}")
            else:
                print("[SHP] Imagem não encontrada.")
            return {"title": title, "image_url": image_url}
        except PlaywrightError as e:
            print(f"[SHP] Browser erro: {e}")
            return {}
        finally:
            browser.close()


async def fetch_shopee_metadata(product_url: str, meta_only: bool = False) -> dict:
    if not is_shopee_product_url(product_url):
        print("[SHP] Link nao parece produto claro; tentando buscar imagem mesmo assim.")
    api_metadata = await fetch_shopee_item_api_metadata(product_url)
    if api_metadata.get("image_url"):
        return api_metadata

    if meta_only:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15, headers=RESOLVE_HEADERS) as http:
                response = await http.get(product_url)
                page_html = response.text
            title = find_meta_content(page_html, ("og:title", "twitter:title"))
            if is_bad_shopee_title(title):
                title = None
            image_url = find_meta_content(
                page_html,
                ("og:image", "twitter:image", "twitter:image:src", "og:image:secure_url"),
            )
            if image_url and image_url.startswith("//"):
                image_url = "https:" + image_url
            if image_url and not is_bad_shopee_image_url(image_url):
                print(f"[SHP] Foto do produto encontrada no segundo link: {image_url}")
                return {"title": title, "image_url": image_url}
            print("[SHP] Segundo link nao trouxe foto valida no HTML; tentando navegador.")
        except Exception as e:
            print(f"[SHP] Erro ao ler metatag HTTP: {e}")
    return await asyncio.to_thread(get_shopee_metadata_browser_sync, product_url, meta_only)


async def build_shopee_affiliate_result(
    url: str,
    fetch_metadata: bool = True,
    metadata_from_meta_only: bool = False,
) -> dict | None:
    resolved = await resolve_shopee_shortlink(url)
    clean_url = clean_shopee_url(resolved)
    is_product = is_shopee_product_url(clean_url)
    print(f"[SHP] URL limpa: {clean_url}")
    if is_product:
        print("[SHP] Link identificado como produto.")
    else:
        print("[SHP] Link identificado como cupom/live/outro; nao sera usado para imagem.")
    affiliate_url = build_shopee_affiliate_url(clean_url)
    if not affiliate_url:
        return None
    print(f"[SHP] Link afiliado: {affiliate_url}")
    metadata = {}
    if fetch_metadata:
        metadata = await fetch_shopee_metadata(clean_url, meta_only=metadata_from_meta_only)
    else:
        print("[SHP] Busca de imagem pulada; aguardando link de produto da mensagem.")
    return {
        "affiliate_url": affiliate_url,
        "product_url": clean_url,
        "is_product_url": is_product,
        "metadata": metadata,
    }
