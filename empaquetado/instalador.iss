; Instalador de RemotePad (Inno Setup 6). Lo genera empaquetar.py con /DMyAppVersion.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
AppId={{763E806A-4CAA-4C56-BD19-4B7162D4C00A}
AppName=RemotePad
AppVersion={#MyAppVersion}
AppVerName=RemotePad {#MyAppVersion}
AppPublisher=RemotePad
DefaultDirName={autopf}\RemotePad
DefaultGroupName=RemotePad
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=RemotePad-Instalador-{#MyAppVersion}
SetupIconFile=..\remotepad.ico
UninstallDisplayIcon={app}\RemotePad.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear un icono en el escritorio"; GroupDescription: "Accesos:"
Name: "firewall"; Description: "Permitir que los moviles de mi red se conecten (Firewall de Windows, red privada)"; GroupDescription: "Red:"

[Files]
Source: "..\build\remotepad\RemotePad\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\build\remotepadservidor\RemotePadServidor\*"; DestDir: "{app}\servidor"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\build\remotepaddespertador\RemotePadDespertador\*"; DestDir: "{app}\despertador"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\RemotePad"; Filename: "{app}\RemotePad.exe"
Name: "{group}\Desinstalar RemotePad"; Filename: "{uninstallexe}"
Name: "{autodesktop}\RemotePad"; Filename: "{app}\RemotePad.exe"; Tasks: escritorio
; Mismo nombre que usaba el despertador de desarrollo: lo sustituye.
Name: "{userstartup}\RemotePad despertador"; Filename: "{app}\despertador\RemotePadDespertador.exe"; WorkingDir: "{app}\despertador"

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""RemotePad servidor"" dir=in action=allow program=""{app}\servidor\RemotePadServidor.exe"" enable=yes profile=private"; Flags: runhidden; Tasks: firewall
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""RemotePad despertador"" dir=in action=allow program=""{app}\despertador\RemotePadDespertador.exe"" enable=yes profile=private"; Flags: runhidden; Tasks: firewall
Filename: "{app}\RemotePad.exe"; Description: "Abrir RemotePad"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""RemotePad servidor"""; Flags: runhidden; RunOnceId: "QuitarFirewallServidor"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""RemotePad despertador"""; Flags: runhidden; RunOnceId: "QuitarFirewallDespertador"

[UninstallDelete]
; El acceso de inicio lo crea el panel en la carpeta de inicio del usuario.
Type: files; Name: "{userstartup}\RemotePad.lnk"
Type: files; Name: "{userstartup}\RemotePad despertador.lnk"
