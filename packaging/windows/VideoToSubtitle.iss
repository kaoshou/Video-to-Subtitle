; Build the onedir payload, NOT a wrapper around the portable onefile EXE.
; ISCC /DAppVersion=... /DSourceDir=... /DOutputDir=... VideoToSubtitle.iss
#ifndef AppVersion
  #error AppVersion is required (read it from pyproject.toml)
#endif
#ifndef SourceDir
  #error SourceDir must point to the PyInstaller onedir output
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif
#if !FileExists(SourceDir + "\_internal\python311.dll")
  #error Missing onedir Python runtime; do not package the portable EXE
#endif

[Setup]
AppId=VideoToSubtitle
AppName=Video to Subtitle
AppVersion={#AppVersion}
AppPublisher=kaoshou
AppPublisherURL=https://github.com/kaoshou/Video-to-Subtitle
AppSupportURL=https://github.com/kaoshou/Video-to-Subtitle/issues
DefaultDirName={localappdata}\Programs\VideoToSubtitle
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0
WizardStyle=modern
DisableWelcomePage=no
SetupIconFile={#SourceDir}\_internal\app_icon.ico
UninstallDisplayIcon={app}\VideoToSubtitle.exe
UninstallDisplayName=Video to Subtitle
OutputDir={#OutputDir}
OutputBaseFilename=VideoToSubtitle-Setup-v{#AppVersion}
Compression=lzma2
SolidCompression=yes
CloseApplications=no
RestartApplications=no

[Languages]
Name: "zhTW"; MessagesFile: "compiler:Languages\ChineseTraditional.isl"

[Messages]
WelcomeLabel2=這將安裝 [name/ver] 到您的電腦。%n%n安裝包已內含 Python 與必要套件，不需另行準備執行環境。%n%n第一次使用語音模型仍需連線下載；CPU 可直接使用，NVIDIA 加速需相容的顯示卡與驅動。%n%n更新前請先關閉程式，避免中斷尚未完成的工作。
FinishedLabel=已完成 [name] 安裝。%n%n可從「開始」功能表啟動程式。更新或解除安裝不會移除使用者設定與模型快取。

[Tasks]
Name: "desktopicon"; Description: "建立桌面捷徑"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Video to Subtitle"; Filename: "{app}\VideoToSubtitle.exe"; WorkingDir: "{app}"; AppUserModelID: "kaoshou.subtitletranscriber.v2"
Name: "{userdesktop}\Video to Subtitle"; Filename: "{app}\VideoToSubtitle.exe"; WorkingDir: "{app}"; Tasks: desktopicon; AppUserModelID: "kaoshou.subtitletranscriber.v2"

[Run]
Filename: "{app}\VideoToSubtitle.exe"; Parameters: "--from-installer"; WorkingDir: "{app}"; Description: "啟動 Video to Subtitle"; Flags: nowait postinstall skipifsilent unchecked

; Intentionally no UninstallDelete: settings and model caches are user data.
