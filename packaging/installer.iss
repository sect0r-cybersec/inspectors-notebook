; Inno Setup script for the companion (NFR-9): a per-user install with no admin rights.
;
;     packaging/build.ps1 builds the app folder first, then compiles this with
;     ISCC /DAppVersion=<version from pyproject.toml>.
;
; The browser extension is not in the installer: it installs from each browser's store,
; by sideloading or through enterprise policy.

#ifndef AppVersion
  #error Pass /DAppVersion=x.y.z (packaging/build.ps1 does)
#endif

#define AppName "Inspector's Notebook"
#define AppExe "inspectors-notebook.exe"
#define RegisterExe "inspectors-notebook-register.exe"

[Setup]
; Fixed for every release so upgrades replace the same install.
AppId={{6C1F3E0A-8D52-4B7E-9A64-2F0D5C9B7E31}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Sam
AppPublisherURL=https://github.com/sect0r-cybersec/inspectors-notebook
; Per user: %LOCALAPPDATA%\Programs, no UAC prompt (NFR-5).
PrivilegesRequired=lowest
DefaultDirName={autopf}\InspectorsNotebook
DisableProgramGroupPage=yes
DisableDirPage=auto
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Windows 10 1809, the oldest release WebView2 supports.
MinVersion=10.0.17763
SetupIconFile=..\build\inspectors-notebook.ico
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
OutputDir=..\dist
OutputBaseFilename=InspectorsNotebook-{#AppVersion}-setup
; Close a running companion (and a relay a browser has open) before replacing files.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\InspectorsNotebook\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; An upgrade replaces the whole runtime, so no stale modules from the last version are left.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Start with Windows is a setting the app writes (FR-38); remove it with the app.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "InspectorsNotebook"; Flags: uninsdeletevalue dontcreatekey

[Run]
; Register the relay with Chrome, Edge, Chromium and Firefox for this user.
Filename: "{app}\{#RegisterExe}"; Parameters: "install"; StatusMsg: "Registering with your browsers..."; Flags: runhidden waituntilterminated
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\{#RegisterExe}"; Parameters: "uninstall"; RunOnceId: "UnregisterRelay"; Flags: runhidden waituntilterminated

[Code]
// Cases and settings are the analyst's notes, so they stay unless the analyst says otherwise.
// A silent uninstall keeps them.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    if SuppressibleMsgBox('Also delete your saved cases and settings?' + #13#10#13#10 +
        ExpandConstant('{localappdata}\InspectorsNotebook') + #13#10 +
        ExpandConstant('{userappdata}\InspectorsNotebook'),
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
    begin
      DelTree(ExpandConstant('{localappdata}\InspectorsNotebook'), True, True, True);
      DelTree(ExpandConstant('{userappdata}\InspectorsNotebook'), True, True, True);
    end;
end;
