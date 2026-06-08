# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = []
# Bundle imgui_bundle's font assets (Roboto + Font Awesome 6). hello_imgui points
# its asset folder at <imgui_bundle>/assets at import time, so the fonts must live
# at _internal/imgui_bundle/assets/fonts in the frozen app — otherwise it falls
# back to the built-in ProggyClean font, which renders no icons (or the star glyph).
datas += collect_data_files('imgui_bundle', includes=['assets/fonts/**'])
binaries = [('C:/Python313/Lib/site-packages/_portaudiowpatch.cp313-win_amd64.pyd', '.'), ('C:/Python313/Lib/site-packages/imgui_bundle/glfw3.dll', 'imgui_bundle'), ('C:/Python313/Lib/site-packages/imgui_bundle/_imgui_bundle.cp313-win_amd64.pyd', 'imgui_bundle')]
hiddenimports = ['sounddevice', '_sounddevice_data', 'pyaudiowpatch', 'scipy.signal', 'scipy.signal.windows', 'glfw', 'app_icon_data']
tmp_ret = collect_all('_sounddevice_data')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pydantic')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pydantic_core')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'torchvision', 'torchaudio', 'onnxruntime', 'cv2', 'opencv', 'PIL', 'pygame', 'lxml', 'cryptography', 'Pythonwin', 'win32com', 'google', 'rapidfuzz', 'matplotlib', 'pandas', 'tkinter', '_tkinter', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'IPython', 'jedi', 'zmq', 'jupyter', 'notebook', 'nbformat'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SpectrumAnalyzer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='spectral.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='SpectrumAnalyzer',
)
