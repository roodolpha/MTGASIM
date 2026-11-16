; Inno Setup script for the Windows installer. Built by .github/workflows/release.yml:
;   iscc /DAppVersion=0.3.0 packaging\installer.iss
; Installs per user (no admin prompt) into %LOCALAPPDATA%\Programs\brewbench.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6B0E9B7C-4C1E-4F6B-9D0B-6B1C2C5D7A31}
AppName=Brewbench
AppVersion={#AppVersion}
AppPublisher=brewbench
AppPublisherURL=https://github.com/roodolpha/brewbench
DefaultDirName={localappdata}\Programs\brewbench
DefaultGroupName=Brewbench
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=brewbench-setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
UninstallDisplayIcon={app}\brewbench.exe
SetupIconFile=brewbench.ico
; close a running copy before upgrading or removing it
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "startup"; Description: "Start with Windows (records your Arena games in the background)"; Flags: unchecked
Name: "desktopicon"; Description: "Desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\brewbench\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Brewbench"; Filename: "{app}\brewbench.exe"
Name: "{group}\Uninstall Brewbench"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Brewbench"; Filename: "{app}\brewbench.exe"; Tasks: desktopicon

[Registry]
; "Start with Windows": the same setting as the tick in the app's tray menu
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Brewbench"; ValueData: """{app}\brewbench.exe"" --background"; Tasks: startup
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "Brewbench"; Flags: uninsdeletevalue dontcreatekey

[Run]
Filename: "{app}\brewbench.exe"; Description: "Open Brewbench now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM brewbench.exe /F"; Flags: runhidden; RunOnceId: "StopApp"
