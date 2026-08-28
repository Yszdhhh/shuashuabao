' ShuaBao OD12 Web Shell launcher.
' Defaults to isolated %LOCALAPPDATA%\ShuaBaoWeb.  Set SHUABAO_APP_DATA explicitly
' before launch only when deliberately sharing the native shell's data and locks.
' Runtime: Python 3.13 with full PySide6 (QtWebEngine)
Option Explicit

Dim sh, shellApp, fso, root, pyw, appData
Set sh = CreateObject("WScript.Shell")
Set shellApp = CreateObject("Shell.Application")
Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))

sh.Environment("PROCESS")("SHUABAO_SHELL") = "web"
appData = Trim(sh.Environment("PROCESS")("SHUABAO_APP_DATA"))
If appData = "" Then
    appData = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\ShuaBaoWeb")
End If
sh.Environment("PROCESS")("SHUABAO_APP_DATA") = appData
sh.Environment("PROCESS")("PYTHONPATH") = root & "\src"
sh.CurrentDirectory = root

pyw = "C:\Users\10639\AppData\Local\Programs\Python\Python313\pythonw.exe"
If Not fso.FileExists(pyw) Then
    MsgBox "Python 3.13 runtime not found: " & pyw, 16, "ShuaBao Web Shell"
    WScript.Quit 1
End If

shellApp.ShellExecute pyw, """" & root & "\desktop_app.py""", root, "runas", 1
