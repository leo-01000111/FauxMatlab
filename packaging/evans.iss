; Inno Setup script: the Windows installer.
;
; It packages the PyInstaller one-folder build, so build that first:
;
;   pyinstaller --clean --noconfirm packaging/evans.spec
;   iscc packaging\evans.iss
;
; which writes dist\Evans-Setup-<version>.exe. Inno Setup 6.3 or newer.
;
; Per user, no admin rights: it installs into %LOCALAPPDATA%\Programs\Evans
; and writes only to the current user's registry. A student on a locked-down
; university machine can install it, and nothing asks for elevation.

; The version comes from the package, the one place it is written down, so
; the installer cannot drift from what `evans --version` prints. Read at
; compile time: the first line of src\evans\__init__.py that starts with
; `__version__`, and whatever sits between its quotes.
#define VersionFile AddBackslash(SourcePath) + "..\src\evans\__init__.py"
#define AppVersion ""
#define FileHandle
#define FileLine
#define Quoted

#sub ReadVersionLine
  #expr FileLine = FileRead(FileHandle)
  #if Pos("__version__", FileLine) == 1
    #expr Quoted = Copy(FileLine, Pos('"', FileLine) + 1)
    #expr AppVersion = Copy(Quoted, 1, Pos('"', Quoted) - 1)
  #endif
#endsub

#expr FileHandle = FileOpen(VersionFile)
#if !FileHandle
  #error Cannot open the version file
#endif
#for {0; !FileEof(FileHandle) && AppVersion == ""; 0} ReadVersionLine
#expr FileClose(FileHandle)
#if AppVersion == ""
  #error No __version__ line in src\evans\__init__.py
#endif

; The taskbar identity src\evans\app.py claims at start-up. The shortcuts
; carry the same one, so a pinned shortcut and the running window are one
; taskbar button rather than two.
#define AppUserModelID "LeonGorecki.Evans"
#define ProgId "Evans.Model"

[Setup]
; Never change this: it is how a newer installer recognises an older install
; and upgrades it in place instead of installing a second copy beside it.
AppId={{1AEA92A7-EBDD-44A5-8F6E-06CA605C78F8}
AppName=Evans
AppVersion={#AppVersion}
AppVerName=Evans {#AppVersion}
AppPublisher=Leon Gorecki
AppPublisherURL=https://github.com/leo-01000111/evans
AppSupportURL=https://github.com/leo-01000111/evans/issues
AppUpdatesURL=https://github.com/leo-01000111/evans/releases
AppCopyright=Copyright (c) Leon Gorecki. MIT licence.
VersionInfoVersion={#AppVersion}
VersionInfoProductName=Evans

PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\Evans
DefaultGroupName=Evans
DisableProgramGroupPage=yes
; An upgrade goes where the first install went, without asking again.
DisableDirPage=auto
UsePreviousAppDir=yes

; The PyInstaller build is 64-bit.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

SourceDir=..
OutputDir=dist
OutputBaseFilename=Evans-Setup-{#AppVersion}
SetupIconFile=src\evans\ui\icons\app.ico
UninstallDisplayIcon={app}\Evans.exe
UninstallDisplayName=Evans
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes

; Close a running Evans before replacing its files, and the shell is told
; about the .fmdl association so Explorer picks up the icon straight away.
CloseApplications=yes
RestartApplications=no
ChangesAssociations=yes

[Tasks]
Name: desktopicon; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: fmdlassoc; Description: "Open Evans models (.fmdl) with Evans"; \
    GroupDescription: "File associations:"

[InstallDelete]
; PyInstaller's bundle changes shape between versions: a DLL one release
; needed is gone in the next. Clear the old bundle on upgrade so stale files
; cannot be loaded beside the new ones. Program files only — the user's
; settings live in the registry under Software\Evans and are never touched.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\Evans\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Evans"; Filename: "{app}\Evans.exe"; \
    AppUserModelID: "{#AppUserModelID}"; Comment: "Classical and modern control workbench"
Name: "{autodesktop}\Evans"; Filename: "{app}\Evans.exe"; \
    AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon

[Registry]
; .fmdl is Evans' own format, so Evans may be its default program. Not .m or
; .mlx: those belong to MATLAB, and an installer that took them over would
; be rude to anybody who has both.
;
; HKA is HKCU in a per-user install. Uninstall removes exactly these keys
; and values; the settings under Software\Evans stay where they are.
Root: HKA; Subkey: "Software\Classes\.fmdl"; ValueType: string; ValueName: ""; \
    ValueData: "{#ProgId}"; Flags: uninsdeletevalue uninsdeletekeyifempty; Tasks: fmdlassoc
Root: HKA; Subkey: "Software\Classes\.fmdl\OpenWithProgids"; ValueType: string; \
    ValueName: "{#ProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty; Tasks: fmdlassoc
Root: HKA; Subkey: "Software\Classes\{#ProgId}"; ValueType: string; ValueName: ""; \
    ValueData: "Evans model"; Flags: uninsdeletekey; Tasks: fmdlassoc
Root: HKA; Subkey: "Software\Classes\{#ProgId}"; ValueType: string; \
    ValueName: "AppUserModelID"; ValueData: "{#AppUserModelID}"; Tasks: fmdlassoc
Root: HKA; Subkey: "Software\Classes\{#ProgId}\DefaultIcon"; ValueType: string; \
    ValueName: ""; ValueData: "{app}\Evans.exe,0"; Tasks: fmdlassoc
Root: HKA; Subkey: "Software\Classes\{#ProgId}\shell\open\command"; ValueType: string; \
    ValueName: ""; ValueData: """{app}\Evans.exe"" ""%1"""; Tasks: fmdlassoc
; Lists Evans under "Open with" for .fmdl, with its proper name.
Root: HKA; Subkey: "Software\Classes\Applications\Evans.exe"; ValueType: string; \
    ValueName: "FriendlyAppName"; ValueData: "Evans"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\Evans.exe\SupportedTypes"; \
    ValueType: string; ValueName: ".fmdl"; ValueData: ""

[Run]
Filename: "{app}\Evans.exe"; Description: "{cm:LaunchProgram,Evans}"; \
    Flags: nowait postinstall skipifsilent
