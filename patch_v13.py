from pathlib import Path

BOT = Path("restock_bot_github.py")
PATCH = Path("patch_v13.py")

text = BOT.read_text(encoding="utf-8")


def replace_between(source, start_marker, end_marker, replacement):
    start = source.find(start_marker)
    if start == -1:
        raise RuntimeError(f"Missing start marker: {start_marker[:80]}")
    end = source.find(end_marker, start)
    if end == -1:
        raise RuntimeError(f"Missing end marker: {end_marker[:80]}")
    return source[:start] + replacement + source[end:]


# ---------------------------------------------------------
# curl_cffi / browser-TLS fallback for Proshop
# ---------------------------------------------------------
if "from curl_cffi import requests as curl_requests" not in text:
    text = text.replace(
        "import requests\n",
        "import requests\n\ntry:\n    from curl_cffi import requests as curl_requests\nexcept ImportError:\n    curl_requests = None\n",
        1,
    )


# ---------------------------------------------------------
# Discord embeds: each alert becomes a separate visual card.
# Plain URLs inside embeds do not create the huge link previews
# that made the channels feel stacked/cluttered.
# ---------------------------------------------------------
discord_start = "# =========================================================\n# DISCORD\n# =========================================================\n"
discord_end = "# =========================================================\n# PRIS\n# =========================================================\n"

discord_block = '''# =========================================================
# DISCORD
# =========================================================

def _discord_embed_color(message, kind="restock"):
    upper = (message or "").upper()

    if "FORUDBESTILLING" in upper or "PREORDER" in upper:
        return 0xFEE75C

    if (
        "BEDRE PRIS" in upper
        or "PRISFALD" in upper
        or "RESTOCK" in upper
    ):
        return 0x57F287

    if "BEDSTE PRIS ÆNDRET" in upper:
        return 0xF0B232

    if "NYT" in upper or "DAGENS BEDSTE PRISER" in upper:
        return 0x5865F2

    return 0x5865F2 if kind == "restock" else 0x57F287


def _discord_embed_payload(message, kind="restock"):
    lines = (message or "").splitlines()

    if lines:
        title = lines[0].replace("**", "").strip()
        description = "\\n".join(lines[1:]).strip()
    else:
        title = "MasterBot"
        description = ""

    if not title:
        title = "MasterBot"

    # Discord limits: title 256, description 4096.
    title = title[:256]
    description = (description or " ")[:4096]

    footer = (
        "MasterBot · Price Watch"
        if kind == "price"
        else "MasterBot · Restock Watch"
    )

    return {
        "username": "MasterBot",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": _discord_embed_color(message, kind),
                "footer": {"text": footer},
            }
        ],
    }


def _post_discord(webhook_url, message, kind):
    response = requests.post(
        webhook_url,
        json=_discord_embed_payload(message, kind),
        headers={
            "User-Agent": "Pokemon-Lorcana-MasterBot/1.3"
        },
        timeout=20,
    )

    response.raise_for_status()


def send_discord(message):
    _post_discord(
        WEBHOOK_URL,
        message,
        "restock",
    )


def send_price_watch(message):
    if not PRICE_WATCH_WEBHOOK_URL:
        print(
            "PRICE_WATCH_WEBHOOK_URL mangler - "
            "springer Price Watch-besked over."
        )
        return

    _post_discord(
        PRICE_WATCH_WEBHOOK_URL,
        message,
        "price",
    )


'''

text = replace_between(
    text,
    discord_start,
    discord_end,
    discord_block,
)


# ---------------------------------------------------------
# Proshop: use real browser TLS fingerprint first, then
# requests-session fallback with warm-up/retries.
# ---------------------------------------------------------
proshop_start = "def get_proshop_products():\n"
proshop_end = "\n\n# =========================================================\n# BR FRONTEND CONFIG\n# =========================================================\n"

proshop_block = '''def get_proshop_products():
    headers = {
        **BROWSER_HEADERS,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "da-DK,da;q=0.9,en-US;q=0.7,en;q=0.6",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": PROSHOP_BASE + "/",
        "Upgrade-Insecure-Requests": "1",
    }

    response = None
    last_error = None

    # GitHub-hosted runners are sometimes blocked when using the plain
    # requests TLS fingerprint. curl_cffi impersonates a normal Chrome
    # browser while keeping the scan rate unchanged.
    if curl_requests is not None:
        try:
            session = curl_requests.Session(
                impersonate="chrome"
            )

            try:
                session.get(
                    PROSHOP_BASE + "/",
                    headers=headers,
                    timeout=20,
                )
            except Exception:
                pass

            for attempt in range(3):
                candidate = session.get(
                    PROSHOP_URL,
                    headers=headers,
                    timeout=30,
                )

                if candidate.status_code == 200:
                    response = candidate
                    break

                last_error = RuntimeError(
                    f"Proshop HTTP {candidate.status_code}"
                )

                if candidate.status_code not in (403, 429):
                    candidate.raise_for_status()

                time.sleep(2 + attempt * 2)

        except Exception as error:
            last_error = error

    # Conservative fallback if curl_cffi is unavailable or Proshop changes.
    if response is None:
        session = requests.Session()
        session.headers.update(headers)

        try:
            session.get(
                PROSHOP_BASE + "/",
                timeout=20,
            )
        except requests.RequestException:
            pass

        for attempt in range(3):
            candidate = session.get(
                PROSHOP_URL,
                timeout=30,
            )

            if candidate.status_code == 200:
                response = candidate
                break

            last_error = RuntimeError(
                f"Proshop HTTP {candidate.status_code}"
            )

            if candidate.status_code not in (403, 429):
                candidate.raise_for_status()

            time.sleep(3 + attempt * 3)

    if response is None:
        if last_error:
            raise last_error
        raise RuntimeError("Proshop kunne ikke hentes efter retries")

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    products = {}

    cards = soup.select(
        "li.site-productlist-item"
    )

    for card in cards:
        link = card.find(
            "a",
            href=re.compile(
                r"/Pokemon/[^?#]+/\\d+(?:[?#].*)?$",
                re.IGNORECASE
            )
        )

        if not link:
            continue

        href = link["href"]

        match = re.search(
            r"/(\\d+)(?:[?#].*)?$",
            href
        )

        if not match:
            continue

        product_id = match.group(1)

        text_card = card.get_text(
            " ",
            strip=True
        )

        name = clean_proshop_name(
            href
        )

        price = parse_price(
            text_card
        )

        if "På lager" in text_card:
            stock = "PÅ LAGER"
        elif "Fjernlager" in text_card:
            stock = "FJERNLAGER"
        elif "Bestillingsvare" in text_card:
            stock = "BESTILLINGSVARE"
        else:
            stock = "UKENDT"

        url = urljoin(
            PROSHOP_BASE,
            href
        )

        products[product_id] = {
            "name": name,
            "price": price,
            "stock": stock,
            "url": url
        }

    if not products:
        raise RuntimeError(
            "Proshop svarede 200, men produktlisten kunne ikke parses"
        )

    return products
'''

text = replace_between(
    text,
    proshop_start,
    proshop_end,
    proshop_block,
)


# ---------------------------------------------------------
# Elgiganten: persistent signed-key cache + rate-limit backoff.
# The previous process-memory cache was lost on every GitHub Action,
# so signed-api-key was unnecessarily hit every five minutes.
# ---------------------------------------------------------
elgig_start = "def get_elgiganten_signed_key(force=False):\n"
elgig_end = "\n\ndef is_real_elgiganten_pokemon_tcg(product):\n"

elgig_block = '''def get_elgiganten_signed_key(force=False):
    cached_key = ELGIGANTEN_KEY_CACHE.get("api_key")
    valid_until = safe_int(
        ELGIGANTEN_KEY_CACHE.get("valid_until"),
        0
    )

    if (
        not force
        and cached_key
        and (valid_until == 0 or time.time() < valid_until - 120)
    ):
        return cached_key

    session = requests.Session()

    headers = {
        **BROWSER_HEADERS,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
        "Referer": ELGIGANTEN_HOME
    }

    response = None

    for attempt in range(3):
        response = session.get(
            ELGIGANTEN_SIGNED_KEY_URL,
            headers=headers,
            timeout=20
        )

        if response.status_code in (401, 403):
            try:
                session.get(
                    ELGIGANTEN_HOME,
                    headers=BROWSER_HEADERS,
                    timeout=20
                )
            except requests.RequestException:
                pass

            response = session.get(
                ELGIGANTEN_SIGNED_KEY_URL,
                headers=headers,
                timeout=20
            )

        if response.status_code != 429:
            break

        retry_after = safe_int(
            response.headers.get("Retry-After"),
            0
        )

        wait_seconds = retry_after or (5 * (attempt + 1))
        wait_seconds = max(3, min(wait_seconds, 30))

        print(
            f"ELGIGANTEN signed-key rate limit (429) - "
            f"retry om {wait_seconds}s"
        )
        time.sleep(wait_seconds)

    if response is None:
        raise RuntimeError("Elgiganten signed-api-key gav intet svar")

    # If the endpoint itself is rate limited but we have a recently cached
    # public signed key, prefer trying it instead of dropping the source.
    if response.status_code == 429 and cached_key:
        if valid_until == 0 or time.time() < valid_until + 300:
            print(
                "ELGIGANTEN: bruger cached signed key under 429 rate limit."
            )
            return cached_key

    response.raise_for_status()

    data = response.json()
    api_key = data.get("apiKey")

    if not api_key:
        raise RuntimeError(
            "Elgiganten signed-api-key svarede uden apiKey."
        )

    ELGIGANTEN_KEY_CACHE["api_key"] = api_key
    ELGIGANTEN_KEY_CACHE["valid_until"] = (
        get_elgiganten_key_valid_until(api_key)
    )

    return api_key
'''

text = replace_between(
    text,
    elgig_start,
    elgig_end,
    elgig_block,
)


# Restore the Elgiganten cache immediately after loading persisted state.
restore_marker = "state = load_state()\n"
restore_code = '''state = load_state()

# Persist the public Elgiganten signed Algolia key between GitHub Action
# runs. Without this, process-memory cache resets every five minutes.
if isinstance(state, dict):
    saved_elgiganten_cache = state.get(
        "_elgiganten_key_cache"
    )

    if isinstance(saved_elgiganten_cache, dict):
        cached_api_key = saved_elgiganten_cache.get("api_key")
        cached_valid_until = safe_int(
            saved_elgiganten_cache.get("valid_until"),
            0
        )

        if cached_api_key:
            ELGIGANTEN_KEY_CACHE["api_key"] = cached_api_key
            ELGIGANTEN_KEY_CACHE["valid_until"] = cached_valid_until
'''

if "saved_elgiganten_cache = state.get(" not in text:
    if restore_marker not in text:
        raise RuntimeError("Could not find state = load_state()")
    text = text.replace(
        restore_marker,
        restore_code,
        1,
    )


# Persist key cache in the initial baseline state.
baseline_old = '''            "epicpanda": epicpanda,
            "steffeno": steffeno,
            "nextlevel": nextlevel
        }
'''
baseline_new = '''            "epicpanda": epicpanda,
            "steffeno": steffeno,
            "nextlevel": nextlevel,
            "_elgiganten_key_cache": dict(ELGIGANTEN_KEY_CACHE)
        }
'''

if baseline_new not in text:
    if baseline_old not in text:
        raise RuntimeError("Could not find baseline state dictionary")
    text = text.replace(
        baseline_old,
        baseline_new,
        1,
    )


# Persist refreshed key cache on every normal scan.
save_marker = '''        save_state(
            new_state
        )
'''
save_new = '''        new_state["_elgiganten_key_cache"] = dict(
            ELGIGANTEN_KEY_CACHE
        )

        save_state(
            new_state
        )
'''

if save_new not in text:
    if save_marker not in text:
        raise RuntimeError("Could not find normal save_state(new_state)")
    text = text.replace(
        save_marker,
        save_new,
        1,
    )


# Cosmetic log label: logic is V3 after the anti-flap patch.
text = text.replace(
    'f"PRICE WATCH V1: "',
    'f"PRICE WATCH V3: "',
)
text = text.replace(
    "# PRICE WATCH V1\n",
    "# PRICE WATCH V3\n",
)

BOT.write_text(text, encoding="utf-8")
PATCH.unlink(missing_ok=True)

print(
    "V1.3 patch applied: Discord embeds + Proshop browser fallback + "
    "Elgiganten persistent key cache/backoff."
)
