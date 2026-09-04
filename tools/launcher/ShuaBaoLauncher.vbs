' Stable desktop trampoline. No console. Delegates to ShuaBaoLauncher.ps1 beside this file.
Option Explicit

Dim sh, fso, launcherDir, ps1, cmd, rc
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

launcherDir = fso.GetParentFolderName(WScript.ScriptFullName)
ps1 = launcherDir & "\ShuaBaoLauncher.ps1"
If Not fso.FileExists(ps1) Then
    MsgBox "Missing ShuaBaoLauncher.ps1:" & vbCrLf & ps1, 16, "ShuaBao launch failed"
    WScript.Quit 1
End If

cmd = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & ps1 & """"
rc = sh.Run(cmd, 0, True)
If rc <> 0 Then
    WScript.Quit rc
End If
