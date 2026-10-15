; Inno Setup script for Spark Flow FOCUS - the new one-panel layout, for testing.
; Produces SparkFlowFocusSetup.exe, which installs BESIDE the normal widget:
;   - its own AppId, folder, Start Menu entry and desktop icon ("Spark Flow Focus")
;   - NO auto-start at Windows sign-in: the normal widget keeps that, and two copies
;     racing for the one-copy lock every morning would be a coin toss
;   - uninstalling it removes only its own files; the normal widget and the
;     signed-in session are never touched
;
; installer.iss (the normal widget) is not changed by this file.
;
; Build:  python build_focus.py --installer
; (or ISCC.exe installer\installer_focus.iss after build_focus.py has made build\focus-dist\SparkFlowFocus)

#define AppName "Spark Flow Focus"
#define AppVersion "2.9.57-focus"
#define AppPublisher "Spark Flow"
#define AppExe "SparkFlowFocus.exe"

[Setup]
AppId={{8E2F1B40-7C2A-4E91-9D3A-FOCUSPREVIEW1}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE.txt
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} (test build)
OutputDir=Output
OutputBaseFilename=SparkFlowFocusSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional shortcuts:"

[Files]
; Folder (onedir) build, as the normal widget - see installer.iss.
Source: "..\build\focus-dist\SparkFlowFocus\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Messages]
FinishedLabel=Spark Flow Focus is installed.%n%nOnly one Spark Flow can run at a time: before opening Spark Flow Focus, right-click the Spark Flow icon near the clock and choose Quit.

[Run]
; Not ticked by default: the normal widget is usually still running.
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName} now"; Flags: nowait postinstall skipifsilent unchecked
