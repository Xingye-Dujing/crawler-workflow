; Inno Setup 6/7 script for the portable CaiXiHui onedir build (compiled with ISCC.exe; the UTF-8
; BOM at the head of this file is what lets it carry Chinese — Inno reads a BOM-less .iss as ANSI).
;
; Build the folder first:
;   powershell -ExecutionPolicy Bypass -File desktop\build_windows.ps1
; Then compile this file with ISCC.exe (the build script does it with -Installer).
;
; User data is NOT installed here and NOT deleted on uninstall: the app stores it in
; %APPDATA%\CaiXiHui (runs, datasets, cookies, exports, logs), which survives upgrades.

#define MyAppName "采析绘"
#define MyAppVersion "1.0.0"
#define MyAppExeName "CaiXiHui.exe"

[Setup]
AppId={{8E1C6A2D-5E46-4C71-9A0B-6D0F7A2E9C11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=采析绘
VersionInfoVersion=1.0.0.0
VersionInfoProductName={#MyAppName}
VersionInfoDescription=采析绘 工作流采集与分析
DefaultDirName={localappdata}\Programs\CaiXiHui
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
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

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: checkedonce

[Files]
Source: "..\dist\CaiXiHui\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

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
; Deliberately empty: %APPDATA%\CaiXiHui is the user's data, not ours to delete.
