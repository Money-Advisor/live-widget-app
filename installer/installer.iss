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
;
; 2.9.59 replaced the old screen with the one-panel one. Nothing about the
; install changed: the SAME AppId, folder, exe name and Run entry, so running
; this over any earlier Spark Flow - by hand, or silently by the auto-updater -
; upgrades it in place, keeps its tasks (auto-start, desktop icon) and leaves
; the settings (sign-in, devices, server addresses: HKCU\Software\Spark Flow)
; untouched. Keep it that way: a new AppId would install a SECOND widget.

#define AppName "Spark Flow"
#define AppVersion "2.9.64"
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

[InstallDelete]
; Start the runtime folder clean. Over an older build, files it had and this one
; does not would otherwise stay behind in _internal; [Files] then lays down this
; build's complete set. Nothing here may be in use: the widget has quit before an
; update runs, and PrepareToInstall ([Code]) waits until its processes are gone.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
; Folder (onedir) build: ship the exe AND its runtime next to it. A one-file
; build unpacked python312.dll into %TEMP% on every launch, which antivirus
; could break ("Failed to load Python DLL") leaving the agent with no widget.
Source: "..\dist\SparkFlow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
// 2.9.64 (Bilal, 30 Oct 2026): an auto-update runs this installer a few seconds
// after the widget quits. Since 2.9.59 the widget has a Qt WebEngine process
// beside it, and the widget or that process could still hold files in _internal
// when [InstallDelete] tried to replace them - the install failed silently, and
// widgets stayed on old versions. Every widget up to 2.9.63 runs this installer
// after a fixed ~3s, so the wait has to be HERE as well as in the widget's own
// update helper. Silent installs only (the auto-updater's): run by hand, Setup's
// own "close applications" page does what it always did.
const
  WaitForWidgetMs = 60000;

function GetLongPathName(ShortPath: String; LongPath: String; Size: Cardinal): Cardinal;
  external 'GetLongPathNameW@kernel32.dll stdcall';

// The folder as Windows names running programs: in full, never 8.3-short.
function FullPath(const Path: String): String;
var
  Buf: String;
  N: Cardinal;
begin
  Result := Path;
  SetLength(Buf, 1024);
  N := GetLongPathName(Path, Buf, 1024);
  if (N > 0) and (N < 1024) then
    Result := Copy(Buf, 1, N);
end;

// SparkFlow.exe and QtWebEngineProcess.exe processes started from Dir - this
// install's own; another folder's copy is not ours to wait for.
function WidgetProcessesIn(const Dir: String): Integer;
var
  Locator, Service, Procs, P: Variant;
  I: Integer;
  Path: String;
begin
  Result := 0;
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Service := Locator.ConnectServer('.', 'root\CIMV2');
    Procs := Service.ExecQuery('SELECT ExecutablePath FROM Win32_Process WHERE ' +
      'Name = ''SparkFlow.exe'' OR Name = ''QtWebEngineProcess.exe''');
    for I := 0 to Procs.Count - 1 do
    begin
      P := Procs.ItemIndex(I);
      if not VarIsNull(P.ExecutablePath) then
      begin
        // Started by an 8.3 path, a process is named by it: compare both in full.
        Path := FullPath(P.ExecutablePath);
        if CompareText(Copy(Path, 1, Length(Dir)), Dir) = 0 then
          Result := Result + 1;
      end;
    end;
  except
    Log('Could not list the running widget processes: ' + GetExceptionMessage);
    Result := 0;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Dir: String;
  Waited, Left: Integer;
begin
  Result := '';
  if not WizardSilent then
    Exit;
  Dir := AddBackslash(FullPath(ExpandConstant('{app}')));
  Waited := 0;
  Left := WidgetProcessesIn(Dir);
  while (Left > 0) and (Waited < WaitForWidgetMs) do
  begin
    Sleep(250);
    Waited := Waited + 250;
    Left := WidgetProcessesIn(Dir);
  end;
  if Waited = 0 then
    Log('No widget process running from ' + Dir)
  else if Left = 0 then
    Log(Format('Waited %d ms for the widget''s processes in %s to exit', [Waited, Dir]))
  else
    Log(Format('Waited %d ms; %d widget process(es) in %s still running - installing anyway', [Waited, Left, Dir]));
end;
