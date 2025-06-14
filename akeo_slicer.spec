# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['akeo_slicer.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('icon.ico', '.'),       # 아이콘 파일 포함
        ('icon.png', '.'),       # PNG 아이콘 파일 포함
    ],
    hiddenimports=[
        'PIL._tkinter_finder',
        'psd_tools',
        'requests',
        'urllib3',
        'certifi',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
        'jupyter',
        'IPython',
        'tornado',
        'zmq',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='akeo_slicer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,  # UPX 압축 사용
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 콘솔 창 숨김
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',  # 실행 파일 아이콘
    version='version_info.txt',  # 버전 정보 파일
) 