; Mirabel Voice installer.
;
; Build it with:
;   iscc /DAppVersion=0.1.0 packaging\installer.iss
;
; It installs for the person who runs it, in their own folder, so it
; never asks for an administrator password. That matters: most people
; here cannot approve one.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "Mirabel Voice"
#define AppExe "MirabelVoice.exe"
#define ConsoleExe "MirabelVoiceConsole.exe"
#define Publisher "Mirabel Technologies"

[Setup]
AppId={{5061E346-3CCC-4243-B516-EA7285763AFA}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#Publisher}
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\Mirabel Voice
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
; "lowest" keeps the whole install inside the user's own profile.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=MirabelVoiceSetup-{#AppVersion}
SetupIconFile=MirabelVoice.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startup"; Description: "Start Mirabel Voice when I sign in"; GroupDescription: "Options:"
Name: "desktopicon"; Description: "Put a shortcut on my Desktop"; GroupDescription: "Options:"

[Files]
Source: "..\dist\MirabelVoice\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start Mirabel Voice now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Stop the running copy, or its files cannot be deleted.
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#AppExe}"; Flags: runhidden; RunOnceId: "StopApp"

[Code]
var
  KeyPage: TInputQueryWizardPage;

{ A blank line inside a message box.

  Never start a source line with #13#10. The Inno preprocessor reads any
  line whose first character is a hash as one of its own directives, and
  the compile fails with "Unknown preprocessor directive". This function
  keeps the hash away from the start of a line. }
function Gap(): String;
begin
  Result := #13#10 + #13#10;
end;

function KeysTarget(): String;
begin
  Result := ExpandConstant('{userappdata}\MirabelVoice\keys.json');
end;

{ Return a keys file that somebody prepared, or an empty string.
  The order matches ADMIN.md: beside the installer first, then the
  path in MIRABEL_VOICE_KEYS. }
function PreparedKeys(): String;
var
  Candidate: String;
begin
  Result := '';
  Candidate := ExpandConstant('{src}\keys.json');
  if FileExists(Candidate) then
  begin
    Result := Candidate;
    Exit;
  end;
  Candidate := GetEnv('MIRABEL_VOICE_KEYS');
  if (Candidate <> '') and FileExists(Candidate) then
    Result := Candidate;
end;

function NeedsKeys(): Boolean;
begin
  Result := (not FileExists(KeysTarget())) and (PreparedKeys() = '');
end;

procedure InitializeWizard();
begin
  KeyPage := CreateInputQueryPage(wpSelectTasks,
    'Your keys',
    'Mirabel Voice needs two keys to work.',
    'Ask Tommy for them, then paste one into each box. They are stored on this computer only.');
  KeyPage.Add('OpenAI key:', False);
  KeyPage.Add('Anthropic key:', False);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = KeyPage.ID) and (not NeedsKeys());
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = KeyPage.ID then
  begin
    if (Trim(KeyPage.Values[0]) = '') or (Trim(KeyPage.Values[1]) = '') then
    begin
      MsgBox('Both keys are needed. Ask Tommy for them, then run this again.',
        mbError, MB_OK);
      Result := False;
    end;
  end;
end;

{ Stop a running copy, so its files can be replaced. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#AppExe}', '',
    SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(600);
end;

procedure StoreKeys();
var
  Folder, Prepared, Json: String;
begin
  Folder := ExpandConstant('{userappdata}\MirabelVoice');
  ForceDirectories(Folder);

  if FileExists(KeysTarget()) then
    Exit;

  Prepared := PreparedKeys();
  if Prepared <> '' then
  begin
    FileCopy(Prepared, KeysTarget(), False);
    Exit;
  end;

  { Braces here are part of the JSON text, not an Inno constant. }
  Json := '{' + #13#10 +
          '  "openai_api_key": "' + Trim(KeyPage.Values[0]) + '",' + #13#10 +
          '  "anthropic_api_key": "' + Trim(KeyPage.Values[1]) + '"' + #13#10 +
          '}' + #13#10;
  SaveStringToUTF8File(KeysTarget(), Json, False);
end;

{ Ask the app whether the keys are accepted by both providers. A wrong
  key must be caught now, not during somebody's first dictation. }
procedure CheckKeys();
var
  ResultCode: Integer;
begin
  if not Exec(ExpandConstant('{app}\{#ConsoleExe}'), '--check-keys', '',
    SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Exit;
  if ResultCode <> 0 then
    MsgBox('One of the keys was not accepted.' + Gap() +
      'Mirabel Voice is installed, but dictation will not work until the ' +
      'keys are right. Delete this file and run the installer again:' +
      Gap() + KeysTarget(), mbError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    StoreKeys();
    CheckKeys();
  end;
end;
