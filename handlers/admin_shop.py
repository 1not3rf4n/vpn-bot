from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from database.models import AsyncSessionLocal, User, Category, Product
from handlers.admin import check_admin, CANCEL_BTN, admin_panel

(WAIT_CAT_NAME, WAIT_PROD_V2RAY, WAIT_PROD_VOL, WAIT_PROD_INBOUND, WAIT_PROD_NAME, WAIT_PROD_PRICE, WAIT_PROD_DUR, WAIT_PROD_DESC) = range(50, 58)
(EDIT_PROD_NAME, EDIT_PROD_PRICE, EDIT_PROD_DUR, EDIT_PROD_DESC, EDIT_PROD_INBOUND, EDIT_PROD_VOL) = range(58, 64)


async def admin_shop_nav(update: Update, context: ContextTypes.DEFAULT_TYPE, parent_id=None):
    query = update.callback_query

    async with AsyncSessionLocal() as session:
        # Fetch current category if parent_id exists
        current_cat = None
        if parent_id:
            res = await session.execute(select(Category).where(Category.id == parent_id))
            current_cat = res.scalars().first()
            if not current_cat:
                await query.answer("دسته‌بندی یافت نشد.", show_alert=True)
                return

        # Fetch sub-categories
        res = await session.execute(select(Category).where(Category.parent_id == parent_id))
        sub_cats = res.scalars().all()

        # Fetch products in this category
        products = []
        if parent_id:
            res = await session.execute(select(Product).where(Product.category_id == parent_id))
            products = res.scalars().all()

    text = f"🗂 **مدیریت فروشگاه**\n\n📌 موقعیت: {'خانه' if not current_cat else current_cat.name}\nانتخاب کنید:"
    keyboard = []

    for c in sub_cats:
        c_status = "🟢" if c.is_active else "🔴"
        keyboard.append([
            InlineKeyboardButton(f"📁 {c.name}", callback_data=f"adm_cat_{c.id}"),
            InlineKeyboardButton(c_status, callback_data=f"adm_tggl_c_{c.id}"),
            InlineKeyboardButton("🗑", callback_data=f"adm_delc_{c.id}")
        ])

    for p in products:
        p_status = "🟢" if p.is_active else "🔴"
        keyboard.append([InlineKeyboardButton(f"🛒 {p.name}", callback_data=f"adm_prod_{p.id}"), InlineKeyboardButton(
            p_status, callback_data=f"adm_tggl_p_{p.id}")])

    # Actions
    kb_actions = []
    kb_actions.append(InlineKeyboardButton("➕ زیردسته جدید",
                      callback_data=f"adm_addc_{parent_id or 0}"))
    if parent_id:
        kb_actions.append(InlineKeyboardButton(
            "➕ محصول جدید", callback_data=f"adm_addp_{parent_id}"))
    keyboard.append(kb_actions)

    if parent_id and current_cat.parent_id:
        keyboard.append([InlineKeyboardButton(
            "⬆️ بازگشت به پوشه بالاتر", callback_data=f"adm_cat_{current_cat.parent_id}")])
    elif parent_id:  # Go to root
        keyboard.append([InlineKeyboardButton(
            "⬆️ بازگشت به ریشه", callback_data=f"adm_cat_0")])

    keyboard.append([InlineKeyboardButton(
        "🔙 بازگشت به پنل اصلی مدیریت", callback_data="admin_panel")])

    try:
        if query:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except:
        pass


async def admin_shop_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "admin_shop":
        await admin_shop_nav(update, context, None)
    elif query.data.startswith("adm_cat_"):
        cid = int(query.data.split("_")[2])
        await admin_shop_nav(update, context, cid if cid > 0 else None)
    elif query.data.startswith("adm_delp_"):
        pid = int(query.data.split("_")[2])
        async with AsyncSessionLocal() as session:
            p = (await session.execute(select(Product).where(Product.id == pid))).scalars().first()
            if p:
                cat_id = p.category_id
                await session.delete(p)
                await session.commit()
                await admin_shop_nav(update, context, cat_id)
    elif query.data.startswith("adm_delc_"):
        cid = int(query.data.split("_")[2])
        async with AsyncSessionLocal() as session:
            cat = (await session.execute(select(Category).where(Category.id == cid))).scalars().first()
            if cat:
                parent = cat.parent_id
                # Delete all products in this category
                prods = (await session.execute(select(Product).where(Product.category_id == cid))).scalars().all()
                for p in prods:
                    await session.delete(p)
                # Delete all child categories and their products
                children = (await session.execute(select(Category).where(Category.parent_id == cid))).scalars().all()
                for child in children:
                    child_prods = (await session.execute(select(Product).where(Product.category_id == child.id))).scalars().all()
                    for cp in child_prods:
                        await session.delete(cp)
                    await session.delete(child)
                await session.delete(cat)
                await session.commit()
                await query.answer("دسته‌بندی و محتویاتش حذف شد!", show_alert=True)
                await admin_shop_nav(update, context, parent)
            else:
                await query.answer("یافت نشد.", show_alert=True)
    elif query.data.startswith("adm_tggl_"):
        # adm_tggl_c_ID or adm_tggl_p_ID
        parts = query.data.split("_")
        t_type = parts[2]
        t_id = int(parts[3])
        async with AsyncSessionLocal() as session:
            if t_type == "c":
                item = (await session.execute(select(Category).where(Category.id == t_id))).scalars().first()
                if item:
                    item.is_active = not item.is_active
            elif t_type == "p":
                item = (await session.execute(select(Product).where(Product.id == t_id))).scalars().first()
                if item:
                    item.is_active = not item.is_active
            await session.commit()

            # extract parent_id to jump back correctly
            parent_id = item.parent_id if t_type == "c" else item.category_id
            await admin_shop_nav(update, context, parent_id)

# --- Adding Categories ---


async def start_add_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = int(query.data.split("_")[2])
    context.user_data['temp_parent_id'] = pid if pid > 0 else None

    await query.edit_message_text("نام دسته‌بندی جدید را وارد کنید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_CAT_NAME


async def save_new_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text
    pid = context.user_data.get('temp_parent_id')
    async with AsyncSessionLocal() as session:
        session.add(Category(name=name, parent_id=pid))
        await session.commit()
    await update.message.reply_text("✅ با موفقیت ایجاد شد.")
    await admin_shop_nav(update, context, pid)
    return ConversationHandler.END

# --- Adding Products ---


async def start_add_prod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = int(query.data.split("_")[2])
    context.user_data['temp_prod_cat'] = pid
    keys = [
        [InlineKeyboardButton("✅ بله، ساخت اتوماتیک (V2RAY)", callback_data="v2r_yes")],
        [InlineKeyboardButton("❌ خیر، فروش عادی", callback_data="v2r_no")]
    ]
    await query.edit_message_text("آیا این محصول V2RAY است که بصورت اتوماتیک سرور ساخته شود؟", reply_markup=InlineKeyboardMarkup(keys))
    return WAIT_PROD_V2RAY

async def ask_prod_v2ray(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "v2r_yes":
        context.user_data['temp_prod_v2r'] = True
        await query.edit_message_text("حجم ترافیک سرور را به گیگابایت وارد کنید (0 = نامحدود):", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
        return WAIT_PROD_VOL
    else:
        context.user_data['temp_prod_v2r'] = False
        await query.edit_message_text("نام محصول را وارد کنید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
        return WAIT_PROD_NAME

async def save_prod_vol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    try:
        vol = float(val)
    except ValueError:
        await update.message.reply_text("فقط عدد مجاز است (0 = نامحدود):", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
        return WAIT_PROD_VOL
    context.user_data['temp_prod_vol'] = vol
    await update.message.reply_text("شماره Inbound ID پنل را وارد کنید (مثلا 1):", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_PROD_INBOUND

async def save_prod_inbound(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    if not val.isdigit():
        await update.message.reply_text("فقط عدد مجاز است. (مثلا 1):", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
        return WAIT_PROD_INBOUND
    context.user_data['temp_prod_inbound'] = int(val)
    await update.message.reply_text("نام محصول را وارد کنید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_PROD_NAME

async def save_prod_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_prod_name'] = update.message.text
    await update.message.reply_text("قیمت را (فقط عدد لاتین - تومان) وارد کنید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_PROD_PRICE

async def save_prod_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text.isdigit():
        await update.message.reply_text("فقط عدد مجاز است:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
        return WAIT_PROD_PRICE
    context.user_data['temp_prod_price'] = int(update.message.text)
    await update.message.reply_text("تعداد روز اعتبار زمان سرور (مثلا 30):", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_PROD_DUR

async def save_prod_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    if not val.isdigit():
        await update.message.reply_text("فقط عدد مجاز است. (مثلا 30):", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
        return WAIT_PROD_DUR
    context.user_data['temp_prod_dur'] = int(val)
    await update.message.reply_text("توضیحات تکمیلی یا متن تحویل سرویس به مشتری را وارد کنید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_PROD_DESC

async def save_prod_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text
    async with AsyncSessionLocal() as session:
        is_v2 = context.user_data.get('temp_prod_v2r', False)
        prod = Product(
            category_id=context.user_data['temp_prod_cat'],
            name=context.user_data['temp_prod_name'],
            price=context.user_data['temp_prod_price'],
            duration_days=context.user_data.get('temp_prod_dur', 30),
            description=desc,
            product_type="V2RAY" if is_v2 else "VPN",
            panel_id=context.user_data.get('temp_prod_inbound', None),
            volume_gb=context.user_data.get('temp_prod_vol', 0)
        )
        session.add(prod)
        await session.commit()
    await update.message.reply_text("✅ محصول افزوده شد.")
    await admin_shop_nav(update, context, context.user_data['temp_prod_cat'])
    return ConversationHandler.END


async def cancel_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    await admin_panel(update, context)
    return ConversationHandler.END

# --- Editing Products ---


async def admin_prod_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = int(query.data.split("_")[2])

    async with AsyncSessionLocal() as session:
        p = (await session.execute(select(Product).where(Product.id == pid))).scalars().first()
        if not p:
            await query.edit_message_text("محصول یافت نشد.")
            return ConversationHandler.END

    v2_label = ""
    if p.product_type == 'V2RAY':
        vol_txt = f"{p.volume_gb} GB" if p.volume_gb > 0 else "نامحدود"
        v2_label = f"\n🔌 نوع: V2RAY (اتوماتیک)\nInbound ID: {p.panel_id or 'تنظیم نشده'}\n📦 حجم: {vol_txt}"
    else:
        v2_label = "\n🔌 نوع: فروش عادی"
    
    text = f"📦 مدیریت محصول: {p.name}\n\nوضعیت: {'🟢 روشن' if p.is_active else '🔴 خاموش'}\nقیمت: {p.price:,.0f} تومان\nمدت اعتبار: {p.duration_days} روز{v2_label}\nتوضیحات: {p.description or 'ندارد'}\n\nجهت ویرایش انتخاب کنید:"
    keys = [
        [InlineKeyboardButton(
            f"وضعیت (تغییر): {'روشن✅' if p.is_active else 'خاموش❌'}", callback_data=f"adm_tggl_p_{p.id}")],
        [InlineKeyboardButton(
            "✏️ تغییر نام", callback_data=f"adm_editp_name_{p.id}")],
        [InlineKeyboardButton("✏️ تغییر قیمت", callback_data=f"adm_editp_price_{p.id}"), InlineKeyboardButton(
            "✏️ تغییر اعتبار زمانی", callback_data=f"adm_editp_dur_{p.id}")],
        [InlineKeyboardButton("✏️ تغییر توضیحات",
                              callback_data=f"adm_editp_desc_{p.id}")],
    ]
    if p.product_type == 'V2RAY':
        keys.append([InlineKeyboardButton("🔌 تغییر Inbound ID", callback_data=f"adm_editp_inb_{p.id}"),
                     InlineKeyboardButton("📦 تغییر حجم", callback_data=f"adm_editp_vol_{p.id}")])
    keys.append([InlineKeyboardButton(
            "🗑 حذف محصول", callback_data=f"adm_delp_{p.id}")])
    keys.append([InlineKeyboardButton("🔙 بازگشت به پوشه",
                              callback_data=f"adm_cat_{p.category_id}")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys))


async def start_edit_prod(update: Update, context: ContextTypes.DEFAULT_TYPE, prop: str):
    query = update.callback_query
    await query.answer()
    pid = int(query.data.split("_")[3])
    context.user_data['temp_edit_pid'] = pid

    msg_map = {"name": "نام جدید را وارد کنید:",
               "price": "قیمت جدید (تومان) را وارد کنید:", "dur": "اعتبار زمانی جدید (تعداد روز) را وارد کنید:", "desc": "توضیحات جدید را وارد کنید:", "inb": "شماره Inbound ID جدید را وارد کنید (فقط عدد):", "vol": "حجم جدید را به گیگابایت وارد کنید (0 = نامحدود):"}
    state_map = {"name": EDIT_PROD_NAME, "price": EDIT_PROD_PRICE,
                 "dur": EDIT_PROD_DUR, "desc": EDIT_PROD_DESC, "inb": EDIT_PROD_INBOUND, "vol": EDIT_PROD_VOL}

    await query.edit_message_text(msg_map[prop], reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return state_map[prop]


async def start_edit_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE): return await start_edit_prod(update, context, "name")


async def start_edit_price(
    update: Update, context: ContextTypes.DEFAULT_TYPE): return await start_edit_prod(update, context, "price")


async def start_edit_dur(
    update: Update, context: ContextTypes.DEFAULT_TYPE): return await start_edit_prod(update, context, "dur")


async def start_edit_desc(
    update: Update, context: ContextTypes.DEFAULT_TYPE): return await start_edit_prod(update, context, "desc")

async def start_edit_inbound(
    update: Update, context: ContextTypes.DEFAULT_TYPE): return await start_edit_prod(update, context, "inb")


async def save_edit_prop(update: Update, context: ContextTypes.DEFAULT_TYPE, prop: str):
    pid = context.user_data.get('temp_edit_pid')
    val = update.message.text
    if prop == "price" and not val.isdigit():
        await update.message.reply_text("فقط عدد مجاز است:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
        return EDIT_PROD_PRICE
    if prop == "dur":
        if not val.isdigit():
            await update.message.reply_text("فقط عدد مجاز است:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
            return EDIT_PROD_DUR

    async with AsyncSessionLocal() as session:
        p = (await session.execute(select(Product).where(Product.id == pid))).scalars().first()
        if p:
            if prop == "name":
                p.name = val
            elif prop == "price":
                p.price = int(val)
            elif prop == "dur":
                p.duration_days = int(val)
            elif prop == "desc":
                p.description = val
            elif prop == "inb":
                if not val.isdigit():
                    await update.message.reply_text("فقط عدد مجاز است:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
                    return EDIT_PROD_INBOUND
                p.panel_id = int(val)
            elif prop == "vol":
                try:
                    p.volume_gb = float(val)
                except ValueError:
                    await update.message.reply_text("فقط عدد مجاز است:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
                    return EDIT_PROD_VOL
            await session.commit()

    await update.message.reply_text("✅ با موفقیت ذخیره شد.")
    # Show prod menu again
    # Fake query to re-render menu isn't possible directly with message, so go to admin_shop_nav
    await admin_shop_nav(update, context, p.category_id)
    return ConversationHandler.END


async def save_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE): return await save_edit_prop(
    update, context, "name")


async def save_edit_price(update: Update, context: ContextTypes.DEFAULT_TYPE): return await save_edit_prop(
    update, context, "price")


async def save_edit_dur(update: Update, context: ContextTypes.DEFAULT_TYPE): return await save_edit_prop(
    update, context, "dur")


async def save_edit_desc(update: Update, context: ContextTypes.DEFAULT_TYPE): return await save_edit_prop(
    update, context, "desc")

async def save_edit_inbound(update: Update, context: ContextTypes.DEFAULT_TYPE): return await save_edit_prop(
    update, context, "inb")

async def start_edit_vol(
    update: Update, context: ContextTypes.DEFAULT_TYPE): return await start_edit_prod(update, context, "vol")

async def save_edit_vol(update: Update, context: ContextTypes.DEFAULT_TYPE): return await save_edit_prop(
    update, context, "vol")


def get_admin_shop_conv_handler():
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_add_cat, pattern="^adm_addc_"),
            CallbackQueryHandler(start_add_prod, pattern="^adm_addp_"),
            CallbackQueryHandler(start_edit_name, pattern="^adm_editp_name_"),
            CallbackQueryHandler(
                start_edit_price, pattern="^adm_editp_price_"),
            CallbackQueryHandler(start_edit_dur, pattern="^adm_editp_dur_"),
            CallbackQueryHandler(start_edit_desc, pattern="^adm_editp_desc_"),
            CallbackQueryHandler(start_edit_inbound, pattern="^adm_editp_inb_"),
            CallbackQueryHandler(start_edit_vol, pattern="^adm_editp_vol_")
        ],
        states={
            WAIT_CAT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_cat)],
            WAIT_PROD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_prod_name)],
            WAIT_PROD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_prod_price)],
            WAIT_PROD_DUR: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_prod_duration)],
            WAIT_PROD_V2RAY: [CallbackQueryHandler(ask_prod_v2ray, pattern="^v2r_")],
            WAIT_PROD_VOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_prod_vol)],
            WAIT_PROD_INBOUND: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_prod_inbound)],
            WAIT_PROD_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_prod_desc)],
            EDIT_PROD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_edit_name)],
            EDIT_PROD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_edit_price)],
            EDIT_PROD_DUR: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_edit_dur)],
            EDIT_PROD_DESC: [MessageHandler(
                filters.TEXT & ~filters.COMMAND, save_edit_desc)],
            EDIT_PROD_INBOUND: [MessageHandler(
                filters.TEXT & ~filters.COMMAND, save_edit_inbound)],
            EDIT_PROD_VOL: [MessageHandler(
                filters.TEXT & ~filters.COMMAND, save_edit_vol)]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_shop),
            CallbackQueryHandler(cancel_shop, pattern="^admin_cancel$")
        ]
    )


def get_admin_shop_routers():
    return [
        CallbackQueryHandler(
            admin_shop_callbacks, pattern="^(admin_shop|adm_cat_|adm_delp_|adm_delc_|adm_tggl_)"),
        CallbackQueryHandler(admin_prod_menu, pattern="^adm_prod_")
    ]
