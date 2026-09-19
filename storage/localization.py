"""Runtime English/Bangla localization used by Pycam UI.

All keys intentionally have both English and Bangla values.  Unknown keys fall
back to English/default instead of showing a blank control.
"""

TRANSLATIONS = {
    "en": {
        "home":"Home","files":"Files","tools":"Tools","settings":"Settings",
        "run":"RUN","cancel":"CANCEL","save":"SAVE","close":"CLOSE","ok":"OK","choose":"CHOOSE","reset":"RESET",
        "copy":"COPY","share":"SHARE","done":"Done","processing":"Processing…","cancelled":"Cancelled",
        "scan":"Scan","convert":"Convert","edit":"Edit","utilities":"Utilities",
        "search":"Search","search_documents":"Search documents","discard":"DISCARD","resume":"RESUME","no_documents":"No documents yet",
        "scan_first_page":"Tap the camera button to scan your first page","scans_show_here":"Scanned documents will show up here",
        "all":"ALL","favorites":"FAVORITES","folders":"FOLDERS","trash":"TRASH","filter":"FILTER","bulk":"BULK",
        "document":"document","documents":"documents","storage":"Storage","storage_unavailable":"Storage unavailable",
        "unfinished_scan":"Unfinished scan","page":"page","pages":"pages",
        "tool_id_cards":"ID Cards","tool_nid_ocr":"NID OCR","tool_passport_mrz":"Passport MRZ","tool_extract_text":"Extract Text",
        "tool_passport_photo":"Passport\nPhoto Maker","tool_photo_translation":"Photo\nTranslation","tool_scan_code":"Scan Code","tool_book_mode":"Book Mode",
        "tool_merge_pdf":"Merge PDF","tool_image_to_pdf":"Image to PDF","tool_text_to_pdf":"Text to PDF","tool_to_word":"To Word",
        "tool_pdf_to_word":"PDF to Word","tool_to_excel":"To Excel","tool_pdf_images":"PDF to\nImages","tool_pdf_long":"PDF to Long\nImage",
        "tool_opencv_crop":"OpenCV Crop","tool_bg_remove":"BG Remover","tool_resize":"Image Resizer","tool_smart_erase":"Smart Erase",
        "tool_split_pdf":"Split PDF","tool_sign":"Sign","tool_watermark":"Add\nWatermark","tool_extract_pages":"Extract PDF\nPages",
        "tool_reorder_pages":"Reorder\nPages","tool_rotate_pdf":"Rotate PDF","tool_lock":"Lock","tool_unlock":"Unlock",
        "tool_remove_pages":"Remove\nPages","tool_insert_pages":"Insert\nPages","tool_page_numbers":"Page\nNumbers","tool_header_footer":"Header /\nFooter",
        "tool_metadata":"PDF\nMetadata","tool_flatten":"Flatten PDF","tool_compress":"Compress","tool_ai_chat":"AI Chat","tool_print":"Print","tool_create_qr":"Create QR\nCode",
        "scanner":"SCANNER","export":"EXPORT","ocr":"OCR","app_privacy":"APP & PRIVACY","about":"ABOUT","backup":"BACKUP & PRIVATE VAULT",
        "auto_capture":"Auto capture","auto_crop":"Auto crop after capture","edge_sensitivity":"Edge detection sensitivity","capture_delay":"Capture delay",
        "high_resolution":"High resolution scan","auto_enhance":"Auto enhance","shutter_sound":"Shutter sound","vibration":"Vibration",
        "default_format":"Default format","default_page":"Default PDF page","default_margin":"Default margin","default_quality":"Default quality",
        "searchable_pdf":"Searchable PDF by default","save_exports":"Save exported files","custom_folder_none":"Custom folder: not selected",
        "default_ocr":"Default OCR language","auto_ocr":"Auto OCR after save","keep_ocr":"Keep OCR text","app_language":"App language",
        "dark_theme":"Dark theme","anonymous_analytics":"Anonymous analytics","clean_temp":"Clean temporary files on startup",
        "block_screenshots":"Block screenshots for locked/protected content","trash_auto_delete":"Trash auto-delete","app_lock":"App lock / PIN",
        "biometric_unlock":"Biometric unlock","lock_background":"Lock after background","set_pin":"SET / CHANGE PIN","remove_pin":"REMOVE PIN",
        "clear_cache":"CLEAR CACHE","crash_report":"CRASH REPORT","device_info":"DEVICE INFO","share_report":"SHARE REPORT",
        "run_health":"RUN HEALTH CHECK","last_health":"LAST HEALTH REPORT","app_info":"APP INFO","whats_new":"WHAT'S NEW",
        "filename_template":"Filename template","export_backup":"EXPORT BACKUP","restore_backup":"RESTORE BACKUP","check_vault":"CHECK PRIVATE VAULT","repair_paths":"REPAIR PATHS",
        "select_file_first":"Select a file first.","search_tools":"Search tools","tool_search_hint":"Type a tool name",
    },
    "bn": {
        "home":"হোম","files":"ফাইল","tools":"টুলস","settings":"সেটিংস",
        "run":"চালান","cancel":"বাতিল","save":"সেভ","close":"বন্ধ","ok":"ঠিক আছে","choose":"নির্বাচন","reset":"রিসেট",
        "copy":"কপি","share":"শেয়ার","done":"সম্পন্ন","processing":"প্রসেস হচ্ছে…","cancelled":"বাতিল করা হয়েছে",
        "scan":"স্ক্যান","convert":"কনভার্ট","edit":"এডিট","utilities":"ইউটিলিটি",
        "search":"খুঁজুন","search_documents":"ডকুমেন্ট খুঁজুন","discard":"বাতিল করুন","resume":"চালিয়ে যান","no_documents":"এখনও কোনো ডকুমেন্ট নেই",
        "scan_first_page":"প্রথম পেজ স্ক্যান করতে ক্যামেরা বাটনে চাপুন","scans_show_here":"স্ক্যান করা ডকুমেন্ট এখানে দেখা যাবে",
        "all":"সব","favorites":"ফেভারিট","folders":"ফোল্ডার","trash":"ট্র্যাশ","filter":"ফিল্টার","bulk":"বাল্ক",
        "document":"ডকুমেন্ট","documents":"ডকুমেন্ট","storage":"স্টোরেজ","storage_unavailable":"স্টোরেজ পাওয়া যাচ্ছে না",
        "unfinished_scan":"অসমাপ্ত স্ক্যান","page":"পেজ","pages":"পেজ",
        "tool_id_cards":"আইডি কার্ড","tool_nid_ocr":"NID OCR","tool_passport_mrz":"পাসপোর্ট MRZ","tool_extract_text":"টেক্সট বের করুন",
        "tool_passport_photo":"পাসপোর্ট\nফটো মেকার","tool_photo_translation":"ছবি\nঅনুবাদ","tool_scan_code":"কোড স্ক্যান","tool_book_mode":"বুক মোড",
        "tool_merge_pdf":"PDF মার্জ","tool_image_to_pdf":"ছবি থেকে PDF","tool_text_to_pdf":"টেক্সট থেকে PDF","tool_to_word":"Word-এ নিন",
        "tool_pdf_to_word":"PDF থেকে Word","tool_to_excel":"Excel-এ নিন","tool_pdf_images":"PDF থেকে\nছবি","tool_pdf_long":"PDF থেকে লং\nইমেজ",
        "tool_opencv_crop":"OpenCV ক্রপ","tool_bg_remove":"ব্যাকগ্রাউন্ড রিমুভ","tool_resize":"ছবি রিসাইজ","tool_smart_erase":"স্মার্ট ইরেজ",
        "tool_split_pdf":"PDF ভাগ করুন","tool_sign":"সাইন","tool_watermark":"ওয়াটারমার্ক\nযোগ","tool_extract_pages":"PDF পেজ\nবের করুন",
        "tool_reorder_pages":"পেজ\nসাজান","tool_rotate_pdf":"PDF ঘোরান","tool_lock":"লক","tool_unlock":"আনলক",
        "tool_remove_pages":"পেজ\nমুছুন","tool_insert_pages":"পেজ\nযোগ করুন","tool_page_numbers":"পেজ\nনম্বর","tool_header_footer":"হেডার /\nফুটার",
        "tool_metadata":"PDF\nমেটাডাটা","tool_flatten":"PDF ফ্ল্যাটেন","tool_compress":"কমপ্রেস","tool_ai_chat":"AI চ্যাট","tool_print":"প্রিন্ট","tool_create_qr":"QR কোড\nতৈরি",
        "scanner":"স্ক্যানার","export":"এক্সপোর্ট","ocr":"OCR","app_privacy":"অ্যাপ ও প্রাইভেসি","about":"অ্যাবাউট","backup":"ব্যাকআপ ও প্রাইভেট ভল্ট",
        "auto_capture":"অটো ক্যাপচার","auto_crop":"ক্যাপচারের পর অটো ক্রপ","edge_sensitivity":"এজ ডিটেকশন সেনসিটিভিটি","capture_delay":"ক্যাপচার বিলম্ব",
        "high_resolution":"হাই রেজোলিউশন স্ক্যান","auto_enhance":"অটো এনহ্যান্স","shutter_sound":"শাটার সাউন্ড","vibration":"ভাইব্রেশন",
        "default_format":"ডিফল্ট ফরম্যাট","default_page":"ডিফল্ট PDF পেজ","default_margin":"ডিফল্ট মার্জিন","default_quality":"ডিফল্ট কোয়ালিটি",
        "searchable_pdf":"ডিফল্ট সার্চযোগ্য PDF","save_exports":"এক্সপোর্ট কোথায় সেভ হবে","custom_folder_none":"কাস্টম ফোল্ডার: নির্বাচন করা হয়নি",
        "default_ocr":"ডিফল্ট OCR ভাষা","auto_ocr":"সেভের পর অটো OCR","keep_ocr":"OCR টেক্সট রাখুন","app_language":"অ্যাপ ভাষা",
        "dark_theme":"ডার্ক থিম","anonymous_analytics":"অ্যানোনিমাস অ্যানালিটিক্স","clean_temp":"শুরুর সময় টেম্প ফাইল পরিষ্কার",
        "block_screenshots":"লক/প্রটেক্টেড কনটেন্টে স্ক্রিনশট বন্ধ","trash_auto_delete":"ট্র্যাশ অটো-ডিলিট","app_lock":"অ্যাপ লক / PIN",
        "biometric_unlock":"বায়োমেট্রিক আনলক","lock_background":"ব্যাকগ্রাউন্ডের পর লক","set_pin":"PIN সেট / পরিবর্তন","remove_pin":"PIN সরান",
        "clear_cache":"ক্যাশ পরিষ্কার","crash_report":"ক্র্যাশ রিপোর্ট","device_info":"ডিভাইস তথ্য","share_report":"রিপোর্ট শেয়ার",
        "run_health":"হেলথ চেক চালান","last_health":"শেষ হেলথ রিপোর্ট","app_info":"অ্যাপ তথ্য","whats_new":"নতুন কী আছে",
        "filename_template":"ফাইলনেম টেমপ্লেট","export_backup":"ব্যাকআপ এক্সপোর্ট","restore_backup":"ব্যাকআপ রিস্টোর","check_vault":"প্রাইভেট ভল্ট চেক","repair_paths":"পাথ রিপেয়ার",
        "select_file_first":"প্রথমে একটি ফাইল নির্বাচন করুন।","search_tools":"টুল খুঁজুন","tool_search_hint":"টুলের নাম লিখুন",
    },
}


def normalize_language(value):
    value = (value or "en").lower()
    return "bn" if value in {"bn", "bangla", "bengali"} else "en"


def tr(key, language="en", default=None):
    language = normalize_language(language)
    english = TRANSLATIONS["en"]
    table = TRANSLATIONS.get(language, english)
    return table.get(key, english.get(key, default if default is not None else key))


def missing_translation_keys():
    """Return language->keys missing compared with the English catalogue."""
    base = set(TRANSLATIONS["en"])
    return {lang: sorted(base - set(values)) for lang, values in TRANSLATIONS.items() if lang != "en"}
