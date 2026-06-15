"""
V2RAY delivery helpers: QR codes, subscription links, and formatted Telegram messages.
"""
import base64
import io
import logging
from html import escape
from urllib.parse import urlparse

import httpx
import qrcode
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton

from core.settings import get_setting

logger = logging.getLogger(__name__)

META_PREFIX = "@meta|"
V2RAY_PREFIXES = ("vless://", "vmess://", "trojan://", "ss://")
DEFAULT_SERVER_PREFIX = "zyphervpnsalle"


async def allocate_v2ray_server_names(serial: int = None) -> tuple[str, str]:
    """
    Generate server email/remark from the given serial number.
    Does NOT read/write settings - caller provides serial.
    Returns: (panel_email, display_remark)
    """
    from core.settings import get_setting

    raw_prefix = await get_setting("v2ray_server_prefix", DEFAULT_SERVER_PREFIX) or DEFAULT_SERVER_PREFIX
    prefix = raw_prefix.lstrip("@").strip() or DEFAULT_SERVER_PREFIX
    if serial is None:
        serial = 1
    panel_email = f"{prefix}{serial}"
    display_remark = f"@{prefix}{serial}"
    return panel_email, display_remark


def apply_remark_to_link(link: str, remark: str) -> str:
    """Set the name shown in V2ray apps (URL fragment / vmess ps)."""
    from urllib.parse import quote
    import base64
    import json

    remark = remark.strip()
    if not link or not remark:
        return link
    if link.startswith("vmess://"):
        try:
            raw = link.split("vmess://", 1)[1]
            pad = len(raw) % 4
            if pad:
                raw += "=" * (4 - pad)
            data = json.loads(base64.b64decode(raw).decode("utf-8"))
            data["ps"] = remark
            enc = base64.b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()
            return f"vmess://{enc}"
        except Exception:
            return link
    base = link.split("#", 1)[0]
    return f"{base}#{quote(remark)}"


def build_service_config_link(
    direct_link: str,
    sub_code: str,
    email: str = "",
    inbound_id: int = 0,
    client_uuid: str = "",
    remark: str = "",
    serial: int = 0,
) -> str:
    """Persist direct link plus hidden metadata for later delivery."""
    if remark and direct_link:
        direct_link = apply_remark_to_link(direct_link, remark)
    base = direct_link or ""

    # Always include metadata for subscription access
    meta = f"{META_PREFIX}email={email}|inbound={inbound_id}|uuid={client_uuid}"
    if remark:
        meta += f"|remark={remark}"
    if serial:
        meta += f"|serial={serial}"

    parts = [base, f"کد رهگیری: {sub_code}", meta]
    return "\n".join(parts).strip()


def parse_service_meta(config_link: str | None) -> dict:
    if not config_link:
        return {}
    for line in config_link.split("\n"):
        line = line.strip()
        if line.startswith(META_PREFIX):
            raw = line[len(META_PREFIX):]
            out = {}
            for piece in raw.split("|"):
                if "=" in piece:
                    k, v = piece.split("=", 1)
                    out[k.strip()] = v.strip()
            return out
    return {}


def extract_direct_link(config_link: str | None) -> str | None:
    if not config_link:
        return None
    for line in config_link.split("\n"):
        line = line.strip()
        if line.startswith(V2RAY_PREFIXES):
            return line
    return None


def extract_sub_code(panel_username: str | None) -> str:
    return panel_username or ""


def make_qr_bytes(data: str) -> io.BytesIO:
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1a1a2e", back_color="#ffffff")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    buf.name = "qr.png"
    return buf


def build_subscription_url(panel_base_url: str, sub_id: str, sub_path: str | None = None) -> str:
    path = (sub_path or "/sub/").strip()
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path += "/"
    parsed = urlparse(panel_base_url.rstrip("/"))
    base_path = parsed.path.rstrip("/") if parsed.path else ""
    base = f"{parsed.scheme}://{parsed.netloc}{base_path}"
    return f"{base}{path}{quote(str(sub_id), safe='')}"


async def fetch_subscription_configs(sub_url: str) -> list[str]:
    """Fetch all config lines from a subscription URL."""
    try:
        async with httpx.AsyncClient(verify=False, timeout=15.0, follow_redirects=True) as client:
            res = await client.get(sub_url)
            if res.status_code != 200:
                logger.warning(f"Sub fetch HTTP {res.status_code} for {sub_url[:80]}")
                return []
            raw = res.text.strip()
    except Exception as e:
        logger.error(f"Sub fetch error: {e}")
        return []

    decoded = raw
    try:
        pad = len(raw) % 4
        if pad:
            raw += "=" * (4 - pad)
        decoded = base64.b64decode(raw).decode("utf-8", errors="ignore")
    except Exception:
        decoded = raw

    links = []
    for line in decoded.splitlines():
        line = line.strip()
        if line.startswith(V2RAY_PREFIXES):
            links.append(line)

    logger.info(f"Subscription fetch: total_lines={len(decoded.splitlines())}, valid_configs={len(links)}, url={sub_url[:80]}")
    if len(links) > 0:
        logger.info(f"Config sample: {links[0][:100]}")

    return links


def _header_block(title: str, subtitle: str = "") -> str:
    lines = [
        "╔══════════════════════╗",
        f"║  {title}",
    ]
    if subtitle:
        lines.append(f"║  {subtitle}")
    lines.append("╚══════════════════════╝")
    return "\n".join(lines)


def format_sub_delivery_text(sub_code: str, product_name: str, sub_url: str) -> str:
    return (
        f"{_header_block('📡 اشتراک V2RAY', 'تحویل ساب')}\n\n"
        f"🎫 کد: <code>{escape(sub_code)}</code>\n"
        f"📦 محصول: <b>{escape(product_name)}</b>\n\n"
        f"🔗 <b>لینک سابسکریپشن:</b>\n"
        f"<code>{escape(sub_url)}</code>\n\n"
        f"📱 QR بالا را در برنامه V2rayNG / Streisand / Hiddify اسکن کنید.\n"
        f"➖➖➖➖➖➖➖➖➖➖"
    )


def format_config_item_text(index: int, total: int, link: str, remark: str = "", usage_info: str = "") -> str:
    title = f"📋 کانفیگ {index}/{total}"
    if remark:
        title += f" — {escape(remark)}"
    # Show full link and include usage/time info if provided
    lines = [f"{_header_block(title, '🔗 لینک سرور')}", "", f"🔗 <code>{escape(link)}</code>", ""]
    if usage_info:
        lines.append(usage_info)
        lines.append("")
    lines.append("📱 می‌توانید QR را اسکن کنید یا دکمه کپی را بزنید.")
    return "\n".join(lines)


MAX_COPY_TEXT = 4096


def copy_button_row(text: str, label: str = "📋 کپی لینک") -> list:
    if not text:
        return []
    btn = safe_copy_button(text, label)
    return [[btn]] if btn else []


def safe_copy_button(text: str, label: str) -> InlineKeyboardButton | None:
    if not text:
        return None
    safe_text = text[:MAX_COPY_TEXT]
    try:
        return InlineKeyboardButton(label, copy_text=CopyTextButton(text=safe_text))
    except Exception:
        return None


async def send_subscription_delivery(
    bot, chat_id: int, *, sub_url: str, sub_code: str, product_name: str
):
    caption = format_sub_delivery_text(sub_code, product_name, sub_url)
    qr = make_qr_bytes(sub_url)
    keys = copy_button_row(sub_url, "📋 کپی لینک ساب")
    await bot.send_photo(
        chat_id,
        photo=qr,
        caption=caption,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keys) if keys else None,
    )


def extract_remark_from_link(link: str) -> str:
    """Extract remark/name from a v2ray link URL fragment."""
    if not link or "#" not in link:
        return ""
    try:
        from urllib.parse import unquote
        remark = unquote(link.split("#", 1)[1])
        return remark
    except Exception:
        return ""


async def send_individual_configs_delivery(
    bot, chat_id: int, *, links: list[str], sub_code: str, product_name: str, usage_info: str = ""
):
    if not links:
        await bot.send_message(
            chat_id,
            "❌ کانفیگی برای نمایش پیدا نشد. از گزینه «دریافت ساب» استفاده کنید یا به پشتیبانی پیام دهید.",
            parse_mode="HTML",
        )
        return

    intro = (
        f"{_header_block('📋 کانفیگ‌های جدا', escape(product_name))}\n\n"
        f"🎫 کد: <code>{escape(sub_code)}</code>\n"
        f"📊 تعداد: <b>{len(links)}</b> کانفیگ\n\n"
        f"در پیام‌های بعدی هر کانفیگ با QR ارسال می‌شود ⬇️"
    )

    keys = []
    try:
        if len(links) > 1:
            all_text = "\n".join(links)
            btn = safe_copy_button(all_text, "📋 کپی همه کانفیگ‌ها")
            if btn:
                keys = [[btn]]
    except Exception:
        keys = []

    try:
        await bot.send_message(chat_id, intro, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keys) if keys else None)
    except Exception as e:
        logger.error(f"Delivery intro send failed: {e}")
        await bot.send_message(chat_id, intro, parse_mode="HTML")

    for i, link in enumerate(links, 1):
        try:
            remark = extract_remark_from_link(link) if link and "#" in link else f"سرور {i}"
            qr = make_qr_bytes(link)
            caption = format_config_item_text(i, len(links), link, remark, usage_info)
            btn = safe_copy_button(link, f"📋 کپی کانفیگ {i}")
            row = [[btn]] if btn else []
            await bot.send_photo(
                chat_id,
                photo=qr,
                caption=caption,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(row) if row else None,
            )
        except Exception as e:
            logger.error(f"Delivery config {i} failed: {e}")
            try:
                await bot.send_message(
                    chat_id,
                    f"🔗 <b>کانفیگ {i}:</b>\n<code>{escape(link)}</code>",
                    parse_mode="HTML",
                )
            except Exception:
                pass


def delivery_choice_keyboard(service_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📡 دریافت ساب", callback_data=f"v2del_sub_{service_id}"),
            InlineKeyboardButton("📋 کانفیگ‌های جدا", callback_data=f"v2del_cfg_{service_id}"),
        ],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="start_menu")],
    ])


def format_order_confirm_with_delivery(
    base_text: str, sub_code: str, product_name: str, cat_del_msg: str = ""
) -> str:
    extra = ""
    if cat_del_msg:
        extra = f"\n\n📦 <b>توضیحات:</b>\n{cat_del_msg}"
    return (
        f"{base_text}{extra}\n\n"
        f"{'─' * 18}\n"
        f"✨ <b>سرویس شما آماده است!</b>\n\n"
        f"🎫 کد اشتراک: <code>{escape(sub_code)}</code>\n"
        f"📦 محصول: <b>{escape(product_name)}</b>\n\n"
        f"👇 نحوه دریافت کانفیگ را انتخاب کنید:"
    )
