# PyInstaller tanımı: motoru tek klasörlük (onedir) çalıştırılabilir pakete dönüştürür.
# Masaüstü uygulaması bu klasörü kaynak olarak paketler ve motoru buradan başlatır.
#   uv run --group packaging pyinstaller packaging/ati-engine.spec --noconfirm
# Tek dosya (onefile) yerine klasör: her açılışta geçici dizine açma olmaz, açılış hızlıdır ve
# virüs tarayıcılarının yanlış alarmları azalır.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("ati_engine")
    + ["websockets.asyncio.client", "websockets.asyncio.server"]
)
datas = collect_data_files("ati_engine", includes=["**/*.sql", "**/*.json"])

a = Analysis(
    ["entry.py"],
    pathex=[],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "IPython", "matplotlib", "talib"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ati-engine",
    console=True,  # kabuk pencere açmadan (CREATE_NO_WINDOW) başlatır; komut satırı için konsol
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="ati-engine", upx=False)
