# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['ngt_studio.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['scipy', 'matplotlib', 'IPython', 'pytest', 'setuptools', 'pkg_resources', 'numpy.array_api'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NGT_Studio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='Z:/tmp/claude-0/-home-claude/3384afe8-67d5-5eae-998d-7a79e8706374/scratchpad/NGT_Studio_2.5.25_final/windows/version.txt',
    icon=['Z:/tmp/claude-0/-home-claude/3384afe8-67d5-5eae-998d-7a79e8706374/scratchpad/NGT_Studio_2.5.25_final/windows/ngt.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='NGT_Studio',
)
