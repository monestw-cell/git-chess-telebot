"""Multi-language support module."""

from bot.database import get_user_config

# Translation dictionaries
TRANSLATIONS = {
    'ar': {
        # Menu
        'main_menu_title': '\U0001f916 مدير المشاريع السحابي',
        'connected': 'متصل: {username}',
        'not_connected': 'غير متصل بـ GitHub',
        'choose_option': 'اختر من القائمة:',
        'my_projects': '📁 مشاريعي',
        'new_project': '➕ مشروع جديد',
        'statistics': '📊 إحصائيات',
        'chess_analysis': '♟️ تحليل شطرنج',
        'settings': '⚙️ الإعدادات',
        'help': '❓ مساعدة',
        'gists': '📝 Gists',
        'notifications': '🔔 الإشعارات',
        'bot_status': '📈 حالة البوت',
        'home': '🏠 الرئيسية',
        'back': '🔙 رجوع',
        'cancel': '🚫 إلغاء',

        # Settings
        'settings_menu': '⚙️ الإعدادات:',
        'language_setting': '🌐 اللغة',
        'chess_depth_setting': '♟️ عمق التحليل',
        'github_setup': '🔑 إعداد GitHub',
        'current_language': 'اللغة الحالية: العربية',
        'current_depth': 'عمق التحليل: {depth}',
        'select_language': 'اختر اللغة:',
        'select_depth': 'اختر عمق التحليل:',
        'depth_info': 'عمق أعلى = تحليل أدق لكن أبطأ',
        'language_changed': '✅ تم تغيير اللغة',
        'depth_changed': '✅ تم تغيير عمق التحليل إلى {depth}',

        # Common
        'error': '❌ خطأ: {msg}',
        'setup_first': '⚠️ يرجى ضبط الإعدادات أولاً.',
        'loading': '⏳ جاري التحميل...',
        'success': '✅ تم بنجاح!',
        'confirm_delete': '⚠️ هل أنت متأكد؟',
        'yes_delete': '✅ نعم، احذف',
        'no_cancel': '🚫 إلغاء',

        # Chess
        'chess_prompt': '♟️ تحليل الشطرنج\n\nالصق نص الـ PGN هنا:',
        'chess_analyzing': '⏳ جاري تحليل مباراة:\n⚪ {white} vs ⚫ {black}...',
        'chess_invalid_pgn': '❌ PGN غير صالح.',
        'chess_report_title': '♟️ التقرير النهائي',
        'chess_notable_moments': '🎯 أبرز اللحظات:',

        # GitHub
        'repos_title': '📁 مشاريعك ({count} مستودع) - مرتبة حسب آخر تحديث:',
        'repo_empty': '📂 المستودع {name} فارغ.\nارفع ملفات عبر ZIP لتهيئته.',
        'upload_zip': '📤 رفع ZIP',
        'replace_file': '🔄 استبدال ملف',
        'workflows': '⚡ Workflows',
        'files': '📄 الملفات',
        'branches': '🌿 الفروع',
        'issues': '🐛 القضايا',
        'pull_requests': '🔀 PR',
        'actions': '⚡ Actions',
        'more_tools': '📦 المزيد...',
        'repo_settings': '⚙️ إعدادات',
        'delete_repo': '🗑️ حذف',
        'open_github': '🌐 فتح في GitHub',
    },
    'en': {
        # Menu
        'main_menu_title': '\U0001f916 Cloud Project Manager',
        'connected': 'Connected: {username}',
        'not_connected': 'Not connected to GitHub',
        'choose_option': 'Choose an option:',
        'my_projects': '📁 My Projects',
        'new_project': '➕ New Project',
        'statistics': '📊 Statistics',
        'chess_analysis': '♟️ Chess Analysis',
        'settings': '⚙️ Settings',
        'help': '❓ Help',
        'gists': '📝 Gists',
        'notifications': '🔔 Notifications',
        'bot_status': '📈 Bot Status',
        'home': '🏠 Home',
        'back': '🔙 Back',
        'cancel': '🚫 Cancel',

        # Settings
        'settings_menu': '⚙️ Settings:',
        'language_setting': '🌐 Language',
        'chess_depth_setting': '♟️ Analysis Depth',
        'github_setup': '🔑 GitHub Setup',
        'current_language': 'Current language: English',
        'current_depth': 'Analysis depth: {depth}',
        'select_language': 'Select language:',
        'select_depth': 'Select analysis depth:',
        'depth_info': 'Higher depth = more accurate but slower',
        'language_changed': '✅ Language changed',
        'depth_changed': '✅ Analysis depth changed to {depth}',

        # Common
        'error': '❌ Error: {msg}',
        'setup_first': '⚠️ Please set up GitHub first.',
        'loading': '⏳ Loading...',
        'success': '✅ Success!',
        'confirm_delete': '⚠️ Are you sure?',
        'yes_delete': '✅ Yes, delete',
        'no_cancel': '🚫 Cancel',

        # Chess
        'chess_prompt': '♟️ Chess Analysis\n\nPaste your PGN here:',
        'chess_analyzing': '⏳ Analyzing game:\n⚪ {white} vs ⚫ {black}...',
        'chess_invalid_pgn': '❌ Invalid PGN.',
        'chess_report_title': '♟️ Final Report',
        'chess_notable_moments': '🎯 Notable Moments:',

        # GitHub
        'repos_title': '📁 Your repos ({count}) - sorted by last update:',
        'repo_empty': '📂 Repository {name} is empty.\nUpload files via ZIP.',
        'upload_zip': '📤 Upload ZIP',
        'replace_file': '🔄 Replace File',
        'workflows': '⚡ Workflows',
        'files': '📄 Files',
        'branches': '🌿 Branches',
        'issues': '🐛 Issues',
        'pull_requests': '🔀 PRs',
        'actions': '⚡ Actions',
        'more_tools': '📦 More...',
        'repo_settings': '⚙️ Settings',
        'delete_repo': '🗑️ Delete',
        'open_github': '🌐 Open in GitHub',
    }
}


def get_text(chat_id, key, **kwargs):
    """Get translated text for a user based on their language preference.

    Args:
        chat_id: User's chat ID
        key: Translation key
        **kwargs: Format arguments for the string

    Returns:
        Translated and formatted string
    """
    config = get_user_config(chat_id)
    lang = 'ar'  # default
    if config and config.get('language'):
        lang = config['language']

    translations = TRANSLATIONS.get(lang, TRANSLATIONS['ar'])
    text = translations.get(key, TRANSLATIONS['ar'].get(key, key))

    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


def get_lang(chat_id):
    """Get user's language code."""
    config = get_user_config(chat_id)
    if config and config.get('language'):
        return config['language']
    return 'ar'
