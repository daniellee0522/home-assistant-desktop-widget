; Fixed AppId preserves the installation identity across releases.
#ifndef AppVersion
  #define AppVersion "1.1.1"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\" + AppVersion + "\HA Widgets"
#endif
#ifndef ReleaseDir
  #define ReleaseDir "..\dist\" + AppVersion
#endif
#define AppName "HA Widgets"
#define AppExe "HA Widgets.exe"

[Setup]
AppId={{8C1B2D4E-6F3A-4B5C-9E7D-1A2B3C4D5E6F}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=HA Widgets
DefaultDirName={code:DefaultInstallDir}
DefaultGroupName={#AppName}
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableFinishedPage=yes
PrivilegesRequired=lowest
OutputDir={#ReleaseDir}
OutputBaseFilename=HA-Widgets-Setup-{#AppVersion}
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
UsePreviousAppDir=not TestInstall
Uninstallable=not TestInstall
CloseApplications=force
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no
SetupMutex=HAWidgetsSetup

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "ha_widgets_config.json,widget.log,hang_report.txt"

[InstallDelete]
; Remove incompatible Poppler ICU accidentally shipped in version 1.1.0.
Type: files; Name: "{app}\_internal\icuuc.dll"
Type: files; Name: "{app}\_internal\icudt78.dll"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; Check: not TestInstall
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Check: ExistingStartupShortcut

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "HAWidgets"; ValueData: """{app}\{#AppExe}"""; Flags: uninsdeletevalue; Check: ExistingStartupValue

[Run]
Filename: "{app}\{#AppExe}"; Flags: nowait skipifsilent; Check: ShouldLaunch

[Code]
function TestInstall: Boolean;
begin
  Result := ExpandConstant('{param:testinstall|0}') = '1';
end;

function ShouldLaunch: Boolean;
begin
  Result := (not TestInstall) and (ExpandConstant('{param:nolaunch|0}') <> '1');
end;

function ExistingStartupShortcut: Boolean;
begin
  Result := False;
  if not TestInstall then
    Result := FileExists(ExpandConstant('{userstartup}\{#AppName}.lnk'));
end;

function ExistingStartupValue: Boolean;
var
  Command: String;
begin
  Result := False;
  if not TestInstall then
    Result := RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run',
      'HAWidgets', Command) and (Command <> '');
end;

function DefaultInstallDir(Param: String): String;
begin
  if TestInstall then begin
    Result := ExpandConstant('{param:dir|{tmp}\HAWidgetsInstallerTest}');
    exit;
  end;
  { Reuse the directory used by the previous PowerShell installer, if present. }
  Result := ExpandConstant('{localappdata}\HA Widgets');
  if not FileExists(Result + '\{#AppExe}') then
    Result := ExpandConstant('{localappdata}\Programs\HA Widgets');
end;

function SettingsDir: String;
begin
  if TestInstall then
    Result := ExpandConstant('{app}\test-user-data')
  else
    Result := ExpandConstant('{userappdata}\HA Widgets');
end;

procedure MigrateSettings;
var
  Destination, Source: String;
begin
  Destination := SettingsDir + '\ha_widgets_config.json';
  { Never replace existing settings or include tokens in the installer. }
  if FileExists(Destination) then exit;
  Source := ExpandConstant('{app}\ha_widgets_config.json');
  if not FileExists(Source) then
    Source := ExpandConstant('{app}\_internal\ha_widgets_config.json');
  if (not FileExists(Source)) and (not TestInstall) then
    Source := ExpandFileName(ExpandConstant('{src}\..\ha_widgets_config.json'));
  if (not FileExists(Source)) and (not TestInstall) then
    Source := ExpandFileName(ExpandConstant('{src}\..\..\ha_widgets_config.json'));
  if FileExists(Source) then begin
    if not ForceDirectories(SettingsDir) then
      RaiseException('Unable to create the settings directory.');
    if not FileCopy(Source, Destination, True) then
      RaiseException('Unable to migrate the existing settings.');
    Log('Existing settings migrated; original file preserved.');
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then MigrateSettings;
end;
