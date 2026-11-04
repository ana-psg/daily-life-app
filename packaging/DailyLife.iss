; Instalador do Daily Life (Inno Setup 6). Gerar com build.ps1, que cria antes a pasta dist\DailyLife.
#define AppVersion "2.0.0"

[Setup]
AppId={{B8C1E6A2-4F3D-4E57-9A21-7D6F0C3E1A10}
AppName=Daily Life
AppVersion={#AppVersion}
AppVerName=Daily Life {#AppVersion}
AppPublisher=Daily Life
VersionInfoVersion={#AppVersion}
VersionInfoCompany=Daily Life
VersionInfoDescription=Instalador do Daily Life
VersionInfoProductName=Daily Life
; Instala só para o usuário atual: não pede administrador
PrivilegesRequired=lowest
DefaultDirName={autopf}\Daily Life
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=DailyLife-Setup-{#AppVersion}
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\DailyLife.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; Flags: unchecked
Name: "startup"; Description: "Abrir ao iniciar o Windows"; Flags: unchecked

[InstallDelete]
; Atualização: tira os arquivos da versão antiga do programa. Os dados ficam em %APPDATA% e não são tocados.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\DailyLife\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; DestName: "Manual.md"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Daily Life"; Filename: "{app}\DailyLife.exe"
Name: "{autoprograms}\Manual do Daily Life"; Filename: "{app}\Manual.md"
Name: "{autodesktop}\Daily Life"; Filename: "{app}\DailyLife.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "DailyLife"; ValueData: """{app}\DailyLife.exe"" --inicializacao"; Tasks: startup

[Run]
Filename: "{app}\DailyLife.exe"; Description: "Abrir o Daily Life agora"; Flags: nowait postinstall skipifsilent

[Code]
const
  RUN_KEY = 'Software\Microsoft\Windows\CurrentVersion\Run';

{ Fechar a janela só esconde o app na bandeja: pede para ele sair de verdade. }
procedure AskAppToQuit;
var
  Request: Variant;
begin
  try
    Request := CreateOleObject('WinHttp.WinHttpRequest.5.1');
    Request.SetTimeouts(1000, 1000, 1000, 1000);
    Request.Open('POST', 'http://127.0.0.1:' + ExpandConstant('{param:port|5055}') + '/api/janela/sair', False);
    Request.SetRequestHeader('Content-Type', 'application/json');
    Request.Send('{}');
    Sleep(3000);
  except
    { O app não estava aberto: nada a fazer. }
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  AskAppToQuit;
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  AskAppToQuit;
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    { A opção pode ter sido ligada depois, nas Configurações do app. }
    RegDeleteValue(HKCU, RUN_KEY, 'DailyLife');
    if not UninstallSilent then
      MsgBox('Seus dados não foram apagados. Eles continuam em:' + #13#10 + ExpandConstant('{userappdata}\Daily Life'), mbInformation, MB_OK);
  end;
end;
