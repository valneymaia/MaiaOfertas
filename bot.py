import asyncio
import html
import io
import re
import httpx
from urllib.parse import urlsplit
from telethon import TelegramClient, events, functions
from telethon.utils import get_peer_id
from telethon.tl.types import Channel, Chat
from config import (
    API_ID, API_HASH, SESSION_NAME,
    SOURCE_GROUPS, TARGET_GROUP,
)
from marketplaces.mercadolivre import is_ml, build_ml_affiliate_result, validate_ml_config
from marketplaces.amazon import is_amazon, build_amazon_affiliate_result
from marketplaces.shopee import is_shopee, build_shopee_affiliate_result
from marketplaces.aliexpress import is_aliexpress, build_aliexpress_affiliate_result

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
ML_MEDIA_TIMEOUT = 15
RESOLVE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

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

def hidden_entity_urls(message):
    text = message.text or ""
    entities = message.entities or []
    urls = []

    for entity in entities:
        hidden_url = getattr(entity, "url", None)
        if not hidden_url or hidden_url in text:
            continue

        urls.append(hidden_url)

    if urls:
        print(f"[MSG] Links escondidos extraidos: {len(urls)}")
    return urls

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

def image_download_headers(image_url):
    host = urlsplit(image_url).netloc.lower()
    if "shopee" in host or "susercontent.com" in host:
        headers = {
            **RESOLVE_HEADERS,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        headers["Referer"] = "https://shopee.com.br/"
        return headers
    return RESOLVE_HEADERS

def filename_for_image_response(response):
    return "produto.jpg"

async def download_image_file(image_url):
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=ML_MEDIA_TIMEOUT,
            headers=image_download_headers(image_url),
        ) as http:
            response = await http.get(image_url)
            response.raise_for_status()
    except Exception as e:
        print(f"[!] Nao consegui baixar imagem do produto: {e}")
        return None

    image_file = io.BytesIO(response.content)
    image_file.name = filename_for_image_response(response)
    return image_file

async def download_source_media_file(message, allow_webpage_preview=True):
    if not getattr(message, "media", None):
        return None

    webpage = getattr(message.media, "webpage", None)
    if webpage and not allow_webpage_preview:
        print("[SRC] Preview original ignorado para nao usar imagem do cupom.")
        return None

    targets = [message]
    webpage_photo = getattr(webpage, "photo", None)
    if webpage_photo and allow_webpage_preview:
        targets.append(webpage_photo)

    for target in targets:
        image_file = io.BytesIO()
        try:
            downloaded = await client.download_media(target, file=image_file)
        except Exception as e:
            print(f"[SRC] Nao consegui baixar midia original: {e}")
            continue

        if not downloaded or image_file.tell() == 0:
            continue

        image_file.seek(0)
        image_file.name = "produto.jpg"
        print("[SRC] Usando midia original do Telegram como imagem.")
        return image_file

    return None

async def download_telegram_webpage_preview_file(url):
    target = None

    try:
        preview = await client(functions.messages.GetWebPagePreviewRequest(url))
        webpage = getattr(preview, "webpage", None)
        target = getattr(webpage, "photo", None) or getattr(webpage, "document", None)
    except Exception as e:
        print(f"[SRC] Telegram nao gerou preview direto do segundo link: {e}")

    if not target:
        temp_message = None
        try:
            temp_message = await client.send_message("me", url, link_preview=True)
            await asyncio.sleep(3)
            temp_message = await client.get_messages("me", ids=temp_message.id)
            webpage = getattr(getattr(temp_message, "media", None), "webpage", None)
            target = getattr(webpage, "photo", None) or getattr(webpage, "document", None)
        except Exception as e:
            print(f"[SRC] Telegram nao gerou preview temporario do segundo link: {e}")
        finally:
            if temp_message:
                try:
                    await client.delete_messages("me", [temp_message.id], revoke=True)
                except Exception:
                    pass

    if not target:
        print("[SRC] Preview do segundo link nao tem foto.")
        return None

    image_file = io.BytesIO()
    try:
        downloaded = await client.download_media(target, file=image_file)
    except Exception as e:
        print(f"[SRC] Nao consegui baixar preview do segundo link: {e}")
        return None

    if not downloaded or image_file.tell() == 0:
        print("[SRC] Preview do segundo link veio vazio.")
        return None

    image_file.seek(0)
    image_file.name = "produto.jpg"
    print("[SRC] Usando preview do segundo link Shopee como imagem.")
    return image_file

async def process_message(text, extra_urls=None):
    text = remove_promo_group_blocks(text)
    visible_urls = URL_REGEX.findall(text)
    extra_urls = [
        raw_url for raw_url in (extra_urls or [])
        if is_shopee(raw_url.strip(".,)\"'"))
    ]
    url_entries = [(raw_url, True) for raw_url in visible_urls]
    url_entries.extend((raw_url, False) for raw_url in extra_urls)
    if not url_entries:
        return None
    modified = text
    found = False
    media = {"link_preview": True}
    shopee_total = sum(1 for raw, _ in url_entries if is_shopee(raw.strip(".,)\"'")))
    shopee_seen = 0
    for raw_url, is_visible_url in url_entries:
        if is_visible_url and raw_url not in modified:
            continue

        url = raw_url.strip(".,)\"'")
        print(f"[URL] {url}")
        resolved = await resolve_redirect(url)
        print(f"[RES] {resolved}")
        if is_ml(resolved):
            ml_result = await build_ml_affiliate_result(resolved)
            if ml_result:
                new_url = ml_result["affiliate_url"]
                if is_visible_url:
                    modified = modified.replace(raw_url, new_url)
                print(f"[ML ] {new_url}")
                if not media.get("image_url"):
                    media = ml_result.get("metadata") or {}
                    media["link_preview"] = False
                found = True
            else:
                print("[~  ] ML nao gerou link afiliado.")
                if is_visible_url:
                    modified = remove_url_from_text(modified, raw_url)
        elif is_amazon(resolved):
            amazon_result = await build_amazon_affiliate_result(resolved)
            if amazon_result:
                new_url = amazon_result["affiliate_url"]
                if is_visible_url:
                    modified = modified.replace(raw_url, new_url)
                print(f"[AMZ] {new_url}")
                if not media.get("image_url"):
                    media = amazon_result.get("metadata") or {}
                    if media.get("image_url"):
                        media["link_preview"] = False
                    else:
                        media["link_preview"] = True
                        media["source_media_fallback"] = True
                        media["source_media_allow_webpage"] = True
                found = True
            else:
                print("[~  ] Amazon nao gerou link afiliado.")
                if is_visible_url:
                    modified = remove_url_from_text(modified, raw_url)
        elif is_shopee(url) or is_shopee(resolved):
            shopee_seen += 1
            shopee_source_url = url if is_shopee(url) else resolved
            use_second_shopee_link_for_media = shopee_total >= 2
            fetch_shopee_media = (
                shopee_seen == 2 if use_second_shopee_link_for_media else True
            )
            shopee_result = await build_shopee_affiliate_result(
                shopee_source_url,
                fetch_metadata=fetch_shopee_media,
                metadata_from_meta_only=use_second_shopee_link_for_media and shopee_seen == 2,
            )
            if shopee_result:
                new_url = shopee_result["affiliate_url"]
                if is_visible_url:
                    modified = modified.replace(raw_url, new_url)
                print(f"[SHP] {new_url}")
                media["link_preview"] = False
                media["source_media_fallback"] = shopee_total < 2
                media["source_media_allow_webpage"] = shopee_total < 2
                if use_second_shopee_link_for_media and shopee_seen == 2:
                    media["telegram_preview_url"] = shopee_source_url
                shopee_metadata = shopee_result.get("metadata") or {}
                if not media.get("image_url") and shopee_metadata.get("image_url"):
                    telegram_preview_url = media.get("telegram_preview_url")
                    media = shopee_metadata
                    media["link_preview"] = False
                    media["source_media_fallback"] = shopee_total < 2
                    media["source_media_allow_webpage"] = shopee_total < 2
                    if telegram_preview_url:
                        media["telegram_preview_url"] = telegram_preview_url
                found = True
            else:
                print("[~  ] Shopee nao gerou link afiliado.")
                if is_visible_url:
                    modified = remove_url_from_text(modified, raw_url)
        elif is_aliexpress(resolved):
            ali_result = await build_aliexpress_affiliate_result(resolved)
            if ali_result:
                new_url = ali_result["affiliate_url"]
                if is_visible_url:
                    modified = modified.replace(raw_url, new_url)
                print(f"[ALI] {new_url}")
                if not media.get("image_url"):
                    media = ali_result.get("metadata") or {}
                    media["link_preview"] = False
                found = True
            else:
                print("[~  ] AliExpress nao gerou link afiliado.")
                if is_visible_url:
                    modified = remove_url_from_text(modified, raw_url)
        else:
            print(f"[~  ] Nao e ML, Amazon, Shopee nem AliExpress. Link removido.")
            if is_visible_url:
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

    validate_ml_config()

    print(f"\nMonitorando {len(RESOLVED_SOURCE_IDS)} grupos. Aguardando mensagens...\n")
    await client.run_until_disconnected()

@client.on(events.NewMessage())
async def handler(event):
    chat = await event.get_chat()
    chat_id = event.chat_id
    chat_name = getattr(chat, 'title', None) or getattr(chat, 'username', None) or str(chat_id)

    text = event.message.text or ""
    extra_urls = hidden_entity_urls(event.message)
    print(f"[MSG] {chat_name} ({chat_id}): {text[:60]!r}")

    if chat_id not in RESOLVED_SOURCE_IDS:
        return

    if not text:
        return

    result = await process_message(text, extra_urls=extra_urls)
    if result is None:
        print("[~] Sem link afiliado.")
        return

    if resolved_target is None:
        print("[!!] Grupo de destino nao resolvido; nao foi possivel repostar.")
        return

    result_text = result["text"]
    media = result.get("media") or {}
    image_url = media.get("image_url")
    image_file = None

    if image_url:
        image_file = await download_image_file(image_url)

    if not image_file and media.get("telegram_preview_url"):
        image_file = await download_telegram_webpage_preview_file(media["telegram_preview_url"])

    if not image_file and media.get("source_media_fallback"):
        image_file = await download_source_media_file(
            event.message,
            allow_webpage_preview=media.get("source_media_allow_webpage", True),
        )

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
