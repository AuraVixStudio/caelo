; Inno Setup script — instalator "AI Studio Pro"
; 1) Zbuduj aplikację:  powershell -ExecutionPolicy Bypass -File build.ps1
; 2) Zainstaluj Inno Setup:  https://jrsoftware.org/isdl.php
; 3) Otwórz ten plik w Inno Setup i kliknij Compile (lub: iscc installer.iss)
; Wynik: Output\AI-Studio-Pro-Setup.exe

#define AppName "AI Studio Pro"
#define AppVersion "2.2.0"
#define AppExe "AI Studio Pro.exe"

[Setup]
AppId={{B7E1B2A0-7C3A-4E1F-9C2D-AISTUDIOPRO01}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=AI Studio Pro
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=Output
OutputBaseFilename=AI-Studio-Pro-Setup
SetupIconFile=appicon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; Portable, jednoplikowy exe z PyInstaller (onefile)
Source: "dist\AI Studio Pro.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
