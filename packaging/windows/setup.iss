[Setup]
AppName=Epic Report Generator
AppVersion=@@VERSION@@
AppPublisher=Epic Report Generator
DefaultDirName={autopf}\Epic Report Generator
DefaultGroupName=Epic Report Generator
OutputDir=Output
OutputBaseFilename=epic-report-generator-setup
SetupIconFile=..\..\src\epic_report_generator\resources\logo.ico
UninstallDisplayIcon={app}\epic-report-generator.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "..\..\epic-report-generator.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\src\epic_report_generator\resources\logo.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Epic Report Generator"; Filename: "{app}\epic-report-generator.exe"; IconFilename: "{app}\logo.ico"
Name: "{commondesktop}\Epic Report Generator"; Filename: "{app}\epic-report-generator.exe"; IconFilename: "{app}\logo.ico"

[Run]
Filename: "{app}\epic-report-generator.exe"; Description: "Launch Epic Report Generator"; Flags: nowait postinstall skipifsilent
