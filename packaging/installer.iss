; Inno Setup script for the Windows installer. Built by .github/workflows/release.yml:
;   iscc /DAppVersion=0.3.0 packaging\installer.iss
; Installs per user (no admin prompt) into %LOCALAPPDATA%\Programs\mtgasim.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6B0E9B7C-4C1E-4F6B-9D0B-6B1C2C5D7A31}
AppName=mtgasim
AppVersion={#AppVersion}
AppPublisher=mtgasim
AppPublisherURL=https://github.com/roodolpha/MTGASIM
DefaultDirName={localappdata}\Programs\mtgasim
DefaultGroupName=mtgasim
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=mtgasim-setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
UninstallDisplayIcon={app}\mtgasim.exe

[Tasks]
Name: "startup"; Description: "Start with Windows (records your Arena games in the background)"; Flags: unchecked
Name: "desktopicon"; Description: "Desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\mtgasim\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\mtgasim"; Filename: "{app}\mtgasim.exe"
Name: "{group}\Uninstall mtgasim"; Filename: "{uninstallexe}"
Name: "{userdesktop}\mtgasim"; Filename: "{app}\mtgasim.exe"; Tasks: desktopicon
Name: "{userstartup}\mtgasim"; Filename: "{app}\mtgasim.exe"; Parameters: "--background"; Tasks: startup

[Run]
Filename: "{app}\mtgasim.exe"; Description: "Open mtgasim now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM mtgasim.exe /F"; Flags: runhidden; RunOnceId: "StopApp"
