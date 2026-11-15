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
DefaultGroupName=brewbench
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=brewbench-setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
UninstallDisplayIcon={app}\brewbench.exe

[Tasks]
Name: "startup"; Description: "Start with Windows (records your Arena games in the background)"; Flags: unchecked
Name: "desktopicon"; Description: "Desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\brewbench\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\brewbench"; Filename: "{app}\brewbench.exe"
Name: "{group}\Uninstall brewbench"; Filename: "{uninstallexe}"
Name: "{userdesktop}\brewbench"; Filename: "{app}\brewbench.exe"; Tasks: desktopicon
Name: "{userstartup}\brewbench"; Filename: "{app}\brewbench.exe"; Parameters: "--background"; Tasks: startup

[Run]
Filename: "{app}\brewbench.exe"; Description: "Open Brewbench now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM brewbench.exe /F"; Flags: runhidden; RunOnceId: "StopApp"
