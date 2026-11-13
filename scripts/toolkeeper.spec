# PyInstaller spec (docs/design.md section 9.3). Build with scripts\build-exe.cmd.
# One onedir folder "ToolKeeper" with two exes that share _internal\:
#   toolkeeper.exe   console: commands whose output is read (RepoTether, the window's jobs)
#   toolkeeperw.exe  no console: the window ("gui") and the scheduled tasks ("--log check")
from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "scripts" / "exe_entry.py")],
    pathex=[str(ROOT / "src")],
    hiddenimports=["toolkeeper.gui"],
    excludes=["unittest", "pydoc", "test"],
)
pyz = PYZ(a.pure)


def exe(name, console):
    return EXE(pyz, a.scripts, [], exclude_binaries=True, name=name, console=console,
               upx=False, version=None, icon=None)


coll = COLLECT(exe("toolkeeper", True), exe("toolkeeperw", False), a.binaries, a.datas,
               name="ToolKeeper", upx=False)
