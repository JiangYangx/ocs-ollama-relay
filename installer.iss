; JY 答题助手 · Windows 安装包脚本（Inno Setup 6）
; 生成方式：装好 Inno Setup 后，双击 tools/build_installer.bat，或用 ISCC 编译本文件。
; 产物：dist/JY-Relay-Setup-{版本}.exe

#define MyAppName "JY 答题助手"
#define MyAppVersion "1.5.0"
#define MyAppExeName "JY-Relay.exe"
#define MyAppRepo "https://github.com/JiangYangx/ocs-ollama-relay"

[Setup]
AppId={{8E4A2C91-6B7D-4E0A-9F3B-A1B2C3D4E5F6}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
DefaultDirName={autopf}\JY-Relay
DefaultGroupName={#MyAppName}
AppPublisher=JiangYangx
AppPublisherURL={#MyAppRepo}
AppSupportURL={#MyAppRepo}/issues
AppUpdatesURL={#MyAppRepo}/releases
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=dist
OutputBaseFilename=JY-Relay-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; 允许卸载时保留用户数据
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; \
  GroupDescription: "附加选项："
Name: "autostart"; Description: "开机自动启动（后台答题不弹窗）"; \
  GroupDescription: "附加选项："; Flags: checkedonce

[Files]
Source: "dist\JY-Relay.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\config.json"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist uninsneveruninstall
; README / 许可证随手带上
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--no-browser"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
  Parameters: "--no-browser"; Tasks: desktopicon
; 开机自启：写当前用户启动项（不需要管理员权限）
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
  Parameters: "--no-browser"; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; \
  Flags: nowait postinstall skipifsilent

[UninstallRun]

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if MsgBox('要同时删除题库、订正和答题记录吗？（选「否」则保留，下次安装可继续用）',
              mbConfirmation, MB_YESNO) = IDYES then
      DelTree(ExpandConstant('{app}'), True, True, True);
  end;
end;

[UninstallDelete]
; 注意：jy_data.db / bank.json 等用户数据默认保留，由上方询问决定

[Messages]
WelcomeLabel2=这将安装 [name/ver] 到你的电脑。%n%n安装完成后：桌面双击图标 → 点「开始答题」→ 复制配置到答题客户端，即可使用。
FinishedLabelNoIcons=安装完成！双击桌面图标即可开始使用。
FinishedLabel=安装完成！双击桌面图标即可开始使用。
