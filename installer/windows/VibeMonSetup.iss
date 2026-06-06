; VibeMonSetup.exe — Windows GUI installer (Phase 2).
;
; Thin shell over the same runtime the script install deploys: it places
; the embedded CPython + the hook modules into %USERPROFILE%\.vibemon and
; runs install.py with the key from the wizard page. No install logic of
; its own — merges, privacy guarantees, idempotency and the daily
; auto-update all belong to the runtime (see INSTALLER_PLAN.md).
;
; Built by installer/windows/build.ps1 (stages the hash-pinned embeddable
; Python + modules, then compiles this with ISCC). Per-user, no UAC, no
; uninstaller in v1 (removal is documented in PRIVACY.md).
;
; Silent / scripted installs:  VibeMonSetup.exe /VERYSILENT /APIKEY=vbm_...

#ifndef AppVersion
  #define AppVersion "0"
#endif
#ifndef StageDir
  #define StageDir "stage"
#endif
#ifndef OutDir
  #define OutDir "."
#endif

[Setup]
AppId={{7E1B3A52-9C4D-4D2B-9A1E-3C6F2A81D4B7}
AppName=VibeMon
AppVersion={#AppVersion}
AppPublisher=Streamize LLC
AppPublisherURL=https://vibemon.dev
AppSupportURL=https://github.com/Streamize-llc/vibemon-hooks
DefaultDirName={%USERPROFILE}\.vibemon
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
Uninstallable=no
OutputDir={#OutDir}
OutputBaseFilename=VibeMonSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "{#StageDir}\*.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\python\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs

[Messages]
FinishedLabelNoIcons=VibeMon is connected!%nRestart your Claude Code / Cursor session to start growing your slime.%nYou can delete this installer.

[Code]
var
  KeyPage: TInputQueryWizardPage;

function GetApiKey(): String;
begin
  { Silent / scripted installs pass /APIKEY=vbm_... on the command line. }
  Result := ExpandConstant('{param:APIKEY|}');
  if (Result = '') and (KeyPage <> nil) then
    Result := Trim(KeyPage.Values[0]);
end;

procedure InitializeWizard;
begin
  KeyPage := CreateInputQueryPage(wpWelcome,
    'API Key', 'Connect your VibeMon slime',
    'Paste the API key from the VibeMon app (Settings ' + #8594 + ' API Key). It starts with vbm_.');
  KeyPage.Add('API key:', False);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (KeyPage <> nil) and (PageID = KeyPage.ID)
            and (ExpandConstant('{param:APIKEY|}') <> '');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  k: String;
begin
  Result := True;
  if (KeyPage <> nil) and (CurPageID = KeyPage.ID) then
  begin
    k := Trim(KeyPage.Values[0]);
    if (Pos('vbm_', k) <> 1) or (Length(k) < 12) then
    begin
      MsgBox('That doesn''t look like a VibeMon API key' + #8212 +
             ' it should start with vbm_. Copy it from the VibeMon app (Settings ' + #8594 + ' API Key).',
             mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Py, InstallPy, Key, Params: String;
begin
  if CurStep = ssPostInstall then
  begin
    Key := GetApiKey();
    Py := ExpandConstant('{app}\python\python.exe');
    InstallPy := ExpandConstant('{app}\install.py');
    { install.py saves the key, writes config, merges agent hooks with the
      bundled interpreter baked into the hook commands (--launcher), and
      fires the connection test probe. }
    Params := '"' + InstallPy + '" "' + Key + '" "{#AppVersion}" --launcher "' + Py + '"';
    if not Exec(Py, Params, ExpandConstant('{app}'), SW_HIDE,
                ewWaitUntilTerminated, ResultCode) then
    begin
      if not WizardSilent() then
        MsgBox('Could not run the bundled Python ' + #8212 + ' installation incomplete. ' +
               'Please report this at github.com/Streamize-llc/vibemon-hooks.',
               mbError, MB_OK);
    end
    else if ResultCode <> 0 then
    begin
      { Files are deployed and hooks merged; a non-zero exit is almost
        always the connection test rejecting the key. Don't fail the whole
        setup — tell the user what to check. }
      if not WizardSilent() then
        MsgBox('VibeMon was installed, but the connection test failed (exit ' +
               IntToStr(ResultCode) + '). Double-check your API key in the VibeMon app ' +
               '(Settings ' + #8594 + ' API Key) and run this installer again.',
               mbInformation, MB_OK);
    end;
  end;
end;
