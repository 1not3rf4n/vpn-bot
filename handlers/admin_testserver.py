from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters
from sqlalchemy.future import select
from database.models import AsyncSessionLocal, TestServerTemplate
from core.settings import get_setting, set_setting
from handlers.admin import push_admin_view
from datetime import datetime

# Local states
(WAIT_TPL_NAME, WAIT_TPL_VOL, WAIT_TPL_DUR, WAIT_TPL_INB,
 WAIT_DEF_BASE, WAIT_DEF_VOL, WAIT_DEF_DUR, WAIT_DEF_INB) = range(10, 18)

CANCEL_BTN = [[InlineKeyboardButton("🔙 انصراف و بازگشت", callback_data="admin_settings_menu")]]

async def test_server_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query: await query.answer()
    # push this view onto admin navigation stack
    push_admin_view(context, 'admin_settings_menu')
    text = "🧪 <b>مدیریت سرور تست</b>\nلطفاً یکی از موارد را انتخاب کنید:"
    keys = [
        [InlineKeyboardButton("🗂 مدیریت قالب‌ها", callback_data="testtpl_manage")],
        [InlineKeyboardButton("⚙️ ویرایش پیش‌فرض‌ها", callback_data="testtpl_defaults")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_settings_menu")]
    ]
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")
    except:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")

async def testtpl_manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # push this view onto admin navigation stack
    push_admin_view(context, 'test_server_menu')
    async with AsyncSessionLocal() as session:
        tpls = (await session.execute(select(TestServerTemplate).order_by(TestServerTemplate.id))).scalars().all()
    text = "🗃️ <b>قالب‌های سرور تست</b>\n\n"
    keys = []
    if not tpls:
        text += "هیچ قالبی تعریف نشده است."
    for t in tpls:
        text += f"🔹 {t.name_template} | حجم: {t.volume_gb}GB | {t.duration_days}روز | Inbound:{t.inbound_id}\n"
        keys.append([InlineKeyboardButton("✏️ ویرایش", callback_data=f"testtpl_edit_{t.id}"), InlineKeyboardButton("🗑 حذف", callback_data=f"testtpl_del_{t.id}")])
    keys.append([InlineKeyboardButton("➕ افزودن قالب جدید", callback_data="testtpl_add")])
    keys.append([InlineKeyboardButton("🔙 بازگشت", callback_data="test_server_menu")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")

async def testtpl_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "testtpl_add":
        context.user_data['tmp_tpl_flow'] = {}
        await query.edit_message_text("نام قالب جدید را وارد کنید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
        return WAIT_TPL_NAME
    if data.startswith("testtpl_edit_"):
        tid = int(data.split("_")[2])
        # Start edit flow by asking which field to edit
        keys = [
            [InlineKeyboardButton("✏️ ویرایش نام", callback_data=f"testtpl_editfield_{tid}_name")],
            [InlineKeyboardButton("✏️ ویرایش حجم", callback_data=f"testtpl_editfield_{tid}_vol")],
            [InlineKeyboardButton("✏️ ویرایش مدت", callback_data=f"testtpl_editfield_{tid}_dur")],
            [InlineKeyboardButton("✏️ ویرایش Inbound", callback_data=f"testtpl_editfield_{tid}_inb")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="testtpl_manage")]
        ]
        await query.edit_message_text("یک مورد برای ویرایش انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keys))
        return
    if data.startswith("testtpl_editfield_"):
        parts = data.split("_")
        tid = int(parts[2])
        field = parts[3]
        context.user_data['edit_tpl_id'] = tid
        if field == 'name':
            await query.edit_message_text("نام جدید را وارد کنید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
            return WAIT_TPL_NAME
        if field == 'vol':
            await query.edit_message_text("حجم جدید (GB) را وارد کنید (0 = نامحدود):", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
            return WAIT_TPL_VOL
        if field == 'dur':
            await query.edit_message_text("مدت جدید (تعداد روز) را وارد کنید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
            return WAIT_TPL_DUR
        if field == 'inb':
            await query.edit_message_text("شماره Inbound جدید را وارد کنید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
            return WAIT_TPL_INB
    if data.startswith("testtpl_del_"):
        tid = int(data.split("_")[2])
        async with AsyncSessionLocal() as session:
            tpl = (await session.execute(select(TestServerTemplate).where(TestServerTemplate.id == tid))).scalars().first()
            if tpl:
                await session.delete(tpl)
                await session.commit()
        await testtpl_manage(update, context)
        return

# Add template flow saves
async def save_tpl_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("نام معتبر نیست. دوباره وارد کنید:")
        return WAIT_TPL_NAME
    # If editing specific template
    edit_id = context.user_data.get('edit_tpl_id')
    if edit_id:
        async with AsyncSessionLocal() as session:
            tpl = (await session.execute(select(TestServerTemplate).where(TestServerTemplate.id == edit_id))).scalars().first()
            if tpl:
                tpl.name_template = text
                await session.commit()
        await update.message.reply_text("✅ نام قالب ذخیره شد.")
        context.user_data.pop('edit_tpl_id', None)
        return ConversationHandler.END

    # else it's part of create flow
    context.user_data['tmp_tpl_flow']['name'] = text
    await update.message.reply_text("حجم ترافیک (گیگابایت) برای این قالب را وارد کنید (0 = نامحدود):", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_TPL_VOL

async def save_tpl_vol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = (update.message.text or "").strip()
    try:
        vol = float(val)
    except:
        await update.message.reply_text("لطفاً عدد معتبر وارد کنید:")
        return WAIT_TPL_VOL
    if 'edit_tpl_id' in context.user_data:
        async with AsyncSessionLocal() as session:
            tpl = (await session.execute(select(TestServerTemplate).where(TestServerTemplate.id == context.user_data['edit_tpl_id']))).scalars().first()
            if tpl:
                tpl.volume_gb = vol
                await session.commit()
        context.user_data.pop('edit_tpl_id', None)
        await update.message.reply_text("✅ حجم ذخیره شد.")
        return ConversationHandler.END

    context.user_data['tmp_tpl_flow']['vol'] = vol
    await update.message.reply_text("مدت اعتبار (تعداد روز) برای این قالب را وارد کنید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_TPL_DUR

async def save_tpl_dur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = (update.message.text or "").strip()
    if not val.isdigit():
        await update.message.reply_text("لطفاً تعداد روز به صورت عدد وارد کنید:")
        return WAIT_TPL_DUR
    days = int(val)
    if 'edit_tpl_id' in context.user_data:
        async with AsyncSessionLocal() as session:
            tpl = (await session.execute(select(TestServerTemplate).where(TestServerTemplate.id == context.user_data['edit_tpl_id']))).scalars().first()
            if tpl:
                tpl.duration_days = days
                await session.commit()
        context.user_data.pop('edit_tpl_id', None)
        await update.message.reply_text("✅ مدت ذخیره شد.")
        return ConversationHandler.END

    context.user_data['tmp_tpl_flow']['dur'] = days
    await update.message.reply_text("شماره Inbound ID پنل را وارد کنید (مثلاً 1):", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_TPL_INB

async def save_tpl_inb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = (update.message.text or "").strip()
    if not val.isdigit():
        await update.message.reply_text("لطفاً فقط عدد وارد کنید:")
        return WAIT_TPL_INB
    inb = int(val)
    tmp = context.user_data.get('tmp_tpl_flow', {})
    name = tmp.get('name')
    vol = tmp.get('vol', 0)
    dur = tmp.get('dur', 1)
    async with AsyncSessionLocal() as session:
        tpl = TestServerTemplate(name_template=name, volume_gb=vol, duration_days=dur, inbound_id=inb)
        session.add(tpl)
        await session.commit()
    await update.message.reply_text("✅ قالب جدید اضافه شد.")
    context.user_data.pop('tmp_tpl_flow', None)
    return ConversationHandler.END

# Defaults menu
async def testtpl_defaults(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    base = await get_setting('test_server_base_name', 'test')
    vol = await get_setting('test_server_volume_gb', '1')
    dur = await get_setting('test_server_duration_days', '1')
    inb = await get_setting('test_server_inbound_id', '1')

    text = f"⚙️ <b>پیش‌فرض‌های سرور تست</b>\n\nنام پایه: <code>{base}</code>\nحجم (GB): <code>{vol}</code>\nمدت (روز): <code>{dur}</code>\nInbound ID: <code>{inb}</code>\n\nجهت تغییر هر مورد، گزینه آن را انتخاب کنید:"
    keys = [
        [InlineKeyboardButton("✏️ نام پایه", callback_data="testtpl_def_edit_base")],
        [InlineKeyboardButton("✏️ حجم پیش‌فرض", callback_data="testtpl_def_edit_vol")],
        [InlineKeyboardButton("✏️ مدت پیش‌فرض", callback_data="testtpl_def_edit_dur")],
        [InlineKeyboardButton("✏️ Inbound پیش‌فرض", callback_data="testtpl_def_edit_inb")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="test_server_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")

async def testtpl_def_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # ensure back returns to defaults menu
    push_admin_view(context, 'testtpl_defaults')
    if query.data == 'testtpl_def_edit_base':
        await query.edit_message_text('لطفاً نام پایه جدید را وارد کنید:', reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
        return WAIT_DEF_BASE
    if query.data == 'testtpl_def_edit_vol':
        await query.edit_message_text('حجم پیش‌فرض جدید را وارد کنید (GB):', reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
        return WAIT_DEF_VOL
    if query.data == 'testtpl_def_edit_dur':
        await query.edit_message_text('مدت پیش‌فرض جدید را وارد کنید (روز):', reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
        return WAIT_DEF_DUR
    if query.data == 'testtpl_def_edit_inb':
        await query.edit_message_text('Inbound ID پیش‌فرض را وارد کنید (عدد):', reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
        return WAIT_DEF_INB

async def save_def_base(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = (update.message.text or '').strip()
    if not val:
        await update.message.reply_text('نام نامعتبر است.')
        return WAIT_DEF_BASE
    await set_setting('test_server_base_name', val)
    await update.message.reply_text('✅ نام پایه ذخیره شد.')
    return ConversationHandler.END

async def save_def_vol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = (update.message.text or '').strip()
    try:
        float(val)
    except:
        await update.message.reply_text('لطفاً عدد معتبر وارد کنید:')
        return WAIT_DEF_VOL
    await set_setting('test_server_volume_gb', val)
    await update.message.reply_text('✅ حجم پیش‌فرض ذخیره شد.')
    return ConversationHandler.END

async def save_def_dur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = (update.message.text or '').strip()
    if not val.isdigit():
        await update.message.reply_text('لطفاً عدد وارد کنید:')
        return WAIT_DEF_DUR
    await set_setting('test_server_duration_days', val)
    await update.message.reply_text('✅ مدت پیش‌فرض ذخیره شد.')
    return ConversationHandler.END

async def save_def_inb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = (update.message.text or '').strip()
    if not val.isdigit():
        await update.message.reply_text('لطفاً عدد وارد کنید:')
        return WAIT_DEF_INB
    await set_setting('test_server_inbound_id', val)
    await update.message.reply_text('✅ Inbound پیش‌فرض ذخیره شد.')
    return ConversationHandler.END


def get_admin_testserver_conv_handler():
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(lambda u, c: None, pattern="^test_server_menu$"),
            CallbackQueryHandler(testtpl_callbacks, pattern="^testtpl_"),
            CallbackQueryHandler(testtpl_def_callbacks, pattern="^testtpl_def_"),
            CallbackQueryHandler(lambda u, c: None, pattern="^testtpl_manage$"),
            CallbackQueryHandler(lambda u, c: None, pattern="^testtpl_defaults$")
        ],
        states={
            WAIT_TPL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_tpl_name)],
            WAIT_TPL_VOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_tpl_vol)],
            WAIT_TPL_DUR: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_tpl_dur)],
            WAIT_TPL_INB: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_tpl_inb)],
            WAIT_DEF_BASE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_def_base)],
            WAIT_DEF_VOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_def_vol)],
            WAIT_DEF_DUR: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_def_dur)],
            WAIT_DEF_INB: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_def_inb)],
        },
        fallbacks=[],
        allow_reentry=True
    )


def get_admin_testserver_routers():
    return [
        CallbackQueryHandler(test_server_menu, pattern="^test_server_menu$"),
        CallbackQueryHandler(testtpl_manage, pattern="^testtpl_manage$"),
        CallbackQueryHandler(testtpl_defaults, pattern="^testtpl_defaults$"),
        CallbackQueryHandler(testtpl_callbacks, pattern="^testtpl_"),
        CallbackQueryHandler(testtpl_def_callbacks, pattern="^testtpl_def_"),
    ]
