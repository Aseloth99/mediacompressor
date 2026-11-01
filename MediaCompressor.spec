# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('assets', 'assets')]
binaries = []
hiddenimports = [
    'PyQt6', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets', 'PyQt6.QtNetwork',
    'PIL', 'PIL.Image', 'PIL.ImageOps', 'PIL.ImageDraw', 'PIL.ImageFile', 'piexif',
    'src.utils.crashlog', 'src.utils.notify', 'src.utils.locales'
]
tmp_ret = collect_all('piexif')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# JPEG XL: imagecodecs'in eklenti modulleri tembel (importlib) yuklenir, PyInstaller kendiliginden
# gormez; collect_all hepsini ve ikili dosyalarini paketler. numpy de GEREKLI (asagida dislanmaz).
tmp_ret = collect_all('imagecodecs')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

excludes = [
    'PyQt5', 'PySide2', 'PySide6',
    'PyQt6.QtWebEngine', 'PyQt6.QtWebEngineCore', 'PyQt6.QtWebEngineWidgets',
    'PyQt6.QtWebEngineQuick', 'PyQt6.QtWebChannel',
    'PyQt6.Qt3DAnimation', 'PyQt6.Qt3DCore', 'PyQt6.Qt3DExtras',
    'PyQt6.Qt3DInput', 'PyQt6.Qt3DLogic', 'PyQt6.Qt3DRender',
    'PyQt6.QtMultimedia', 'PyQt6.QtMultimediaWidgets',
    'PyQt6.QtQuick', 'PyQt6.QtQuick3D', 'PyQt6.QtQuickWidgets', 'PyQt6.QtQml',
    'PyQt6.QtBluetooth', 'PyQt6.QtCharts', 'PyQt6.QtDataVisualization',
    'PyQt6.QtLocation', 'PyQt6.QtPositioning', 'PyQt6.QtSensors',
    'PyQt6.QtSerialPort', 'PyQt6.QtSql', 'PyQt6.QtTest', 'PyQt6.QtXml',
    'PyQt6.QtDesigner', 'PyQt6.QtHelp', 'PyQt6.QtOpenGL', 'PyQt6.QtOpenGLWidgets',
    'PyQt6.QtSvg', 'PyQt6.QtSvgWidgets', 'PyQt6.QtNfc', 'PyQt6.QtRemoteObjects',
    'PyQt6.QtTextToSpeech', 'PyQt6.QtSpatialAudio', 'PyQt6.QtPdf', 'PyQt6.QtPdfWidgets',
    'PyQt6.QtDBus',
    # numpy BILEREK dislanmaz: JPEG XL (imagecodecs) goruntu<->dizi donusumu icin gerekir.
    'tkinter', 'matplotlib', 'pandas', 'scipy', 'cv2', 'torch',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MediaCompressor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\icons\\app_icon.ico'],
    version='version_info.txt',  # surum: src/core/app_info.py VERSION ile ayni olmali (testle denetlenir)
)
