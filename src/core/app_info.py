"""Uygulama kimliği — tek kaynak."""

APP_NAME = "Medya Sıkıştırıcı"
APP_ID = "MediaCompressor"
# Eski sürümlerin kimliği: ayar klasörü, indirilen ffmpeg ve başlangıç kaydı bu adla duruyor (geçiş için okunur).
LEGACY_APP_ID = "MedyaSikistirici"
VERSION = "1.0.1"
ORGANIZATION = "MediaCompressor"
UPDATE_CHECK_URL = "https://macik.com.tr/api/updates/check"
EXE_NAME = "MediaCompressor.exe"
LOCK_NAME = "MediaCompressor.lock"
SOCKET_NAME = "MediaCompressorSingleton"
LAUNCH_AGENT_LABEL = "com.mediacompressor"
OUTPUT_FOLDER_NAME = "sıkıştırılmış"

# "Otomatik bitrate" (CRF modu) sentineli. Eskiden yerelleştirilmiş sihirli dize "otomatik"
# her yerde karşılaştırılıyordu; kalıcı ayarlar ve profiller geriye uyum için hâlâ kabul edilir.
BITRATE_AUTO = "auto"
LEGACY_BITRATE_AUTO = ("otomatik",)


def is_auto_bitrate(value) -> bool:
    """Boş/None, ``BITRATE_AUTO`` veya eski ``"otomatik"`` değeri -> otomatik (CRF) mod."""
    if value is None:
        return True
    text = str(value).strip().lower()
    return text == "" or text == BITRATE_AUTO or text in LEGACY_BITRATE_AUTO


def normalize_bitrate(value) -> str:
    """Eski değeri yeni sabite çevir; sabit bitrate ("2000k") aynen kalır."""
    return BITRATE_AUTO if is_auto_bitrate(value) else str(value).strip()

# Güncelleme paketinin indirilebileceği sunucular (alan adı veya alt alan adı). Güncelleme
# sunucusu JSON'da başka bir CDN adresi verirse güvenli indirme reddedilir: gerekiyorsa buraya ekleyin.
UPDATE_ALLOWED_HOSTS = ("macik.com.tr",)

# Çözünürlük açılırlarındaki "Özel..." girdisinin öğe verisi (görünen metin dile göre çevrilir).
CUSTOM_RES = "__custom__"
