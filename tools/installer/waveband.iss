; Waveband's installer, for Inno Setup 6.7 or newer. Built by tools\build_release.py, which passes:
;   /DAppVersion=0.2.0  /DSourceDir=<the release folder>  /DOutDir=<where the setup goes>
;   /DRepoUrl=https://github.com/<owner>/<name>   (optional)
;
; It installs for the current user only (no administrator prompt), in
; %LOCALAPPDATA%\Programs\Waveband, so the settings, fights and boss HP tables Waveband writes
; beside itself stay writable. An update is the next version's setup run over the old one:
; Waveband's own updater runs it with /VERYSILENT /CLOSEAPPLICATIONS /UPDATE, and it starts
; Waveband again when done. What the user made (config.json, sessions\, learned_parts.json,
; waveband.log) is never part of the install, so an update or an uninstall leaves it alone.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #error Pass /DSourceDir=<the release folder built by tools\build_release.py>
#endif
#ifndef OutDir
  #define OutDir "."
#endif
#ifndef RepoUrl
  #define RepoUrl ""
#endif
#define Assets AddBackslash(SourcePath) + "..\..\assets"

[Setup]
; Never change the AppId: it is how a newer setup finds the copy to update.
AppId={{C9470428-A301-45A7-B87C-CD53899B453A}
AppName=Waveband
AppVersion={#AppVersion}
AppVerName=Waveband {#AppVersion}
AppPublisher=Waveband
#if RepoUrl != ""
AppPublisherURL={#RepoUrl}
AppSupportURL={#RepoUrl}/issues
AppUpdatesURL={#RepoUrl}/releases
#endif
AppComments=A passive damage meter for Wuthering Waves. Unofficial; not made or endorsed by Kuro Games.
DefaultDirName={localappdata}\Programs\Waveband
DefaultGroupName=Waveband
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutDir}
OutputBaseFilename=Waveband-{#AppVersion}-setup
SetupIconFile={#Assets}\waveband.ico
UninstallDisplayIcon={app}\Waveband.exe
UninstallDisplayName=Waveband
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern dark
WizardImageFile={#Assets}\installer\wizard-100.bmp,{#Assets}\installer\wizard-125.bmp,{#Assets}\installer\wizard-150.bmp,{#Assets}\installer\wizard-175.bmp,{#Assets}\installer\wizard-200.bmp,{#Assets}\installer\wizard-250.bmp
WizardSmallImageFile={#Assets}\installer\wizard-small-100.bmp,{#Assets}\installer\wizard-small-125.bmp,{#Assets}\installer\wizard-small-150.bmp,{#Assets}\installer\wizard-small-175.bmp,{#Assets}\installer\wizard-small-200.bmp,{#Assets}\installer\wizard-small-250.bmp
InfoBeforeFile=before.txt
; a running Waveband is closed for the update; it is started again by [Run]
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Put Waveband on the desktop"; Flags: unchecked
Name: "startup"; Description: "Start Waveband when Windows starts"; Flags: unchecked

[InstallDelete]
; The program's own folders are replaced whole, so files an older version had and this one
; does not (0.3.1's Qt, gone since 0.3.2) are not left behind.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\ui"
Type: filesandordirs; Name: "{app}\source"
Type: filesandordirs; Name: "{app}\lib"

[UninstallDelete]
; the cache of the web view that draws the overlay (made by wwmeter\overlay_webview2.py)
Type: filesandordirs; Name: "{localappdata}\Waveband\WebView2"
Type: dirifempty; Name: "{localappdata}\Waveband"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Waveband"; Filename: "{app}\Waveband.exe"
Name: "{autoprograms}\Waveband self-test"; Filename: "{app}\selftest.bat"; IconFilename: "{app}\Waveband.exe"
Name: "{autodesktop}\Waveband"; Filename: "{app}\Waveband.exe"; Tasks: desktopicon
Name: "{userstartup}\Waveband"; Filename: "{app}\Waveband.exe"; Tasks: startup

[Run]
; also after a silent update, which is how Waveband comes back after updating itself
Filename: "{app}\Waveband.exe"; Description: "Start Waveband"; Flags: nowait postinstall

[Code]
var
  ChoicePage: TInputOptionWizardPage;
  ImportPage: TInputDirWizardPage;
  WasInstalled: Boolean;  // decided before any file is copied: after, the program is always there

function IsUpdate(): Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\Waveband.exe'));
end;

function Importing(): Boolean;
begin
  Result := ChoicePage.SelectedValueIndex = 1;
end;

procedure InitializeWizard();
begin
  // A folder page takes no empty answer, even in a silent install, so the choice comes first and
  // the folder is asked for only when there is one to bring.
  ChoicePage := CreateInputOptionPage(wpSelectDir,
    'Bring your settings and fights along?',
    'From a copy you unzipped before (version 0.1 was called wwmeter).',
    'Waveband can copy the settings (config.json), the earlier fights (the sessions folder) and the ' +
    'boss part shares an older copy learned. The old folder is not changed.',
    True, False);
  ChoicePage.Add('Start fresh');
  ChoicePage.Add('Bring them from an older copy');
  ChoicePage.SelectedValueIndex := 0;
  ImportPage := CreateInputDirPage(ChoicePage.ID,
    'Bring your settings and fights along',
    'Where the older copy is.',
    'Pick the folder that holds the old wwmeter.exe or Waveband.exe.',
    False, '');
  ImportPage.Add('');
  ImportPage.Values[0] := ExpandConstant('{userdesktop}');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  // an update keeps what is already beside the program; there is nothing to bring
  Result := ((PageID = ChoicePage.ID) and IsUpdate()) or
            ((PageID = ImportPage.ID) and (IsUpdate() or not Importing()));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Folder: String;
begin
  Result := True;
  if CurPageID = ImportPage.ID then
  begin
    Folder := Trim(ImportPage.Values[0]);
    if not FileExists(AddBackslash(Folder) + 'config.json') and
       not DirExists(AddBackslash(Folder) + 'sessions') then
    begin
      MsgBox('That folder has no config.json and no sessions folder. Pick the folder that holds the ' +
             'old wwmeter.exe or Waveband.exe, or go back and choose to start fresh.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure CopyIfMissing(const Source, Target: String);
begin
  if FileExists(Source) and not FileExists(Target) then
    FileCopy(Source, Target, True);
end;

procedure ImportFrom(const Folder: String);
var
  Found: TFindRec;
  Sessions: String;
begin
  CopyIfMissing(Folder + 'config.json', ExpandConstant('{app}\config.json'));
  CopyIfMissing(Folder + 'learned_parts.json', ExpandConstant('{app}\learned_parts.json'));
  Sessions := ExpandConstant('{app}\sessions');
  if FindFirst(Folder + 'sessions\*.json', Found) then
  begin
    ForceDirectories(Sessions);
    try
      repeat
        CopyIfMissing(Folder + 'sessions\' + Found.Name, Sessions + '\' + Found.Name);
      until not FindNext(Found);
    finally
      FindClose(Found);
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Folder: String;
begin
  if CurStep = ssInstall then
    WasInstalled := IsUpdate();
  if (CurStep = ssPostInstall) and not WasInstalled and Importing() then
  begin
    Folder := Trim(ImportPage.Values[0]);
    if Folder <> '' then
      ImportFrom(AddBackslash(Folder));
  end;
end;
