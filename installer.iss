; Inno Setup script: packs dist\FileRing into one release\FileRing-Setup.exe.
; Build with build.bat (it runs this after PyInstaller), or:
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer.iss
; Installs per user (no admin rights needed) into %LOCALAPPDATA%\Programs\FileRing.

#define AppName "FileRing"
; The release workflow passes the version from the git tag: ISCC /DAppVersion=1.2.3
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppExe "FileRing.exe"

[Setup]
AppId={{6B0E3C9A-4F2D-4C1B-9E7A-2D5F8A1C3B47}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppName}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=release
OutputBaseFilename=FileRing-Setup
SetupIconFile=build\FileRing.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "autostart"; Description: "Start FileRing when Windows starts"
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "dist\FileRing\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Remove files from an older version so leftovers don't pile up.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Same value FileRing's own Settings checkbox reads and writes.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
    ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"""; Flags: uninsdeletevalue; Tasks: autostart
; FileRing's settings: removed on uninstall.
Root: HKCU; Subkey: "Software\FileRing"; Flags: uninsdeletekey dontcreatekey

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start FileRing now"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
; Remove the "Convert with FileRing" right-click menu (FileRing writes it itself).
Filename: "{app}\{#AppExe}"; Parameters: "--unregister-shell"; Flags: runhidden; \
    RunOnceId: "RemoveShellMenu"
Filename: "{sys}\taskkill.exe"; Parameters: "/F /T /IM {#AppExe}"; Flags: runhidden; \
    RunOnceId: "StopFileRing"

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\FileRing"

[Code]
// Close a running FileRing (tray app and worker) before installing over it.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM {#AppExe}', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
  Result := '';
end;
