#define MyAppName "NeumoFlow"
#ifndef MyAppVersion
#define MyAppVersion "1.0.2"
#endif
#define MyAppPublisher "NeumoFlow"
#define MyAppExeName "NeumoFlow.exe"

[Setup]
AppId={{A23C4D66-70B7-43D5-A445-5B8BD7A4B6B4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
UninstallDisplayIcon={app}\{#MyAppExeName}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UsePreviousAppDir=yes
UsePreviousGroup=no
DisableProgramGroupPage=yes
OutputDir=..\dist-installer
OutputBaseFilename=NeumoFlowSetup-{#MyAppVersion}
MinVersion=10.0.17763
PrivilegesRequired=admin
DisableDirPage=yes
DisableReadyPage=yes
Compression=lzma
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\app\data\brand\neumoflow.ico
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "..\dist\NeumoFlow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "usb-windows.html"; DestDir: "{app}"; Flags: ignoreversion
Source: "windows-usb\package\*"; DestDir: "{app}\usb-setup\package"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "setup-usb-windows.ps1"; DestDir: "{app}\usb-setup"; Flags: ignoreversion
Source: "windows-usb\README.md"; DestDir: "{app}\usb-setup"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"

[InstallDelete]
; Only clean up our old program/shortcuts when the previous AppId is installed.
; Never remove the user data directory or use recursive deletion here.
Type: files; Name: "{app}\Espirometro.exe"; Check: IsLegacyUpgrade
Type: files; Name: "{autodesktop}\Espirometro.lnk"; Check: IsLegacyUpgrade
Type: files; Name: "{commonprograms}\Espirometro\Espirometro.lnk"; Check: IsLegacyUpgrade

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[Messages]
WelcomeLabel2=Este asistente instalará el programa y preparará la conexión con el espirómetro. No necesita configurar controladores por separado.%n%nPuede conectar el espirómetro ahora o al terminar la instalación.
FinishedLabel=La instalación terminó. Conecte el espirómetro y abra el acceso directo NeumoFlow del escritorio. Realice la calibración antes del primer estudio.

[Code]
var
  DriverRestartRequired: Boolean;
  LegacyUpgrade: Boolean;

function InitializeSetup(): Boolean;
var
  PreviousName: String;
begin
  LegacyUpgrade := False;
  if RegQueryStringValue(HKLM64,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{A23C4D66-70B7-43D5-A445-5B8BD7A4B6B4}_is1',
    'DisplayName', PreviousName) then
    LegacyUpgrade := Pos('Espirometro', PreviousName) = 1;
  Result := True;
end;

function IsLegacyUpgrade(): Boolean;
begin
  Result := LegacyUpgrade;
end;

function NeedRestart(): Boolean;
begin
  Result := DriverRestartRequired;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Parameters: String;
begin
  if CurStep = ssPostInstall then
  begin
    WizardForm.StatusLabel.Caption := 'Preparando la conexión con el espirómetro...';
    { Fixed package + pinned public certificate. PnPUtil checks signed catalog. }
    Parameters := '-NoProfile -ExecutionPolicy Bypass -File "' +
      ExpandConstant('{app}\usb-setup\setup-usb-windows.ps1') + '" -Package "' +
      ExpandConstant('{app}\usb-setup\package') + '"';
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Parameters,
      ExpandConstant('{app}\usb-setup'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      RaiseException('No se pudo preparar la conexión. Reinicie Windows y vuelva a ejecutar el instalador.');
    Log(Format('CPFS/D USB setup returned %d', [ResultCode]));
    if ResultCode = 3010 then
      DriverRestartRequired := True
    else if ResultCode <> 0 then
      RaiseException('No se pudo completar la conexión con el espirómetro. Conecte el equipo y vuelva a ejecutar este instalador. El detalle quedó en C:\ProgramData\Espirometro\USB\setup-usb.log.');
  end;
end;
