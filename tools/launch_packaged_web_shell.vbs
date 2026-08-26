' Packaged OD12 Web Shell launcher.  Must live beside ShuaBao.exe.
Option Explicit

Dim sh, shellApp, fso, root, appData
Set sh = CreateObject("WScript.Shell")
Set shellApp = CreateObject("Shell.Application")
Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(WScript.ScriptFullName)
If Not fso.FileExists(root & "\ShuaBao.exe") Then
    MsgBox "ShuaBao.exe not found beside this launcher.", 16, "ShuaBao Web Shell"
    WScript.Quit 1
End If

sh.Environment("PROCESS")("SHUABAO_SHELL") = "web"
appData = Trim(sh.Environment("PROCESS")("SHUABAO_APP_DATA"))
If appData = "" Then
    appData = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\ShuaBaoWeb")
End If
sh.Environment("PROCESS")("SHUABAO_APP_DATA") = appData

shellApp.ShellExecute root & "\ShuaBao.exe", "", root, "open", 1
