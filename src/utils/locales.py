"""MediaCompressor çoklu dil (TR / EN) yerelleştirme tablosu."""

from __future__ import annotations

import locale
import os
import sys
from typing import Any

LOCALES: dict[str, dict[str, str]] = {
    "tr": {
        "app_name": "Medya Sıkıştırıcı",
        "output_folder_default": "sıkıştırılmış",
        "settings": "Ayarlar",
        "menu_file": "Dosya",
        "menu_add_files": "Dosya Seç…",
        "menu_add_folder": "Klasör Seç…",
        "theme": "Tema",
        "theme_system": "Sistem",
        "theme_dark": "Koyu",
        "theme_light": "Açık",
        "accent": "Renk",
        "language": "Dil",
        "lang_auto": "Otomatik (Sistem)",
        "show_notifications": "Bildirimleri Göster",
        "start_at_login": "Açılışta Başlat",
        "start_at_login_hint": "Açılışta pencere gelmez; tepsi simgesinden açılır.",
        "updates": "Güncellemeler",
        "auto_update_check": "Güncellemeleri Otomatik Kontrol Et",
        "update_check_title": "Güncelleme Kontrolü",
        "update_current": "{app} güncel.\n\nMevcut sürüm: {version}",
        "update_check_failed_msg": "Güncelleme denetlenemedi. İnternet bağlantınızı kontrol edip tekrar deneyin.",
        "check_now": "Kontrol Et",
        "update_pill": "Güncelle · v{version}",
        "update_pill_tip": "Yeni sürüm v{version} hazır; ayrıntılar ve kurulum için tıklayın",
        "update_btn_name": "Güncelle",
        "update_new_version": "Yeni sürüm: v{version}",
        "auto_update_install": "Güncellemeleri Otomatik Kur",
        "auto_update_hint": "Yeni sürüm bulunduğunda arka planda indirilir ve uygulama kullanılmıyorken kurulur.",
        "update_auto_failed": "Otomatik güncelleme tamamlanamadı; başlıktaki ↑ simgesinden, Ayarlar'dan ya da tepsi menüsünden yeniden deneyebilirsiniz.",
        "checking": "Kontrol ediliyor…",
        "up_to_date": "Güncel · v{}",
        "save": "Kaydet",
        "cancel": "İptal",
        "drop_hint": "Dosya veya klasörü buraya bırakın",
        "choose_folder": "Klasör Seç",
        "choose_file": "Dosya Seç",
        "open_folder": "Klasörü Aç",
        "not_selected": "Henüz seçilmedi",
        "output_folder": "Çıkış Klasörü",
        "file_type": "Dosya Türü",
        "section_source": "Kaynak",
        "adv_group_video": "Video Kodlama",
        "adv_group_speed": "Hız ve Ses",
        "adv_group_general": "Genel",
        "section_output": "Çıkış Klasörü",
        "section_quality": "Çıktı Ayarları",
        "output_change": "Değiştir",
        "type_all": "Tümü",
        "type_images": "Resimler",
        "type_videos": "Videolar",
        "video": "Video",
        "image": "Resim",
        "adv_settings": "Gelişmiş Ayarlar",
        "queue": "Kuyruk",
        "clear_queue": "Kuyruğu Temizle",
        "remove": "Çıkar",
        "retry_failed": "Hatalıları Tekrar Dene",
        "start_compression": "Sıkıştırmayı Başlat",
        "stop_compression": "Durdur",
        "open_output": "Çıktıyı Aç",
        "open_when_done": "Bitince Klasörü Aç",
        "open_when_done_tip": "İş bittiğinde çıktı klasörünü otomatik açar.",
        "ready": "Hazır",
        "tray_show": "Göster",
        "tray_hide": "Gizle",
        "tray_quit": "Çıkış",
        "log": "Kayıt",
        "duration": "süre",
        "saved": "tasarruf",
        "pct": "%{}",
        "no_files": "Sıkıştırılacak dosya bulunamadı.",
        "profile_balanced": "Dengeli (Önerilen)",
        "profile_fast": "Hızlı Paylaşım",
        "profile_custom": "Özel",
        "gpu_detecting": "GPU algılanıyor…",
        "download_ffmpeg": "FFmpeg İndir",
        "ffmpeg_recheck": "Yeniden Tara",
        "ffmpeg_missing_windows": "FFmpeg bulunamadı. FFmpeg İndir düğmesine basın veya ffmpeg'i PATH'e ekleyin.",
        "ffmpeg_missing_macos": "FFmpeg bulunamadı. Terminal'de şunu çalıştırın:\nbrew install ffmpeg\nArdından Yeniden Tara düğmesine basın. (Homebrew yoksa: https://brew.sh)",
        "ffmpeg_missing_linux": "FFmpeg bulunamadı. Paket yöneticinizle kurun:\nsudo apt install ffmpeg   (Debian/Ubuntu)\nsudo dnf install ffmpeg   (Fedora)\nsudo pacman -S ffmpeg   (Arch)\nArdından Yeniden Tara düğmesine basın.",
        "current_version": "Mevcut sürüm: v{}",
        "gpu_prefix": "GPU: {}",
        "gpu_none_value": "—",
        "ffmpeg_not_found": "bulunamadı",
        "about": "Hakkında",
        "about_version_line": "Sürüm v{} — Video & Medya Sıkıştırıcı",
        "about_desc": "• H.264, H.265 (HEVC), AV1 Kodek Desteği\n• NVIDIA (NVENC), Intel (QSV), AMD (AMF) Donanım Hızlandırma\n• Toplu Kuyruk İşleme ve Sürükle-Bırak Kolaylığı\n• WhatsApp, Discord, Web ve Özel Çıktı Profilleri",
        "minimize": "Küçült",
        "maximize": "Ekranı Kapla",
        "close_tooltip": "Kapat",
        "restore": "Geri Yükle",
        "ok": "Tamam",
        "updater_unavailable": "Güncelleme kontrolcüsü yok",
        "update_new_available": "Yeni sürüm mevcut",
        "update_check_failed": "Kontrol edilemedi",
        "accent_default": "(varsayılan)",
        "accent_blue": "Mavi",
        "accent_cyan": "Turkuaz",
        "accent_teal": "Zümrüt",
        "accent_indigo": "İndigo",
        "accent_violet": "Mor",
        "accent_rose": "Gül",
        "accent_orange": "Kehribar",
        "accent_red": "Kırmızı",
        "accent_green": "Yeşil",
        "accent_yellow": "Sarı",
        "queue_col_file": "Dosya",
        "queue_col_status": "Durum",
        "queue_col_size": "Boyut",
        "queue_tooltip": "Sürükleyerek sırayı değiştirin. Del veya sağ tık: kuyruktan çıkarır. Orijinal dosya silinmez.",
        "queue_empty_title": "Kuyruk boş",
        "queue_empty_hint": "Soldaki alana dosya ya da klasör bırakın veya Dosya Seç / Klasör Seç'e tıklayın. Eklediğiniz dosyalar burada listelenir.",
        "start_needs_files": "Önce kuyruğa dosya ekleyin",
        "queue_summary": "{n} dosya · toplam {size}",
        "status_wait": "Bekliyor",
        "status_run": "İşleniyor",
        "status_ok": "Tamam",
        "status_skip": "Atlandı",
        "status_fail": "Hata",
        "status_cancel": "İptal",
        "queue_remove": "Kuyruktan Çıkar",
        "queue_remove_n": "Kuyruktan Çıkar ({})",
        "reveal_in_folder": "Klasörde Göster",
        "open_file": "Dosyayı Aç",
        "ovr_menu": "İstisna Uygula",
        "ovr_video_res": "Video Çözünürlüğü",
        "ovr_image_res": "Resim Boyutu",
        "ovr_fps": "Kare Hızı (FPS)",
        "ovr_default": "Genel Ayarı Kullan",
        "ovr_clear": "İstisnaları Kaldır",
        "ovr_tooltip": "İstisna: {}",
        "ovr_audio": "Ses",
        "ovr_audio_keep_option": "Sesi Koru",
        "ovr_audio_mute_option": "Sesi Kaldır",
        "ovr_audio_keep": "Sesli",
        "ovr_audio_mute": "Sessiz",
        "adv_remove_audio": "Sesi Kaldır (Sessiz Video)",
        "av1_cpu_hint": "Bu bilgisayarın ekran kartı AV1 kodlayamıyor: AV1 işlemciyle yapılır (daha yavaş, dosya yine en küçük).",
        "av1_slow_hint": "Dikkat: bu bilgisayarda AV1 çok yavaş. Ekran kartı AV1 kodlayamıyor ve FFmpeg'de hızlı AV1 kodlayıcısı (SVT-AV1) yok; video süresinin yaklaşık 10 katı sürer. HEVC önerilir.",
        "av1_none_hint": "Bu bilgisayarda AV1 kodlanamıyor (ekran kartı da FFmpeg de desteklemiyor). Başka bir kodek seçin.",
        "trim_menu": "Kırp…",
        "trim_title": "Videoyu Kırp",
        "trim_hint": "Başlangıç ve bitişi seçin; yalnızca aradaki bölüm sıkıştırılır. Kaynak dosya değişmez.",
        "trim_start": "Başlangıç",
        "trim_end": "Bitiş",
        "trim_loading": "Kare yükleniyor…",
        "trim_no_frame": "Kare gösterilemedi",
        "trim_info": "Yeni süre: {new}  ·  Orijinal: {total}",
        "trim_reset": "Tamamını Kullan",
        "trim_apply": "Uygula",
        "trim_to_end": "son",
        "trim_remove": "Kırpmayı Kaldır",
        "trim_no_duration": "Videonun süresi okunamadı; bu dosya kırpılamıyor.",
        "fps_value": "{} fps",
        "fps_original": "Orijinal fps",
        "adv_fps": "Kare Hızı (FPS)",
        "fps_orig_option": "Orijinal (kaynaktaki gibi)",
        "fps_hint": "Düşürmek dosyayı küçültür. Kaynaktan yüksek bir değer seçilse de kare hızı artırılmaz.",
        "dur_h": "sa",
        "dur_m": "dk",
        "dur_s": "sn",
        "adv_hint": "Bitrate, kalite, hız ve GPU (video kodeği ana ekranda)",
        "adv_bitrate": "Bitrate",
        "adv_quality_crf": "Kalite (CRF)",
        "adv_processing_speed": "İşleme Hızı",
        "adv_audio": "Ses",
        "adv_img_auto": "Resim Kalitesi Otomatik",
        "adv_subfolders": "Alt Klasörleri İşle (Sıkıştırılmış Hariç)",
        "adv_gpu": "GPU",
        "adv_gpu_auto": "Otomatik",
        "adv_gpu_cpu": "CPU (Sadece İşlemci)",
        "crf_very_high": "{}  ·  çok kaliteli, dosya daha büyük",
        "crf_balanced": "{}  ·  dengeli (önerilen)",
        "crf_smaller": "{}  ·  daha küçük dosya, hafif kayıp",
        "crf_smallest": "{}  ·  en küçük dosya, belirgin kayıp",
        "crf_tooltip": "Düşük CRF = daha net görüntü ve daha büyük dosya.\nYüksek CRF = daha küçük dosya, daha fazla kalite kaybı.",
        "preset_superfast": "Çok hızlı — zayıf sıkıştırma",
        "preset_veryfast": "Oldukça hızlı",
        "preset_faster": "Hızlı",
        "preset_fast": "Orta-hızlı",
        "preset_medium": "Dengeli",
        "preset_slow": "Yavaş — daha iyi sıkıştırma (önerilen)",
        "preset_slower": "Daha yavaş — en küçük dosya",
        "preset_hint": "Yavaş = daha uzun sürer, genelde daha küçük video. Hızlı = çabuk biter, dosya biraz büyük kalır.",
        "audio_hint": "128k konuşma ve paylaşım için yeterli. 192k müzik / yüksek kalite için.",
        "bitrate_auto_hint": "Otomatik (CRF): sabit hız yok. Her sahne, seçtiğiniz kaliteye yetecek kadar veri kullanır. Düz sahneler küçülür, hareketli sahneler biraz büyür — dosya boyutu kaliteye göre oluşur.",
        "crf_mode_hint": "Düşük CRF (18–20) daha net ve daha büyük dosya. Yüksek CRF (28–32) daha küçük dosya, daha fazla kayıp. 24 çoğu paylaşım için dengeli.",
        "bitrate_fixed_hint": "Sabit bitrate: video her saniye bu kadar veri kullanır. CRF bu modda devre dışı. Kısa videoda öngörülebilir boyut istiyorsanız bunu seçin.",
        "crf_disabled_hint": "Sabit bitrate açık olduğu için CRF kullanılmıyor.",
        "update_dialog_title": "Güncelleme Mevcut",
        "update_available_title": "{} {} mevcut",
        "update_version_line": "Mevcut sürüm: {}  →  Yeni sürüm: {}",
        "update_notes_default": "<p>Yeni sürüm hazır.</p>",
        "update_later": "Daha Sonra",
        "update_now": "Şimdi Güncelle",
        "update_downloading": "İndiriliyor…",
        "update_downloaded_bytes": "{} indirildi",
        "update_installing": "Kuruluyor… Uygulama kısa süre sonra yeniden başlayacak.",
        "tray_update_now": "Güncelle · v{version}",
        "update_size_line": "İndirme boyutu: {size}",
        "update_failed_inline": "Güncelleme tamamlanamadı: {error}",
        "update_retry": "Tekrar Dene",
        "update_close": "Kapat",
        "update_installed_toast": "{app} v{version} sürümüne güncellendi.",
        "update_err_unsafe_url": "Güvenli olmayan indirme adresi.",
        "update_err_checksum_invalid": "Güncelleme sağlama toplamı geçersiz (SHA-256 bekleniyor).",
        "update_err_checksum_mismatch": "Dosya bütünlüğü doğrulanamadı (checksum).",
        "update_err_redirect": "Güncelleme sunucusu güvensiz (https olmayan) adrese yönlendirdi.",
        "update_err_incomplete": "İndirme tamamlanamadı: bağlantı yarıda kesildi.",
        "update_err_not_found": "Güncelleme dosyası bulunamadı.",
        "update_err_http": "Sunucu hata döndürdü (HTTP {code}).",
        "update_err_network": "Sunucuya bağlanılamadı. İnternet bağlantınızı kontrol edip tekrar deneyin.",
        "update_err_unsupported_os": "Otomatik kurulum bu sistemde desteklenmiyor.",
        "update_err_unsupported_source": "Otomatik kurulum yalnızca paketlenmiş uygulamada (exe) çalışır; kaynak koddan çalışırken desteklenmez.",
        "update_pkg_read": "Paket okunamadı: {detail}",
        "update_pkg_not_package": "İndirilen dosya bir exe ya da zip değil.",
        "update_pkg_too_big": "Paket izin verilen boyuttan büyük.",
        "update_pkg_no_exe": "Pakette uygulamanın exe dosyası yok.",
        "update_pkg_bad_zip": "Zip dosyası bozuk: {detail}",
        "update_pkg_write": "Yeni sürüm uygulamanın klasörüne yazılamadı: {detail}",
        "update_pkg_not_pe": "Paketteki dosya geçerli bir uygulama dosyası değil.",
        "update_pkg_arch": "Paket başka bir işlemci mimarisi için hazırlanmış.",
        "update_pkg_not_writable": "Uygulamanın bulunduğu klasöre yazılamıyor ({detail}). Uygulamayı yazılabilir bir klasöre (ör. Belgeler ya da Masaüstü) taşıyıp yeniden açın.",
        "update_pkg_swap": "Çalışan uygulama dosyası değiştirilemedi: {detail}",
        "update_pkg_swap2": "Yeni sürüm yerine konamadı: {detail}",
        "update_pkg_spawn": "Yeni sürüm başlatılamadı: {detail}",
        "profile_quality": "Yüksek Kalite",
        "codec_h264_desc": "H.264 — her yerde açılır",
        "codec_hevc_desc": "H.265 (HEVC) — daha küçük",
        "codec_av1_desc": "AV1 — en küçük",
        "video_codec": "Video Kodeği",
        "codec_h264_hint": "Her telefon, TV ve uygulamada açılır (WhatsApp dahil). Önerilen.",
        "codec_hevc_hint": "Aynı kalitede H.264'ten %10–35 küçük. iPhone, yeni Android'ler ve Mac açar; bazı oynatıcılar HEVC uzantısı ister (VLC açar).",
        "codec_av1_hint": "En küçük dosya (H.264'ün yarısına kadar). Yeni cihazlar ve tarayıcılar açar; eski TV ve telefonlar açamayabilir.",
        "bitrate_auto_desc": "Otomatik — kaliteye göre (CRF)",
        "bitrate_1500k_desc": "1500k — küçük dosya",
        "bitrate_2000k_desc": "2000k — önerilen",
        "bitrate_2500k_desc": "2500k — yüksek",
        "bitrate_4000k_desc": "4000k — maksimum",
        "res_original": "Orijinal",
        "stopping": "Durduruluyor…",
        "files_progress": "{done}/{total} dosya",
        "stats_elapsed": "geçen {elapsed}",
        "stats_elapsed_remaining": "geçen {elapsed}  ·  kalan ~{remaining}",
        "job_summary": "{title} — başarılı {ok} · atlanan {skip} · hatalı {fail}",
        "summary_cancelled": "Durduruldu",
        "summary_completed": "Tamamlandı",
        "msg_open_folder_failed": "Klasör açılamadı:\n{}",
        "msg_open_location_failed": "Konum açılamadı:\n{}",
        "msg_open_file_failed": "Dosya açılamadı:\n{}",
        "msg_create_folder_failed": "Klasör oluşturulamadı:\n{}\n{}",
        "msg_ffmpeg_needed": "Video için FFmpeg gerekli. FFmpeg İndir düğmesine basın veya FFmpeg kurun.",
        "msg_ffmpeg_needed_macos": "Video için FFmpeg gerekli. Terminal'de \"brew install ffmpeg\" çalıştırın, sonra Yeniden Tara düğmesine basın.",
        "msg_ffmpeg_needed_linux": "Video için FFmpeg gerekli. \"sudo apt install ffmpeg\" (veya dağıtımınızın paket yöneticisi) ile kurun, sonra Yeniden Tara düğmesine basın.",
        "msg_install_after_done": "Sıkıştırma bitince kurulum başlayacak.",
        "gpu_none_hint": "FFmpeg yok — yalnızca resim sıkıştırılabilir",
        "queue_remove_tooltip": "Seçilenleri kuyruktan çıkar (Del). Orijinal dosya silinmez.",
        "panel_hide": "Ayar panelini gizle (kuyruk genişler)",
        "panel_show": "Ayar panelini göster",
        "log_unexpected_error": "Beklenmeyen hata: {error}",
        "log_no_files": "Seçilen türde işlenecek dosya bulunamadı.",
        "log_stale_cleaned": "{count} yarım kalmış geçici dosya temizlendi.",
        "log_job_start": "{total} dosya bulundu. Sıkıştırma başlıyor…",
        "log_skipped_exists": "Atlandı (zaten mevcut): {name}",
        "log_file_error": "Hata ({name}): {error}",
        "log_image_done": "Resim [{done}/{total}]: {name} ({size_in} → {size_out} | -{pct})",
        "log_stopped": "İşlem durduruldu.",
        "log_container_switch": "{name}: {ext} bu kodeği ({codec}) düzgün taşımıyor, {target} olarak kaydedilecek",
        "log_no_ffmpeg": "FFmpeg yok, video atlandı",
        "log_no_ffmpeg_file": "FFmpeg yok, video atlandı: {name}",
        "log_video_start": "Video [{done}/{total}]: {name} …",
        "log_video_done": "Tamamlandı [{method}]: {name} ({size_in} → {size_out} | -{pct} | {elapsed})",
        "log_original_kept": "Orijinal korundu",
        "log_video_error": "Video hatası ({name}): {error}",
        "image_res_tip": "Resmin en uzun kenarını sınırlar. Küçük resimler (örn: 2000px) asla büyütülmez (upscale yapılmaz), orijinal çözünürlük korunur.",
        "video_res_tip": "Videonun maksimum çözünürlüğünü belirler (örn: 1080p Full HD). Orijinal daha küçükse büyütülmez.",
        "profile_balanced_tip": "Dengeli sıkıştırma: Genel kullanım ve arşiv için ideal (CRF 24, 1080p / 2400px, %90 Kalite).",
        "profile_fast_tip": "Hızlı paylaşım: WhatsApp, Discord ve sosyal medya için hafif boyut (CRF 26, 1080p / 1920px, %85 Kalite).",
        "profile_quality_tip": "Yüksek kalite: CRF 20, orijinal video çözünürlüğü ve 3840px resim ile kayıpsıza yakın arşivleme (%95 Kalite).",
        "profile_custom_tip": "Özel: Tüm çözünürlük, kodek, bitrate ve kalite parametrelerini serbestçe ayarlayın.",
        "preview_btn": "Canlı Önizleme / Karşılaştır",
        "preview_tooltip": "Sıkıştırma kalitesini canlı ayarlayın. Boşluk (Space) tuşuyla orijinal ve sıkıştırılmışı anında karşılaştırın.",
        "preview_dialog_title": "Canlı Kalite Önizleme & Karşılaştırma",
        "preview_hint": "Kalite ve formatı değiştirin. Orijinali görmek için [Boşluk] tuşuna basılı tutun!",
        "preview_toggle_btn": "Orijinal (Boşluk)",
        "preview_apply_btn": "Bu Kaliteyi Uygula",
        "preview_save_btn": "Farklı Kaydet…",
        "preview_badge_orig": "ORİJİNAL (Boşluk Basılı)",
        "preview_badge_comp": "SIKIŞTIRILMIŞ",
        "preview_quality_label": "Kalite: %{}",
        "preview_res_label": "Maks. Çözünürlük",
        "preview_change_img": "Farklı Resim Seç",
        "custom_option": "Özel…",
        "custom_res_title_video": "Özel Video Çözünürlüğü",
        "custom_res_prompt_video": "Maksimum video genişliğini piksel (px) olarak girin:\n(Örn: 1920 = 1080p, 1280 = 720p, 2560 = 1440p, 3840 = 4K)",
        "custom_res_title_image": "Özel Maksimum Çözünürlük",
        "custom_res_prompt_image": "Maksimum kenar boyutu (piksel):",
        "log_started": "Başladı — {codec} / {bitrate} / GPU:{gpu}",
        "log_prepare_error": "Hazırlık hatası: {}",
        "log_ffmpeg_downloading": "FFmpeg indiriliyor…",
        "log_ffmpeg_ready": "FFmpeg hazır: {}",
        "preview_frame_label": "Kare",
        "preview_pick_video": "Video Seç",
        "preview_pick_other_video": "Farklı Video Seç",
        "preview_pick_image": "Resim Seç",
        "preview_format_label": "Format",
        "preview_format_tip": "Sıkıştırma formatı: JPEG, WebP, AVIF veya JPEG XL (JXL).",
        "preview_toggle_tip": "Basılı tutarak orijinali görüntüleyin. Klavyeden [Boşluk] tuşuna basılı tutarak da karşılaştırabilirsiniz.",
        "preview_no_file": "Dosya seçilmedi",
        "preview_calculating": "Hesaplanıyor…",
        "preview_calculating_frame": "Kare Hesaplanıyor…",
        "preview_calculating_fmt": "{fmt} Hesaplanıyor…",
        "preview_loading_frame": "Kare Yükleniyor ({time})…",
        "preview_empty_title": "Resim veya Video Seçin",
        "preview_empty_hint": "Canlı kalite karşılaştırması yapmak için yukarıdaki\nResim Seç veya Video Seç düğmesini kullanın.",
        "preview_badge_frame": "SIKIŞTIRILMIŞ KARE",
        "preview_lbl_video": "Video",
        "preview_lbl_orig_frame": "Orijinal Kare",
        "preview_lbl_comp_frame": "Sıkıştırılmış Kare",
        "preview_lbl_frame_savings": "Kare Tasarrufu",
        "preview_lbl_orig": "Orijinal",
        "preview_lbl_savings": "Tasarruf",
        "preview_filter_images": "Resim Dosyaları",
        "preview_filter_videos": "Video Dosyaları",
        "preview_filter_all": "Tüm Dosyalar",
        "preview_saved_title": "Başarılı",
        "preview_saved_text": "Dosya kaydedildi:\n{}",
        "preview_error_title": "Hata",
        "preview_frame_failed": "Videodan kare alınamadı (FFmpeg hazır olmayabilir).",
        "preview_open_failed": "Resim açılamadı:\n{}",
        "preview_save_failed": "Kaydedilemedi:\n{}",
    },
    "en": {
        "app_name": "Media Compressor",
        "output_folder_default": "compressed",
        "settings": "Settings",
        "menu_file": "File",
        "menu_add_files": "Choose Files…",
        "menu_add_folder": "Choose Folder…",
        "theme": "Theme",
        "theme_system": "System",
        "theme_dark": "Dark",
        "theme_light": "Light",
        "accent": "Color",
        "language": "Language",
        "lang_auto": "Auto (System)",
        "show_notifications": "Show Notifications",
        "start_at_login": "Start at Login",
        "start_at_login_hint": "The window stays hidden at login; open it from the tray icon.",
        "updates": "Updates",
        "auto_update_check": "Check for Updates Automatically",
        "update_check_title": "Update Check",
        "update_current": "{app} is up to date.\n\nCurrent version: {version}",
        "update_check_failed_msg": "Could not check for updates. Check your internet connection and try again.",
        "check_now": "Check for Updates",
        "update_pill": "Update · v{version}",
        "update_pill_tip": "Version v{version} is ready; click for details and installation",
        "update_btn_name": "Update",
        "update_new_version": "New version: v{version}",
        "auto_update_install": "Install Updates Automatically",
        "auto_update_hint": "When a new version is found, it is downloaded in the background and installed while the app is not in use.",
        "update_auto_failed": "The automatic update could not be completed; you can retry from the ↑ icon in the title bar, Settings or the tray menu.",
        "checking": "Checking…",
        "up_to_date": "Up to date · v{}",
        "save": "Save",
        "cancel": "Cancel",
        "drop_hint": "Drag and drop files or folders here",
        "choose_folder": "Choose Folder",
        "choose_file": "Choose Files",
        "open_folder": "Open Folder",
        "not_selected": "None selected yet",
        "output_folder": "Output Folder",
        "file_type": "File Type",
        "section_source": "Source",
        "adv_group_video": "Video Encoding",
        "adv_group_speed": "Speed & Audio",
        "adv_group_general": "General",
        "section_output": "Output Folder",
        "section_quality": "Output Settings",
        "output_change": "Change",
        "type_all": "All",
        "type_images": "Images",
        "type_videos": "Videos",
        "video": "Video",
        "image": "Image",
        "adv_settings": "Advanced Settings",
        "queue": "Queue",
        "clear_queue": "Clear Queue",
        "remove": "Remove",
        "retry_failed": "Retry Failed",
        "start_compression": "Start Compression",
        "stop_compression": "Stop",
        "open_output": "Open Output",
        "open_when_done": "Open Folder When Finished",
        "open_when_done_tip": "Automatically open output folder when finished.",
        "ready": "Ready",
        "tray_show": "Show",
        "tray_hide": "Hide",
        "tray_quit": "Exit",
        "log": "Log",
        "duration": "time",
        "saved": "saved",
        "pct": "{}%",
        "no_files": "No files found to compress.",
        "profile_balanced": "Balanced (Recommended)",
        "profile_fast": "Quick Share",
        "profile_custom": "Custom",
        "gpu_detecting": "Detecting GPU…",
        "download_ffmpeg": "Download FFmpeg",
        "ffmpeg_recheck": "Scan Again",
        "ffmpeg_missing_windows": "FFmpeg not found. Click Download FFmpeg or add ffmpeg to your PATH.",
        "ffmpeg_missing_macos": "FFmpeg not found. Run this in Terminal:\nbrew install ffmpeg\nThen click Scan Again. (No Homebrew? See https://brew.sh)",
        "ffmpeg_missing_linux": "FFmpeg not found. Install it with your package manager:\nsudo apt install ffmpeg   (Debian/Ubuntu)\nsudo dnf install ffmpeg   (Fedora)\nsudo pacman -S ffmpeg   (Arch)\nThen click Scan Again.",
        "current_version": "Current version: v{}",
        "gpu_prefix": "GPU: {}",
        "gpu_none_value": "None",
        "ffmpeg_not_found": "not found",
        "about": "About",
        "about_version_line": "Version v{} — Video & Media Compressor",
        "about_desc": "• H.264, H.265 (HEVC), AV1 codec support\n• NVIDIA (NVENC), Intel (QSV), AMD (AMF) hardware acceleration\n• Batch queue processing and drag-and-drop\n• WhatsApp, Discord, Web and custom output profiles",
        "minimize": "Minimize",
        "maximize": "Maximize",
        "close_tooltip": "Close",
        "restore": "Restore Down",
        "ok": "OK",
        "updater_unavailable": "Update checker unavailable",
        "update_new_available": "New version available",
        "update_check_failed": "Check failed",
        "accent_default": "(default)",
        "accent_blue": "Blue",
        "accent_cyan": "Cyan",
        "accent_teal": "Teal",
        "accent_indigo": "Indigo",
        "accent_violet": "Violet",
        "accent_rose": "Rose",
        "accent_orange": "Orange",
        "accent_red": "Red",
        "accent_green": "Green",
        "accent_yellow": "Yellow",
        "queue_col_file": "File",
        "queue_col_status": "Status",
        "queue_col_size": "Size",
        "queue_tooltip": "Drag to reorder. Del or right click to remove. Original file is not deleted.",
        "queue_empty_title": "The queue is empty",
        "queue_empty_hint": "Drop files or a folder on the area at the left, or click Choose Files / Choose Folder. What you add is listed here.",
        "start_needs_files": "Add files to the queue first",
        "queue_summary": "{n} files · {size} in total",
        "status_wait": "Waiting",
        "status_run": "Processing",
        "status_ok": "Done",
        "status_skip": "Skipped",
        "status_fail": "Failed",
        "status_cancel": "Canceled",
        "queue_remove": "Remove from Queue",
        "queue_remove_n": "Remove from Queue ({})",
        "reveal_in_folder": "Show in Folder",
        "open_file": "Open File",
        "ovr_menu": "Apply Exception",
        "ovr_video_res": "Video Resolution",
        "ovr_image_res": "Image Size",
        "ovr_fps": "Frame Rate (FPS)",
        "ovr_default": "Use General Setting",
        "ovr_clear": "Remove Exceptions",
        "ovr_tooltip": "Exception: {}",
        "ovr_audio": "Audio",
        "ovr_audio_keep_option": "Keep Audio",
        "ovr_audio_mute_option": "Remove Audio",
        "ovr_audio_keep": "With audio",
        "ovr_audio_mute": "No audio",
        "adv_remove_audio": "Remove Audio (Silent Video)",
        "av1_cpu_hint": "This computer's graphics card can't encode AV1: AV1 runs on the processor (slower, still the smallest file).",
        "av1_slow_hint": "Warning: AV1 is very slow on this computer. The graphics card can't encode AV1 and FFmpeg has no fast AV1 encoder (SVT-AV1); it takes about 10x the video's length. HEVC is recommended.",
        "av1_none_hint": "AV1 can't be encoded on this computer (neither the graphics card nor FFmpeg supports it). Pick another codec.",
        "trim_menu": "Trim…",
        "trim_title": "Trim Video",
        "trim_hint": "Pick the start and the end; only the part in between is compressed. The source file is not changed.",
        "trim_start": "Start",
        "trim_end": "End",
        "trim_loading": "Loading frame…",
        "trim_no_frame": "Couldn't show the frame",
        "trim_info": "New length: {new}  ·  Original: {total}",
        "trim_reset": "Use Full Length",
        "trim_apply": "Apply",
        "trim_to_end": "end",
        "trim_remove": "Remove Trim",
        "trim_no_duration": "Couldn't read the video's length; this file can't be trimmed.",
        "fps_value": "{} fps",
        "fps_original": "Original fps",
        "adv_fps": "Frame Rate (FPS)",
        "fps_orig_option": "Original (as in the source)",
        "fps_hint": "Lowering it makes the file smaller. Choosing more than the source never raises the frame rate.",
        "dur_h": "h",
        "dur_m": "m",
        "dur_s": "s",
        "adv_hint": "Bitrate, quality, speed and GPU (the video codec is on the main screen)",
        "adv_bitrate": "Bitrate",
        "adv_quality_crf": "Quality (CRF)",
        "adv_processing_speed": "Processing Speed",
        "adv_audio": "Audio",
        "adv_img_auto": "Automatic Image Quality",
        "adv_subfolders": "Process Subfolders (Except Compressed)",
        "adv_gpu": "GPU",
        "adv_gpu_auto": "Auto",
        "adv_gpu_cpu": "CPU (Processor only)",
        "crf_very_high": "{}  ·  very high quality, larger file",
        "crf_balanced": "{}  ·  balanced (recommended)",
        "crf_smaller": "{}  ·  smaller file, slight loss",
        "crf_smallest": "{}  ·  smallest file, noticeable loss",
        "crf_tooltip": "Lower CRF = sharper image and larger file.\nHigher CRF = smaller file, more quality loss.",
        "preset_superfast": "Super fast — weak compression",
        "preset_veryfast": "Very fast",
        "preset_faster": "Faster",
        "preset_fast": "Fast",
        "preset_medium": "Balanced",
        "preset_slow": "Slow — better compression (recommended)",
        "preset_slower": "Slower — smallest file",
        "preset_hint": "Slow = takes longer, usually smaller video. Fast = finishes quickly, file stays a bit larger.",
        "audio_hint": "128k is enough for speech and sharing. 192k for music / high quality.",
        "bitrate_auto_hint": "Auto (CRF): no fixed rate. Each scene uses enough data for your chosen quality. Static scenes shrink, motion scenes grow — file size follows quality.",
        "crf_mode_hint": "Low CRF (18–20) is sharper and larger. High CRF (28–32) is smaller with more loss. 24 is balanced for most sharing.",
        "bitrate_fixed_hint": "Fixed bitrate: video uses this much data every second. CRF is disabled in this mode. Choose it when you want predictable size for short clips.",
        "crf_disabled_hint": "CRF is not used while fixed bitrate is enabled.",
        "update_dialog_title": "Update Available",
        "update_available_title": "{} {} available",
        "update_version_line": "Current version: {}  →  New version: {}",
        "update_notes_default": "<p>New version ready.</p>",
        "update_later": "Later",
        "update_now": "Update Now",
        "update_downloading": "Downloading…",
        "update_downloaded_bytes": "{} downloaded",
        "update_installing": "Installing… the app will restart in a moment.",
        "tray_update_now": "Update · v{version}",
        "update_size_line": "Download size: {size}",
        "update_failed_inline": "The update could not be completed: {error}",
        "update_retry": "Try Again",
        "update_close": "Close",
        "update_installed_toast": "{app} was updated to v{version}.",
        "update_err_unsafe_url": "Unsafe download address.",
        "update_err_checksum_invalid": "The update checksum is invalid (SHA-256 expected).",
        "update_err_checksum_mismatch": "File integrity check failed (checksum).",
        "update_err_redirect": "The update server redirected to an insecure (non-https) address.",
        "update_err_incomplete": "The download was cut off before it finished.",
        "update_err_not_found": "The update file was not found.",
        "update_err_http": "The server returned an error (HTTP {code}).",
        "update_err_network": "Could not reach the server. Check your internet connection and try again.",
        "update_err_unsupported_os": "Automatic installation is not supported on this system.",
        "update_err_unsupported_source": "Automatic installation only works in the packaged app (exe), not when running from source.",
        "update_pkg_read": "The package could not be read: {detail}",
        "update_pkg_not_package": "The downloaded file is neither an exe nor a zip.",
        "update_pkg_too_big": "The package is larger than allowed.",
        "update_pkg_no_exe": "The package does not contain the application's exe.",
        "update_pkg_bad_zip": "The zip file is corrupt: {detail}",
        "update_pkg_write": "The new version could not be written to the application folder: {detail}",
        "update_pkg_not_pe": "The file in the package is not a valid application file.",
        "update_pkg_arch": "The package was built for a different processor architecture.",
        "update_pkg_not_writable": "Cannot write to the application folder ({detail}). Move the app to a writable folder (e.g. Documents or Desktop) and open it again.",
        "update_pkg_swap": "The running application file could not be replaced: {detail}",
        "update_pkg_swap2": "The new version could not be put in place: {detail}",
        "update_pkg_spawn": "The new version could not be started: {detail}",
        "profile_quality": "High Quality",
        "codec_h264_desc": "H.264 — opens everywhere",
        "codec_hevc_desc": "H.265 (HEVC) — smaller",
        "codec_av1_desc": "AV1 — smallest",
        "video_codec": "Video Codec",
        "codec_h264_hint": "Opens on every phone, TV and app (WhatsApp too). Recommended.",
        "codec_hevc_hint": "10–35% smaller than H.264 at the same quality. iPhone, newer Android phones and Macs open it; some players need the HEVC extension (VLC opens it).",
        "codec_av1_hint": "Smallest file (down to half of H.264). Newer devices and browsers open it; older TVs and phones may not.",
        "bitrate_auto_desc": "Auto — based on quality (CRF)",
        "bitrate_1500k_desc": "1500k — small file",
        "bitrate_2000k_desc": "2000k — recommended",
        "bitrate_2500k_desc": "2500k — high",
        "bitrate_4000k_desc": "4000k — maximum",
        "res_original": "Original",
        "stopping": "Stopping…",
        "files_progress": "{done}/{total} files",
        "stats_elapsed": "elapsed {elapsed}",
        "stats_elapsed_remaining": "elapsed {elapsed}  ·  remaining ~{remaining}",
        "job_summary": "{title} — succeeded {ok} · skipped {skip} · failed {fail}",
        "summary_cancelled": "Cancelled",
        "summary_completed": "Completed",
        "msg_open_folder_failed": "Could not open folder:\n{}",
        "msg_open_location_failed": "Could not open location:\n{}",
        "msg_open_file_failed": "Could not open file:\n{}",
        "msg_create_folder_failed": "Could not create folder:\n{}\n{}",
        "msg_ffmpeg_needed": "FFmpeg is required for video. Click Download FFmpeg or install FFmpeg.",
        "msg_ffmpeg_needed_macos": "FFmpeg is required for video. Run \"brew install ffmpeg\" in Terminal, then click Scan Again.",
        "msg_ffmpeg_needed_linux": "FFmpeg is required for video. Install it with \"sudo apt install ffmpeg\" (or your distribution's package manager), then click Scan Again.",
        "msg_install_after_done": "Installation will begin after compression finishes.",
        "gpu_none_hint": "No FFmpeg — only images can be compressed",
        "queue_remove_tooltip": "Remove selected from queue (Del). Original file is not deleted.",
        "panel_hide": "Hide the settings panel (wider queue)",
        "panel_show": "Show the settings panel",
        "log_unexpected_error": "Unexpected error: {error}",
        "log_no_files": "No files of the selected type to process.",
        "log_stale_cleaned": "Removed {count} leftover temporary file(s).",
        "log_job_start": "Found {total} file(s). Starting compression…",
        "log_skipped_exists": "Skipped (already exists): {name}",
        "log_file_error": "Error ({name}): {error}",
        "log_image_done": "Image [{done}/{total}]: {name} ({size_in} → {size_out} | -{pct})",
        "log_stopped": "Stopped.",
        "log_container_switch": "{name}: {ext} can't carry this codec ({codec}) properly; it will be saved as {target}",
        "log_no_ffmpeg": "No FFmpeg, video skipped",
        "log_no_ffmpeg_file": "No FFmpeg, video skipped: {name}",
        "log_video_start": "Video [{done}/{total}]: {name} …",
        "log_video_done": "Done [{method}]: {name} ({size_in} → {size_out} | -{pct} | {elapsed})",
        "log_original_kept": "original kept",
        "log_video_error": "Video error ({name}): {error}",
        "image_res_tip": "Limits the longest edge. Smaller images (e.g. 2000px) are never upscaled, preserving original resolution.",
        "video_res_tip": "Sets the maximum video resolution (e.g. 1080p Full HD). Smaller videos are never upscaled.",
        "profile_balanced_tip": "Balanced compression: Ideal for general use & archiving (CRF 24, 1080p / 2400px, 90% Quality).",
        "profile_fast_tip": "Quick share: Lightweight for WhatsApp, Discord & social media (CRF 26, 1080p / 1920px, 85% Quality).",
        "profile_quality_tip": "High quality: CRF 20, original video resolution and 3840px image with near-lossless archival quality (95% Quality).",
        "profile_custom_tip": "Custom: Freely adjust all resolution, codec, bitrate and quality parameters.",
        "preview_btn": "Live Preview / Compare",
        "preview_tooltip": "Adjust compression quality live. Hold Space key to compare original vs compressed instantly.",
        "preview_dialog_title": "Live Quality Preview & Comparison",
        "preview_hint": "Adjust quality and format. Hold [Space] key to view original!",
        "preview_toggle_btn": "Original (Space)",
        "preview_apply_btn": "Apply This Quality",
        "preview_save_btn": "Save As…",
        "preview_badge_orig": "ORIGINAL (Space Held)",
        "preview_badge_comp": "COMPRESSED",
        "preview_quality_label": "Quality: {}%",
        "preview_res_label": "Max Resolution",
        "preview_change_img": "Choose Another Image",
        "custom_option": "Custom…",
        "custom_res_title_video": "Custom Video Resolution",
        "custom_res_prompt_video": "Enter the maximum video width in pixels (px):\n(e.g. 1920 = 1080p, 1280 = 720p, 2560 = 1440p, 3840 = 4K)",
        "custom_res_title_image": "Custom Maximum Resolution",
        "custom_res_prompt_image": "Maximum edge size (pixels):",
        "log_started": "Started — {codec} / {bitrate} / GPU:{gpu}",
        "log_prepare_error": "Preparation error: {}",
        "log_ffmpeg_downloading": "Downloading FFmpeg…",
        "log_ffmpeg_ready": "FFmpeg ready: {}",
        "preview_frame_label": "Frame",
        "preview_pick_video": "Choose Video",
        "preview_pick_other_video": "Choose Another Video",
        "preview_pick_image": "Choose Image",
        "preview_format_label": "Format",
        "preview_format_tip": "Compression format: JPEG, WebP, AVIF or JPEG XL (JXL).",
        "preview_toggle_tip": "Hold to view the original. You can also hold the [Space] key to compare.",
        "preview_no_file": "No file selected",
        "preview_calculating": "Calculating…",
        "preview_calculating_frame": "Calculating frame…",
        "preview_calculating_fmt": "Calculating {fmt}…",
        "preview_loading_frame": "Loading frame ({time})…",
        "preview_empty_title": "Choose an image or video",
        "preview_empty_hint": "Use the Choose Image or Choose Video button above\nto compare quality live.",
        "preview_badge_frame": "COMPRESSED FRAME",
        "preview_lbl_video": "Video",
        "preview_lbl_orig_frame": "Original Frame",
        "preview_lbl_comp_frame": "Compressed Frame",
        "preview_lbl_frame_savings": "Frame Savings",
        "preview_lbl_orig": "Original",
        "preview_lbl_savings": "Savings",
        "preview_filter_images": "Image Files",
        "preview_filter_videos": "Video Files",
        "preview_filter_all": "All Files",
        "preview_saved_title": "Success",
        "preview_saved_text": "File saved:\n{}",
        "preview_error_title": "Error",
        "preview_frame_failed": "Could not get a frame from the video (FFmpeg may not be ready).",
        "preview_open_failed": "Could not open image:\n{}",
        "preview_save_failed": "Could not save:\n{}",
    },
}

SUPPORTED_LANGUAGES: tuple[str, ...] = tuple(LOCALES.keys())
FALLBACK_LANGUAGE = "tr"
AUTO_LANGUAGE = "auto"

LANGUAGE_NAMES: dict[str, str] = {
    "tr": "Türkçe",
    "en": "English",
}

_FLAG_ICONS_CACHE: dict[str, Any] = {}


def create_language_icon(code: str = "auto") -> Any:
    """Windows emoji bayrakları desteklemediği için gerçek vektörel bayrak ikonu döner."""
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QPainterPath, QPolygonF, QPen
    from PyQt6.QtCore import Qt, QPointF, QRectF
    import math

    if QApplication.instance() is None:
        from PyQt6.QtGui import QIcon
        return QIcon()

    raw_key = (code or "auto").lower()
    is_auto = raw_key in ("auto", "", "none")

    if is_auto:
        detected = get_system_language() or "tr"
        code_key = (detected or "tr").lower()
        cache_key = f"auto_{code_key}"
    else:
        code_key = raw_key
        cache_key = code_key

    if cache_key in _FLAG_ICONS_CACHE:
        return _FLAG_ICONS_CACHE[cache_key]

    w, h = 48, 32
    pix = QPixmap(w, h)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    clip = QPainterPath()
    clip.addRoundedRect(QRectF(1.0, 1.0, w - 2, h - 2), 5.0, 5.0)
    p.setClipPath(clip)

    if code_key == "tr":
        p.fillRect(QRectF(0, 0, w, h), QColor("#E30A17"))

        # Hilal
        c_outer = QPainterPath()
        c_outer.addEllipse(QPointF(w * 0.38, h * 0.5), h * 0.32, h * 0.32)
        c_inner = QPainterPath()
        c_inner.addEllipse(QPointF(w * 0.45, h * 0.5), h * 0.25, h * 0.25)
        p.fillPath(c_outer.subtracted(c_inner), QColor("#ffffff"))

        # Yıldız
        star_center = QPointF(w * 0.63, h * 0.5)
        star_r_out = h * 0.14
        star_r_in = star_r_out * 0.382
        pts = []
        angle_offset = -math.pi / 2
        for i in range(10):
            r = star_r_out if i % 2 == 0 else star_r_in
            a = angle_offset + i * math.pi / 5
            pts.append(QPointF(star_center.x() + r * math.cos(a), star_center.y() + r * math.sin(a)))
        star_path = QPainterPath()
        star_path.addPolygon(QPolygonF(pts))
        p.fillPath(star_path, QColor("#ffffff"))

    elif code_key in ("en", "us"):
        stripe_h = h / 7.0
        for i in range(7):
            col = QColor("#B22234") if i % 2 == 0 else QColor("#FFFFFF")
            p.fillRect(QRectF(0, i * stripe_h, w, stripe_h + 0.5), col)
        canton_w = w * 0.45
        canton_h = stripe_h * 4.0
        p.fillRect(QRectF(0, 0, canton_w, canton_h), QColor("#3C3B6E"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        for r in range(2):
            for c in range(3):
                sx = canton_w * 0.2 + c * (canton_w * 0.3)
                sy = canton_h * 0.28 + r * (canton_h * 0.44)
                p.drawEllipse(QPointF(sx, sy), 1.4, 1.4)
    else:
        p.fillRect(QRectF(0, 0, w, h), QColor("#1e293b"))
        cx, cy = w / 2.0, h / 2.0
        r = min(w, h) * 0.4
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#0ea5e9"))
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.setPen(QPen(QColor("#ffffff"), 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(cx - r, cy), QPointF(cx + r, cy))
        p.drawLine(QPointF(cx, cy - r), QPointF(cx, cy + r))
        p.drawEllipse(QPointF(cx, cy), r * 0.5, r)

    # Otomatik mod rozeti (Sağ üst köşede şık mavi mini küre)
    if is_auto:
        p.setClipping(False)
        badge_cx, badge_cy, badge_r = w - 8.5, 8.5, 5.5
        p.setPen(QPen(QColor("#ffffff"), 1.2))
        p.setBrush(QColor("#0284c7"))
        p.drawEllipse(QPointF(badge_cx, badge_cy), badge_r, badge_r)
        p.setPen(QPen(QColor("#ffffff"), 0.9))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(badge_cx - badge_r + 1.0, badge_cy), QPointF(badge_cx + badge_r - 1.0, badge_cy))
        p.drawLine(QPointF(badge_cx, badge_cy - badge_r + 1.0), QPointF(badge_cx, badge_cy + badge_r - 1.0))
        p.drawEllipse(QPointF(badge_cx, badge_cy), badge_r * 0.5, badge_r * 0.9)

    # Açık ve koyu temalarda sınırları belirginleştiren zarif kontur
    p.setClipping(False)
    p.setPen(QPen(QColor(15, 23, 42, 70), 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(1.0, 1.0, w - 2, h - 2), 5.0, 5.0)

    p.end()
    icon = QIcon(pix)
    _FLAG_ICONS_CACHE[cache_key] = icon
    return icon


def language_display_name(code: str) -> str:
    native = LANGUAGE_NAMES.get(code, code.upper())
    code_label = "US" if code == "en" else code.upper()
    return f"{code_label} · {native}"


_LANGUAGE_NAME_TO_CODE: dict[str, str] = {
    "turkce": "tr",
    "türkçe": "tr",
    "turkish": "tr",
    "turk": "tr",
    "english": "en",
    "ingilizce": "en",
    "german": "de",
    "deutsch": "de",
    "almanca": "de",
    "french": "fr",
    "francais": "fr",
    "français": "fr",
    "fransizca": "fr",
    "fransızca": "fr",
    "spanish": "es",
    "espanol": "es",
    "español": "es",
    "ispanyolca": "es",
    "italian": "it",
    "italiano": "it",
    "italyanca": "it",
}

_WIN_PRIMARY_LANG_TO_CODE: dict[int, str] = {
    0x1F: "tr",
    0x09: "en",
    0x07: "de",
    0x0C: "fr",
    0x0A: "es",
    0x10: "it",
    0x13: "nl",
    0x19: "ru",
    0x01: "ar",
}


def _normalize_lang_code(raw: str | None) -> str | None:
    """'tr-TR', 'tr_TR.UTF-8', 'Turkish_Turkiye', 'tr:en_US:en' gibi girdilerden dil kodu çıkarır."""
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip().lower()
    if not s or s in ("c", "c.utf8", "c.utf-8", "posix"):
        return None
    if ":" in s or ";" in s:
        for part in s.replace(";", ":").split(":"):
            code = _normalize_lang_code(part)
            if code:
                return code
        return None
    for sep in (".", "@"):
        if sep in s:
            s = s.split(sep, 1)[0]
    s = s.strip()
    if not s:
        return None
    if s in _LANGUAGE_NAME_TO_CODE:
        cand = _LANGUAGE_NAME_TO_CODE[s]
        if cand in LOCALES:
            return cand
    tokens = s.replace("-", "_").split("_")
    if not tokens:
        return None
    first = tokens[0].strip()
    if first in _LANGUAGE_NAME_TO_CODE:
        first = _LANGUAGE_NAME_TO_CODE[first]
    if first in LOCALES:
        return first
    return None


def _locale_code_from_system() -> str | None:
    """Windows / macOS / Linux'ta gerçek arayüz dilini tespit eder."""
    # Windows'ta Qt'nin bölgesel ayarı, Windows görüntüleme dilinden
    # farklı olabilir. Görüntüleme dilini doğrudan Win32 API'den öncele.
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            for func in ("GetUserDefaultUILanguage", "GetSystemDefaultUILanguage"):
                try:
                    lcid = int(getattr(kernel32, func)())
                    code = _WIN_PRIMARY_LANG_TO_CODE.get(lcid & 0x3FF)
                    if code and code in LOCALES:
                        return code
                except Exception:
                    continue
            buf = ctypes.create_unicode_buffer(85)
            if kernel32.GetUserDefaultLocaleName(buf, 85):
                code = _normalize_lang_code(buf.value)
                if code:
                    return code
        except Exception:
            pass

    for env in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        try:
            val = os.environ.get(env)
            if val:
                for part in val.replace(";", ":").split(":"):
                    code = _normalize_lang_code(part)
                    if code:
                        return code
        except Exception:
            pass
    try:
        from PyQt6.QtCore import QLocale
        ql = QLocale.system()
        try:
            for ui_lang in (ql.uiLanguages() or []):
                code = _normalize_lang_code(ui_lang)
                if code:
                    return code
        except Exception:
            pass
        for candidate in (ql.bcp47Name(), ql.name()):
            try:
                code = _normalize_lang_code(candidate)
            except Exception:
                code = None
            if code:
                return code
    except Exception:
        pass
    try:
        if sys.platform == "win32":
            import ctypes
            try:
                kernel32 = ctypes.windll.kernel32
                for func in ("GetUserDefaultUILanguage", "GetSystemDefaultUILanguage"):
                    try:
                        lcid = int(getattr(kernel32, func)())
                        code = _WIN_PRIMARY_LANG_TO_CODE.get(lcid & 0x3FF)
                        if code and code in LOCALES:
                            return code
                    except Exception:
                        continue
                try:
                    buf = ctypes.create_unicode_buffer(85)
                    if kernel32.GetUserDefaultLocaleName(buf, 85):
                        code = _normalize_lang_code(buf.value)
                        if code:
                            return code
                except Exception:
                    pass
            except Exception:
                pass
    except Exception:
        pass
    try:
        if sys.platform == "darwin":
            import subprocess
            try:
                out = subprocess.check_output(
                    ["defaults", "read", "-g", "AppleLanguages"],
                    text=True, timeout=2,
                )
                import re
                for m in re.findall(r'"([^"]+)"', out or ""):
                    code = _normalize_lang_code(m)
                    if code:
                        return code
            except Exception:
                pass
    except Exception:
        pass
    try:
        try:
            loc = locale.getlocale()[0] or ""
            code = _normalize_lang_code(loc)
            if code:
                return code
        except Exception:
            pass
        try:
            loc2 = (locale.getdefaultlocale()[0] or "")
            code = _normalize_lang_code(loc2)
            if code:
                return code
        except Exception:
            pass
    except Exception:
        pass
    return None


def get_system_language() -> str:
    """Sistem dilini desteklenen kodlardan birine çözümler."""
    return _locale_code_from_system() or FALLBACK_LANGUAGE


def _resolve_language_choice(value: str | None) -> str:
    if value and value != AUTO_LANGUAGE and value in LOCALES:
        return value
    return get_system_language()


# Kullanıcının SEÇTİĞİ arayüz dili: `get_active_language(config)` her çözümlediğinde güncellenir. `t(key)` dil verilmezse
# sistem dilini değil bunu kullanır (eskiden parametresiz çağrılar sistem dilinde çıkıyordu).
_ui_language: str | None = None


def set_ui_language(code: str | None) -> None:
    """Etkin arayüz dilini elle ayarla (None: sistem diline dön)."""
    global _ui_language
    _ui_language = code if code in LOCALES else None


def get_active_language(config_or_lang: Any = None) -> str:
    """Yapılandırma ayarına göre etkin dili döner; argümansız çağrıda kullanıcının seçtiği dili (yoksa sistem dilini)."""
    global _ui_language
    if isinstance(config_or_lang, str):
        return _resolve_language_choice(config_or_lang)
    if hasattr(config_or_lang, "get"):
        resolved = _resolve_language_choice(config_or_lang.get("language", AUTO_LANGUAGE))
        _ui_language = resolved
        return resolved
    return _ui_language or get_system_language()


def language_choices(
    include_auto: bool = False,
    lang: str | None = None,
) -> list[tuple[str, str]]:
    """Dil seçici için (kod, etiket) çiftleri döner."""
    detected = get_system_language()
    active = lang or detected
    choices: list[tuple[str, str]] = []
    if include_auto:
        base = t("lang_auto", active)
        detected_label = language_display_name(detected)
        if base.endswith(")"):
            auto_label = f"{base[:-1]} - {detected_label})"
        else:
            auto_label = f"{base} - {detected_label}"
        choices.append((AUTO_LANGUAGE, auto_label))
    for code in LOCALES.keys():
        choices.append((code, language_display_name(code)))
    return choices


def t(key: str, lang: str | None = None) -> str:
    """Belirtilen dilde (verilmezse kullanıcının seçtiği dilde) metni döner; bulunamazsa TR ve ardından anahtarın kendisini döner."""
    if lang is None:
        lang = _ui_language or get_system_language()
    table = LOCALES.get(lang) or LOCALES[FALLBACK_LANGUAGE]
    return table.get(key, LOCALES[FALLBACK_LANGUAGE].get(key, key))


def get_app_name(lang: str = "tr") -> str:
    return t("app_name", lang)


def get_output_folder_name(lang: str = "tr") -> str:
    return t("output_folder_default", lang)


_qt_translators: list = []


def install_qt_translations(lang: str | None = None) -> None:
    """Qt'nin kendi yazılarını (Tamam / İptal / Evet / Hayır, metin kutusu sağ tık menüsü…) uygulama diline çevirir.

    Paketlenmiş uygulamada da çalışır: PyInstaller Qt çevirilerini (`qtbase_*.qm`) pakete koyar. Çeviri
    dosyası bulunamazsa sessizce İngilizce kalır; her çağrı öncekini kaldırıp yenisini kurar.
    """
    try:
        from PyQt6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QTranslator
    except ImportError:
        return
    app = QCoreApplication.instance()
    if app is None:
        return
    for old in _qt_translators:
        try:
            app.removeTranslator(old)
        except RuntimeError:  # önceki QApplication yok edilmiş (testler, yeniden başlatma)
            pass
    _qt_translators.clear()
    code = lang or get_system_language()
    folders = [QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)]
    bundle = getattr(sys, "_MEIPASS", "")
    if bundle:
        folders.append(os.path.join(bundle, "PyQt6", "Qt6", "translations"))
    for folder in folders:
        translator = QTranslator(app)
        if translator.load(QLocale(code), "qtbase", "_", folder):
            app.installTranslator(translator)
            _qt_translators.append(translator)
            break
    _install_key_names(app)


def _install_key_names(app) -> None:
    """Kısayol adlarını (menülerdeki "Ctrl+Shift+N") çevirmeden bırakır.

    Qt'nin Türkçe çevirisi bunları "Kontrol+Üst Karakter+N" yapıyordu; klavyedeki tuşlar ise Ctrl/Shift/Alt
    yazar. En son kurulan çevirici önce sorulduğu için bu, qtbase çevirisinin "QShortcut" bölümünü geçersiz
    kılar. macOS'ta Qt zaten ⌘⇧N gibi simgeler kullanır, bunun etkisi olmaz.
    """
    from PyQt6.QtCore import QTranslator

    class _KeyNames(QTranslator):
        def isEmpty(self) -> bool:  # noqa: N802
            return False

        def translate(self, context, source_text, disambiguation=None, n=-1):
            return source_text if context == "QShortcut" else None

    translator = _KeyNames()  # parent'sız: uygulama yok edilince C++ tarafı Python'dan önce silinmesin
    app.installTranslator(translator)
    _qt_translators.append(translator)
