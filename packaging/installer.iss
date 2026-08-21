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

; The relay's address, baked in so that nobody has to type it. It is not a
; secret; the per-person token is. build.ps1 passes this.
#ifndef RelayUrl
  #error RelayUrl is not set. Build with packaging/build.ps1, or pass /DRelayUrl=https://...
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
  TokenPage: TInputQueryWizardPage;

{ A blank line inside a message box.

  Never start a source line with #13#10. The Inno preprocessor reads any
  line whose first character is a hash as one of its own directives, and
  the compile fails with "Unknown preprocessor directive". This function
  keeps the hash away from the start of a line. }
function Gap(): String;
begin
  Result := #13#10 + #13#10;
end;

function ConfigTarget(): String;
begin
  Result := ExpandConstant('{userappdata}\MirabelVoice\config.json');
end;

{ True when this computer already holds a token, which is what an update
  install looks like. The token lives in the app's own settings file, so
  that is where this looks; an empty or null value is not a token. }
function HasToken(): Boolean;
var
  Lines: TArrayOfString;
  Value: String;
  I, At: Integer;
begin
  Result := False;
  if not FileExists(ConfigTarget()) then
    Exit;
  if not LoadStringsFromFile(ConfigTarget(), Lines) then
    Exit;
  for I := 0 to GetArrayLength(Lines) - 1 do
  begin
    At := Pos('"relay_token"', Lines[I]);
    if At > 0 then
    begin
      Value := Trim(Copy(Lines[I], At + Length('"relay_token":') + 1, 200));
      if (Value <> 'null') and (Value <> 'null,') and (Value <> '""') and (Value <> '"",') then
        Result := True;
    end;
  end;
end;

procedure InitializeWizard();
begin
  TokenPage := CreateInputQueryPage(wpSelectTasks,
    'Your token',
    'Mirabel Voice needs one token to work.',
    'Ask Tommy for yours and paste it in. It is yours alone. There are no API keys to enter: the keys stay on our server, and this computer never holds one.');
  TokenPage.Add('Token:', False);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = TokenPage.ID) and HasToken();
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = TokenPage.ID then
  begin
    if Trim(TokenPage.Values[0]) = '' then
    begin
      MsgBox('A token is needed. Ask Tommy for yours, then run this again.',
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

{ Store the address and the token by asking the app to store them.

  Writing config.json from here would overwrite the dictation key, the
  custom words, and every other setting, which an update install has to
  keep. The app writes only these two fields and leaves the rest alone. }
procedure StoreRelay(Arguments: String);
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{app}\{#ConsoleExe}'), Arguments, '',
    SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

{ Store the address and a token. }
procedure StoreToken(Token: String);
begin
  if Token = '' then
    StoreRelay('--forget-relay-token')
  else
    StoreRelay('--set-relay "{#RelayUrl}" "' + Token + '"');
end;

{ Store the address alone, keeping whatever token is already here. An
  update install runs this, so a relay that moved is followed. }
procedure RefreshAddress();
begin
  StoreRelay('--set-relay "{#RelayUrl}"');
end;

{ Ask the app whether the relay accepts this token. A wrong token must be
  caught now, not during somebody's first dictation.

  A token the relay refuses is cleared again, so that running the
  installer a second time asks for it instead of skipping the page. }
procedure CheckToken();
var
  ResultCode: Integer;
begin
  if not Exec(ExpandConstant('{app}\{#ConsoleExe}'), '--check-keys', '',
    SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Exit;
  if ResultCode <> 0 then
  begin
    StoreToken('');
    MsgBox('That token was not accepted.' + Gap() +
      'Mirabel Voice is installed, but dictation will not work until the ' +
      'token is right. Check it with Tommy, then run this installer again ' +
      'and paste it in.', mbError, MB_OK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if HasToken() then
      RefreshAddress()
    else
      StoreToken(Trim(TokenPage.Values[0]));
    CheckToken();
  end;
end;
