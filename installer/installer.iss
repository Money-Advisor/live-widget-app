; Inno Setup script for the Spark Flow desktop widget.
; Produces SparkFlowSetup.exe — a wizard installer that:
;   - shows a licence page ("I accept the agreement")
;   - offers a "Create a desktop icon" checkbox (checked by default)
;   - installs SparkFlow.exe to Program Files
;   - creates Start Menu + (optional) desktop shortcuts
;   - can launch the app on Finish
;
; Build:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\installer.iss
; (run from the repo root, AFTER `python build_all.py` has produced dist\SparkFlow.exe)

#define AppName "Spark Flow"
#define AppVersion "2.4.1"
#define AppPublisher "Spark Flow"
#define AppExe "SparkFlow.exe"

[Setup]
AppId={{8E2F1B40-7C2A-4E91-9D3A-NEXCALL00001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE.txt
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=Output
OutputBaseFilename=SparkFlowSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Per-user install (no admin prompt). Use "admin" + {autopf} only if you sign it.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
; "Create a desktop icon" — checked by default (no Unchecked flag).
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional shortcuts:"
; Auto-start on Windows sign-in — checked by default (recommended for agents).
Name: "startupicon"; Description: "Start Spark Flow automatically when I sign in to Windows (recommended)"; GroupDescription: "Startup:"

[Registry]
; Per-user auto-start on login (no admin). "--minimized" -> starts quietly in the
; system tray. Removed on uninstall. Only added if the Startup task is ticked.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "SparkFlow"; ValueData: """{app}\{#AppExe}"" --minimized"; Flags: uninsdeletevalue; Tasks: startupicon

[Files]
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
