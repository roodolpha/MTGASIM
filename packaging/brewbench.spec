# PyInstaller spec for the Windows app: pyinstaller packaging/brewbench.spec
# Builds dist/brewbench/ (a folder app). Two exes: the windowed app and a console CLI.
import os

root = os.path.abspath(os.path.join(SPECPATH, ".."))
datas = [
    (os.path.join(root, "brewbench", "web"), "brewbench/web"),
    (os.path.join(root, "brewbench", "harness"), "brewbench/harness"),
]

app = Analysis([os.path.join(root, "packaging", "launch.py")], pathex=[root], datas=datas)
cli = Analysis([os.path.join(root, "packaging", "cli_launch.py")], pathex=[root], datas=datas)

app_pyz = PYZ(app.pure)
cli_pyz = PYZ(cli.pure)

app_exe = EXE(app_pyz, app.scripts, [], exclude_binaries=True, name="brewbench", console=False,
              icon=os.path.join(root, "packaging", "brewbench.ico") if os.path.exists(os.path.join(root, "packaging", "brewbench.ico")) else None)
cli_exe = EXE(cli_pyz, cli.scripts, [], exclude_binaries=True, name="brewbench-cli", console=True)

coll = COLLECT(app_exe, app.binaries, app.datas, cli_exe, cli.binaries, cli.datas, name="brewbench")
