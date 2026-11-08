; Inno Setup 6/7 script for the portable CaiXiHui onedir build (compiled with ISCC.exe; the UTF-8
; BOM at the head of this file is what lets it carry Chinese -- Inno reads a BOM-less .iss as ANSI).
;
; Build the folder first:
;   powershell -ExecutionPolicy Bypass -File desktop\build_windows.ps1
; Then compile this file with ISCC.exe (the build script does it with -Installer).
;
; User data is NOT installed here and NOT deleted on uninstall: the app stores it in
; %APPDATA%\CaiXiHui (runs, datasets, cookies, exports, logs), which survives upgrades.
;
; The managed-install contract below mirrors the parts of anomalyco/hex's installer that are
; worth having without changing where the exe lives: stop ONLY the copy running from this
; install root, put a small console launcher on the user's PATH, and leave two atomically
; written, UTF-8 (no BOM) records of what was installed. We deliberately do NOT move the
; exe into versions\<v>\ : there is no in-app self-updater here (the online installer owns
; component versioning via its manifest), and app_dir()/data-root.txt/portable.txt all read
; the exe's own folder. versions\<v>\ holds the install receipt that current-version points at.

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppName "采析绘"
#define MyAppExeName "CaiXiHui.exe"

[Setup]
AppId={{8E1C6A2D-5E46-4C71-9A0B-6D0F7A2E9C11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=采析绘
VersionInfoVersion={#MyAppVersion}.0
VersionInfoProductName={#MyAppName}
VersionInfoDescription=采析绘 工作流采集与分析
DefaultDirName={localappdata}\Programs\CaiXiHui
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Request admin for the WHOLE Setup, loader included. Inno's loader extracts itself into the
; user's TEMP before the inner setup starts, so a machine whose policy denies %TEMP% writes to
; unsigned non-elevated processes failed with "unable to create the directory ... Error 5" and
; never reached the wizard. Elevating the manifest makes the loader run with the admin token,
; which is the one token that policy allows. Per-user paths ({localappdata}, HKCU PATH) stay
; per-user: UAC keeps the same account, and the app itself still runs without elevation.
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=CaiXiHui-Setup
SetupIconFile=..\backend\static\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/ultra64
SolidCompression=yes
; LZMAUseSeparateProcess was dropped in Inno Setup 7 (it prints
; "directive ... is obsolete and ignored"); separate-process compression is the default now.
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes
; AddBinToPath/RemoveBinFromPath touch HKCU\Environment; without this, terminals opened after
; the install would not see the change until sign-out.
ChangesEnvironment=yes

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: checkedonce

[Files]
Source: "..\dist\CaiXiHui\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Only bin\ goes on PATH, never the 150 MB folder with its 268 binaries. The .cmd launches the
; windowed exe with `start /wait`, so `CaiXiHui --doctor` answers in the calling terminal (the
; exe attaches to that console) and its exit code survives. It is ASCII by construction:
; SaveStringToFile writes the ANSI codepage.
Source: "bin\CaiXiHui.cmd"; DestDir: "{app}\bin"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动{#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Nothing: closing the app window is the normal shutdown; the server writes SQLite WAL
; files that must not be deleted by an uninstaller.

[UninstallDelete]
; Deliberately empty of user data: %APPDATA%\CaiXiHui is the user's data, not ours to delete.
; These four are OUR managed-install records and the PATH launcher, so they go.
Type: filesandordirs; Name: "{app}\bin"
Type: filesandordirs; Name: "{app}\versions"
Type: files; Name: "{app}\current-version"
Type: files; Name: "{app}\current-version.partial"

[Code]
{ A running installed copy holds the per-data-root instance lock and the files [Files] is
  about to replace. CloseApplications=yes uses the Restart Manager, which this launcher does
  not answer. Stop by EXECUTABLE PATH, not by name: a portable copy on a USB drive is a
  different install and must keep running. }
procedure StopManagedApp();
var
  Prefix, Quoted, Command: String;
  ResultCode: Integer;
begin
  Prefix := ExpandConstant('{app}\');
  Quoted := Prefix;
  StringChangeEx(Quoted, '''', '''''', True);
  Command := '-NoProfile -NonInteractive -WindowStyle Hidden -Command "'
    + 'Get-Process -Name ''CaiXiHui'' -ErrorAction SilentlyContinue | '
    + 'Where-Object { $_.Path -and $_.Path.StartsWith(''' + Quoted + ''', [StringComparison]::OrdinalIgnoreCase) } | '
    + 'Stop-Process -Force -ErrorAction SilentlyContinue; Start-Sleep -Milliseconds 500"';
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Command, '',
    SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopManagedApp();
  Result := '';
end;

{ Replaces Path with Contents through a .partial file. A power cut during the write must
  leave either the old record or a stray .partial, never half a version string. }
procedure WriteAtomically(Path, Contents: String);
var
  Partial: String;
begin
  Partial := Path + '.partial';
  DeleteFile(Partial);
  if not SaveStringToFile(Partial, Contents, False) then
    RaiseException('Could not write ' + Partial);
  DeleteFile(Path);
  if not RenameFile(Partial, Path) then
    RaiseException('Could not write ' + Path);
end;

{ current-version is pure ASCII, so SaveStringToFile's ANSI write is safe. install.json is
  NOT: a non-ASCII profile path in the install root would be written in the machine's codepage
  and the receipt would be unreadable UTF-8. anomalyco/hex hit exactly this (#1352). }
procedure WriteUtf8Atomically(Path, Contents: String);
var
  Partial: String;
  Lines: TArrayOfString;
begin
  Partial := Path + '.partial';
  DeleteFile(Partial);
  SetArrayLength(Lines, 1);
  Lines[0] := Contents;
  if not SaveStringsToUTF8FileWithoutBOM(Partial, Lines, False) then
    RaiseException('Could not write ' + Partial);
  DeleteFile(Path);
  if not RenameFile(Partial, Path) then
    RaiseException('Could not write ' + Path);
end;

{ Path entries, compared case-insensitively and ignoring a trailing backslash. }
function NormalPath(Path: String): String;
begin
  Result := ';' + AnsiLowercase(Path) + ';';
  StringChangeEx(Result, '\;', ';', True);
end;

function PathHas(Path, Folder: String): Boolean;
begin
  Result := Pos(';' + AnsiLowercase(Folder) + ';', NormalPath(Path)) > 0;
end;

procedure AddBinToPath();
var
  Path, Bin: String;
begin
  Bin := ExpandConstant('{app}\bin');
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', Path) then
    Path := '';
  if PathHas(Path, Bin) then
    exit;
  if (Path <> '') and (Copy(Path, Length(Path), 1) <> ';') then
    Path := Path + ';';
  RegWriteExpandStringValue(HKCU, 'Environment', 'Path', Path + Bin);
end;

procedure RemoveBinFromPath();
var
  Path, Bin, Entry, Kept: String;
  At: Integer;
begin
  Bin := ExpandConstant('{app}\bin');
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', Path) then
    exit;
  if not PathHas(Path, Bin) then
    exit;
  { Rebuilt without our entry; the comparison form loses the original case. }
  Path := Path + ';';
  Kept := '';
  while Path <> '' do
  begin
    At := Pos(';', Path);
    Entry := Copy(Path, 1, At - 1);
    Delete(Path, 1, At);
    if (Entry <> '') and not PathHas(Entry, Bin) then
    begin
      if Kept <> '' then
        Kept := Kept + ';';
      Kept := Kept + Entry;
    end;
  end;
  RegWriteExpandStringValue(HKCU, 'Environment', 'Path', Kept);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Root: String;
begin
  if CurStep = ssPostInstall then
  begin
    { versions\<v>\ holds the receipt; current-version is the pointer to it. Neither is a
      second opinion about which exe to run -- the exe stays flat at the install root. }
    ForceDirectories(ExpandConstant('{app}\versions\{#MyAppVersion}'));
    Root := ExpandConstant('{app}');
    StringChangeEx(Root, '\', '\\', True);
    WriteUtf8Atomically(ExpandConstant('{app}\versions\{#MyAppVersion}\install.json'),
      '{"app":"CaiXiHui","artifact":"desktop","channel":"stable","method":"direct",'
      + '"version":"{#MyAppVersion}","root":"' + Root + '"}');
    WriteAtomically(ExpandConstant('{app}\current-version'), '{#MyAppVersion}' + #10);
    AddBinToPath();
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    StopManagedApp();
    RemoveBinFromPath();
  end;
end;
