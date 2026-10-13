; Inno Setup script for the codeviz Windows installer. Built in CI after PyInstaller:
;   iscc /DAppVersion=0.2.0 packaging\windows.iss   ->  dist\codeviz-setup.exe
; Installs per user (no admin prompt) into %LOCALAPPDATA%\Programs\codeviz.

#ifndef AppVersion
  #define AppVersion "0.2.0"
#endif

[Setup]
AppId={{6E3B1F0A-7C2D-4B8E-9A51-3F2C8D9E4B17}
AppName=codeviz
AppVersion={#AppVersion}
AppPublisher=codeviz
DefaultDirName={autopf}\codeviz
DefaultGroupName=codeviz
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=codeviz-setup
SetupIconFile=..\build\icon.ico
UninstallDisplayIcon={app}\codeviz.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\codeviz\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\codeviz"; Filename: "{app}\codeviz.exe"
Name: "{autodesktop}\codeviz"; Filename: "{app}\codeviz.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\codeviz.exe"; Description: "{cm:LaunchProgram,codeviz}"; Flags: nowait postinstall skipifsilent
