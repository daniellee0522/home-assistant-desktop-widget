; Inno Setup script for HA Widgets.
;
;   python packaging\build.py
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
;
; Produces dist\HA-Widgets-Setup.exe. Installs per user, so it needs no
; administrator: the program is a desktop gadget, it writes its settings
; under %APPDATA%, and asking for elevation to put a widget on someone's
; own desktop is asking for too much.

#define AppName "HA Widgets"
#define AppVersion "1.0.0"
#define AppPublisher "HA Widgets"
#define AppExe "HA Widgets.exe"

[Setup]
AppId={{8C1B2D4E-6F3A-4B5C-9E7D-1A2B3C4D5E6F}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=HA-Widgets-Setup
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinesetrad"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "建立桌面捷徑"; GroupDescription: "捷徑:"; Flags: unchecked
Name: "startup"; Description: "開機時自動啟動"; GroupDescription: "啟動:"

[Files]
Source: "..\dist\HA Widgets\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "立即啟動 {#AppName}"; Flags: nowait postinstall skipifsilent
