from typing import Dict, Any

LANGUAGES = {
    "en": {"name": "English", "flag": "🇬🇧", "native": "English"},
    "fa": {"name": "Persian (Iran)", "flag": "🇮🇷", "native": "فارسی"},
    "ar": {"name": "Arabic (Palestine)", "flag": "🇵🇸", "native": "العربية"},
    "ur": {"name": "Urdu (Pakistan)", "flag": "🇵🇰", "native": "اردو"},
    "bn": {"name": "Bengali (Bangladesh)", "flag": "🇧🇩", "native": "বাংলা"},
}

TEXTS: Dict[str, Dict[str, str]] = {
    # Buttons
    "btn_shop": {
        "en": "🛒 Shop",
        "fa": "🛒 فروشگاه",
        "ar": "🛒 المتجر",
        "ur": "🛒 شاپ",
        "bn": "🛒 শপ",
    },
    "btn_topup": {
        "en": "💼 Top Up",
        "fa": "💼 افزایش موجودی",
        "ar": "💼 شحن الرصيد",
        "ur": "💼 ٹاپ اپ",
        "bn": "💼 টপ আপ",
    },
    "btn_orders": {
        "en": "📋 My Orders",
        "fa": "📋 سفارشات من",
        "ar": "📋 طلباتي",
        "ur": "📋 میرے آرڈرز",
        "bn": "📋 আমার অর্ডার",
    },
    "btn_support": {
        "en": "💬 Support",
        "fa": "💬 پشتیبانی",
        "ar": "💬 الدعم",
        "ur": "💬 سپورٹ",
        "bn": "💬 সাপোর্ট",
    },
    "btn_profile": {
        "en": "👤 Profile",
        "fa": "👤 پروفایل",
        "ar": "👤 الملف الشخصي",
        "ur": "👤 پروفائل",
        "bn": "👤 প্রোফাইল",
    },
    "btn_language": {
        "en": "🌐 Language",
        "fa": "🌐 زبان (Language)",
        "ar": "🌐 اللغة (Language)",
        "ur": "🌐 زبان (Language)",
        "bn": "🌐 ভাষা (Language)",
    },
    "btn_admin": {
        "en": "⚙️ Admin Panel",
        "fa": "⚙️ پنل مدیریت",
        "ar": "⚙️ لوحة الإدارة",
        "ur": "⚙️ ایڈمن پینل",
        "bn": "⚙️ অ্যাডমিন প্যানেল",
    },
    "btn_assistant": {
        "en": "📦 Assistant Stock Panel",
        "fa": "📦 پنل دستیار",
        "ar": "📦 لوحة المساعد",
        "ur": "📦 اسسٹنٹ پینل",
        "bn": "📦 অ্যাসিস্ট্যান্ট প্যানেল",
    },
    "btn_back_main": {
        "en": "🔙 Back to Main Menu",
        "fa": "🔙 بازگشت به منوی اصلی",
        "ar": "🔙 العودة للقائمة الرئيسية",
        "ur": "🔙 مین مینو میں واپس",
        "bn": "🔙 মেইন মেনু",
    },
    "btn_buy_now": {
        "en": "🛒 Buy Now",
        "fa": "🛒 خرید فوری",
        "ar": "🛒 اشتري الآن",
        "ur": "🛒 ابھی خریدیں",
        "bn": "🛒 এখনই কিনুন",
    },
    "btn_back_catalog": {
        "en": "🔙 Back to Catalog",
        "fa": "🔙 بازگشت به کاتالوگ",
        "ar": "🔙 العودة للمتجر",
        "ur": "🔙 کیٹلاگ میں واپس",
        "bn": "🔙 ক্যাটালগে ফিরে যান",
    },
    "btn_deposit_funds": {
        "en": "💰 Deposit Funds",
        "fa": "💰 افزایش موجودی",
        "ar": "💰 إيداع الرصيد",
        "ur": "💰 بیلنس جمع کریں",
        "bn": "💰 ডিপোজিট করুন",
    },
    "btn_order_history": {
        "en": "📜 Order History",
        "fa": "📜 تاریخچه سفارشات",
        "ar": "📜 سجل الطلبات",
        "ur": "📜 آرڈر ہسٹری",
        "bn": "📜 অর্ডার হিস্টোরি",
    },
    "btn_refresh": {
        "en": "🔄 Refresh",
        "fa": "🔄 بروزرسانی",
        "ar": "🔄 تحديث",
        "ur": "🔄 ریفریش",
        "bn": "🔄 রিফ্রেশ",
    },
    "btn_cancel": {
        "en": "❌ Cancel",
        "fa": "❌ انصراف",
        "ar": "❌ إلغاء",
        "ur": "❌ منسوخ",
        "bn": "❌ বাতিল",
    },

    # Messages
    "welcome": {
        "en": "👋 *Hello {name}! Welcome to Digital Shop Bot.*\n\n💳 *Your Balance:* `${balance:.2f}` USD\n\n🛍️ Browse top-grade digital products with *instant automated delivery*.\n\nSelect an option from the menu below to get started:",
        "fa": "👋 *سلام {name}! به ربات فروشگاه دیجیتال خوش آمدید.*\n\n💳 *موجودی شما:* `${balance:.2f}` USD\n\n🛍️ محصولات دیجیتال باکیفیت با *تحویل آنی و خودکار*.\n\nلطفاً یک گزینه از منوی زیر انتخاب کنید:",
        "ar": "👋 *أهلاً بك {name}! مرحباً بك في متجرنا الرقمي.*\n\n💳 *رصيدك الحالي:* `${balance:.2f}` USD\n\n🛍️ تصفح أفضل المنتجات الرقمية مع *تسليم فوري وتلقائي*.\n\nاختر خياراً من القائمة أدناه للبدء:",
        "ur": "👋 *ہیلو {name}! ڈیجیٹل شاپ بوٹ میں خوش آمدید.*\n\n💳 *آپ کا بیلنس:* `${balance:.2f}` USD\n\n🛍️ *فوری خودکار ترسیل* کے ساتھ اعلیٰ معیار کی ڈیجیٹل پروڈکٹس دیکھیں۔\n\nشروع کرنے کے لیے نیچے دیے گئے مینو میں سے ایک آپشن منتخب کریں:",
        "bn": "👋 *হ্যালো {name}! ডিজিটাল শপ বটে আপনাকে স্বাগতম.*\n\n💳 *আপনার ব্যালেন্স:* `${balance:.2f}` USD\n\n🛍️ *তাৎক্ষণিক অটোমেটেড ডেলিভারি* সহ প্রিমিয়াম ডিজিটাল প্রোডাক্ট কিনুন।\n\nশুরু করতে নিচের যেকোনো অপশন বেছে নিন:",
    },

    "profile": {
        "en": "👤 *My Account Profile*\n\n🆔 *Telegram ID:* `{user_id}`\n👤 *Name:* {name}\n💳 *Available Balance:* `${balance:.2f}` USD\n🛍️ *Total Orders Placed:* `{total_orders}`\n💵 *Total Spent:* `${total_spent:.2f}` USD",
        "fa": "👤 *پروفایل کاربری من*\n\n🆔 *شناسه تلگرام:* `{user_id}`\n👤 *نام:* {name}\n💳 *موجودی کیف پول:* `${balance:.2f}` USD\n🛍️ *تعداد کل سفارشات:* `{total_orders}`\n💵 *مجموع خرید:* `${total_spent:.2f}` USD",
        "ar": "👤 *الملف الشخصي*\n\n🆔 *معرف التلغرام:* `{user_id}`\n👤 *الاسم:* {name}\n💳 *الرصيد المتاح:* `${balance:.2f}` USD\n🛍️ *إجمالي الطلبات:* `{total_orders}`\n💵 *إجمالي المنفق:* `${total_spent:.2f}` USD",
        "ur": "👤 *میرا اکاؤنٹ پروفائل*\n\n🆔 *ٹیلیگرام آئی ڈی:* `{user_id}`\n👤 *نام:* {name}\n💳 *دستیاب بیلنس:* `${balance:.2f}` USD\n🛍️ *کل آرڈرز:* `{total_orders}`\n💵 *کل خرچ:* `${total_spent:.2f}` USD",
        "bn": "👤 *আমার অ্যাকাউন্ট প্রোফাইল*\n\n🆔 *টেলিগ্রাম আইডি:* `{user_id}`\n👤 *নাম:* {name}\n💳 *বর্তমান ব্যালেন্স:* `${balance:.2f}` USD\n🛍️ *মোট সম্পন্ন অর্ডার:* `{total_orders}`\n💵 *মোট খরচ:* `${total_spent:.2f}` USD",
    },

    "support": {
        "en": "💬 *Customer Support*\n\nNeed help with an order or have questions? Our support team is here to assist you 24/7.\n\nClick below to message support directly:",
        "fa": "💬 *پشتیبانی مشتریان*\n\nنیاز به راهنمایی در مورد سفارش یا سؤالی دارید؟ تیم پشتیبانی ما ۲۴/۷ آماده پاسخگویی است.\n\nبرای ارتباط با پشتیبانی روی دکمه زیر کلیک کنید:",
        "ar": "💬 *خدمة العملاء والدعم*\n\nهل تحتاج إلى مساعدة بخصوص طلبك؟ فريق الدعم متواجد لخدمتك على مدار الساعة.\n\nاضغط على الزر أدناه للتواصل مع الدعم مباشرة:",
        "ur": "💬 *کسٹمر سپورٹ*\n\nکیا آپ کو اپنے آرڈر کے بارے میں مدد کی ضرورت ہے؟ ہماری سپورٹ ٹیم 24/7 دستیاب ہے۔\n\nبراہ راست رابطہ کرنے کے لیے نیچے کلک کریں:",
        "bn": "💬 *কাস্টমার সাপোর্ট*\n\nআপনার অর্ডার বা ব্যালেন্স সংক্রান্ত যেকোনো প্রয়োজনে আমাদের সাপোর্ট টিম ২৪/৭ প্রস্তুত রয়েছে।\n\nসরাসরি অ্যাডমিনের সাথে যোগাযোগ করতে নিচের বাটনে চাপুন:",
    },

    "deposit_menu": {
        "en": "💳 *Deposit Funds*\n\n💰 *Your Bot Balance:* `${balance:.2f}` USD\n\nSelect the amount you want to deposit (USDT):",
        "fa": "💳 *افزایش موجودی*\n\n💰 *موجودی شما:* `${balance:.2f}` USD\n\nمبلغ مورد نظر برای شارژ حساب را انتخاب کنید (USDT):",
        "ar": "💳 *شحن الرصيد*\n\n💰 *رصيدك الحالي:* `${balance:.2f}` USD\n\nحدد المبلغ الذي تريد إيداعه (USDT):",
        "ur": "💳 *بیلنس جمع کریں*\n\n💰 *آپ کا بیلنس:* `${balance:.2f}` USD\n\nوہ رقم منتخب کریں جو آپ جمع کرنا چاہتے ہیں (USDT):",
        "bn": "💳 *ব্যালেন্স ডিপোজিট*\n\n💰 *আপনার বর্তমান ব্যালেন্স:* `${balance:.2f}` USD\n\nডিপোজিট করার পরিমাণ নির্বাচন করুন (USDT):",
    },

    "catalog_title": {
        "en": "🛒 *Available Products (Page {current_page}/{total_pages})*\n\n📊 *Total In-Stock Items:* `{total_products}` products\nSelect a product below to view details and purchase:",
        "fa": "🛒 *محصولات موجود (صفحه {current_page}/{total_pages})*\n\n📊 *تعداد کل محصولات موجود:* `{total_products}` محصول\nبرای مشاهده جزئیات و خرید، یک محصول را انتخاب کنید:",
        "ar": "🛒 *المنتجات المتاحة (صفحة {current_page}/{total_pages})*\n\n📊 *إجمالي المنتجات المتوفرة:* `{total_products}` منتج\nاختر منتجاً أدناه لعرض التفاصيل والشراء:",
        "ur": "🛒 *دستیاب پروڈکٹس (صفحہ {current_page}/{total_pages})*\n\n📊 *دستیاب آئٹمز:* `{total_products}` پروڈکٹس\nتفصیلات دیکھنے اور خریدنے کے لیے پروڈکٹ منتخب کریں:",
        "bn": "🛒 *উপলব্ধ ডিজিটাল প্রোডাক্ট (পৃষ্ঠা {current_page}/{total_pages})*\n\n📊 *স্টকে আছে:* `{total_products}` টি প্রোডাক্ট\nবিস্তারিত দেখতে ও কিনতে নিচে পছন্দসই প্রোডাক্টে ক্লিক করুন:",
    },

    "lang_select_title": {
        "en": "🌐 *Choose Your Preferred Language*\n\nPlease select your preferred language below:\n(All bot interfaces and buttons will update immediately)",
        "fa": "🌐 *زبان مورد نظر خود را انتخاب کنید*\n\nلطفاً زبان مورد نظر خود را انتخاب کنید:\n(تمامی منوها بلافاصله بروزرسانی می‌شوند)",
        "ar": "🌐 *اختر لغتك المفضلة*\n\nيرجى تحديد لغتك المفضلة أدناه:\n(سيتم تحديث القوائم والأزرار فوراً)",
        "ur": "🌐 *اپنی پسندیدہ زبان منتخب کریں*\n\nبراہ کرم نیچے دی گئی زبانوں میں سے ایک منتخب کریں:\n(تمام مینو فوری طور پر تبدیل ہو جائیں گے)",
        "bn": "🌐 *আপনার পছন্দের ভাষা নির্বাচন করুন*\n\nনিচের তালিকা থেকে যেকোনো একটি ভাষা বেছে নিন:\n(বটের ইন্টারফেস অবিলম্বে নির্বাচিত ভাষায় পরিবর্তন হবে)",
    },

    "lang_changed": {
        "en": "✅ Language set to English successfully!",
        "fa": "✅ زبان با موفقیت به فارسی تغییر یافت!",
        "ar": "✅ تم تغيير اللغة إلى العربية بنجاح!",
        "ur": "✅ زبان کامیابی سے اردو میں تبدیل ہو گئی!",
        "bn": "✅ সফলভাবে বাংলা ভাষা সেট করা হয়েছে!",
    }
}

def t(key: str, lang: str = "en", **kwargs) -> str:
    """Retrieve translated string with fallback to English."""
    lang_code = lang if lang in LANGUAGES else "en"
    tpl = TEXTS.get(key, {}).get(lang_code) or TEXTS.get(key, {}).get("en") or key
    if kwargs:
        try:
            return tpl.format(**kwargs)
        except Exception:
            return tpl
    return tpl
