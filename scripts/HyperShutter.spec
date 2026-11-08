# PyInstaller spec for HyperShutter.app (run through scripts/build_app.sh).
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent
datas = [(str(ROOT / "presets"), "presets"), (str(ROOT / "ui"), "ui"),
         (str(ROOT / "THIRD_PARTY_LICENSES.md"), ".")]
binaries = []
hiddenimports = ["webview.platforms.cocoa"] + collect_submodules("hypershutter")
for pkg in ("mlx", "mlx_whisper", "sherpa_onnx", "webview", "tiktoken", "tiktoken_ext"):
    try:
        d, b, h = collect_all(pkg)
    except Exception:
        continue
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis([str(ROOT / "hypershutter" / "app" / "launch.py")], pathex=[str(ROOT)], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, excludes=["tkinter", "pytest", "IPython", "matplotlib", "torch", "torchvision", "torchaudio",
                       "transformers", "tensorflow", "jax", "pandas", "sympy"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="HyperShutter", console=False, argv_emulation=False,
          target_arch="arm64", upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="HyperShutter", upx=False)
app = BUNDLE(coll, name="HyperShutter.app", icon=str(ROOT / "build" / "HyperShutter.icns"),
             bundle_identifier="app.hypershutter.HyperShutter", version="0.1.0",
             info_plist={
                 "CFBundleName": "HyperShutter", "CFBundleDisplayName": "HyperShutter",
                 "CFBundleShortVersionString": "0.1.0", "CFBundleVersion": "0.1.0",
                 "LSMinimumSystemVersion": "13.0", "NSHighResolutionCapable": True,
                 "LSApplicationCategoryType": "public.app-category.video",
                 "NSRemovableVolumesUsageDescription": "HyperShutter reads your memory cards and footage drives to copy, verify and organize the footage.",
                 "NSDesktopFolderUsageDescription": "HyperShutter saves diagnostics you export to the Desktop.",
                 "NSDocumentsFolderUsageDescription": "HyperShutter opens event folders you choose.",
                 "NSDownloadsFolderUsageDescription": "HyperShutter opens event folders you choose.",
                 "NSNetworkVolumesUsageDescription": "HyperShutter can copy cards to network drives you choose.",
             })
