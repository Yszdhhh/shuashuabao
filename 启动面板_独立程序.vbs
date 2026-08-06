Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir

' 自动尝试定位绝对路径，避免管理员权限下环境变量丢失
pythonwPath = "C:\Users\10639\AppData\Local\hermes\hermes-agent\venv\Scripts\pythonw.exe"

If Not fso.FileExists(pythonwPath) Then
    pythonwPath = "pythonw.exe"
End If

WshShell.Run """" & pythonwPath & """ """ & scriptDir & "\desktop_app.py""", 0, False
