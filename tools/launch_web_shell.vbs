' ShuaBao Web Shell Preview Launcher (Experimental Branch).
' Isolated AppData: %LOCALAPPDATA%\ShuaBaoWeb
' Runtime: Python 3.13 with full PySide6 (QtWebEngine)
Option Explicit

Dim sh, fso, root, pyw
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))

sh.Environment("PROCESS")("SHUABAO_SHELL") = "web"
sh.Environment("PROCESS")("SHUABAO_APP_DATA") = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\ShuaBaoWeb"
sh.Environment("PROCESS")("PYTHONPATH") = root & "\src"
sh.CurrentDirectory = root

pyw = "C:\Users\10639\AppData\Local\Programs\Python\Python313\pythonw.exe"
If Not fso.FileExists(pyw) Then
    MsgBox "Python 3.13 runtime not found: " & pyw, 16, "ShuaBao Web Shell"
    WScript.Quit 1
End If

sh.Run """" & pyw & """ """ & root & "\desktop_app.py""", 1, False
