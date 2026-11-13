#define MyAppName "Espirometro"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Espirometro"
#define MyAppExeName "Espirometro.exe"

[Setup]
AppId={{A23C4D66-70B7-43D5-A445-5B8BD7A4B6B4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist-installer
OutputBaseFilename=EspirometroSetup-{#MyAppVersion}
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
Source: "..\dist\Espirometro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "usb-windows.html"; DestDir: "{app}"; Flags: ignoreversion
Source: "windows-usb\package\*"; DestDir: "{app}\usb-setup\package"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "setup-usb-windows.ps1"; DestDir: "{app}\usb-setup"; Flags: ignoreversion
Source: "windows-usb\README.md"; DestDir: "{app}\usb-setup"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[Messages]
WelcomeLabel2=Este asistente instalará el programa y preparará la conexión con el espirómetro. No necesita configurar controladores por separado.%n%nPuede conectar el espirómetro ahora o al terminar la instalación.
FinishedLabel=La instalación terminó. Conecte el espirómetro y abra el acceso directo Espirometro del escritorio. Realice la calibración antes del primer estudio.

[Code]
var
  DriverRestartRequired: Boolean;

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
