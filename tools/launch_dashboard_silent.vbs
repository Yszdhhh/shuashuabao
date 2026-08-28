' Launch ShuaBao dashboard silently without any console window popup.
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
venvPyw = root & "\.venv\Scripts\pythonw.exe"
app = root & "\desktop_app.py"

' Terminate only an existing dashboard process for this exact project entrypoint.
On Error Resume Next
Set wmi = GetObject("winmgmts:")
Set procs = wmi.ExecQuery("Select * from Win32_Process Where Name='python.exe' Or Name='pythonw.exe'")
For Each p In procs
  path = ""
  cmd = ""
  path = p.ExecutablePath
  cmd = p.CommandLine
  If InStr(1, cmd, """" & app & """", 1) > 0 Then p.Terminate
Next
On Error GoTo 0

' Always use the project virtual environment; pyvenv.cfg's home is its base interpreter.
pyw = venvPyw
If Not fso.FileExists(pyw) Then
  WScript.Echo "Missing project virtual environment interpreter: " & pyw
  WScript.Quit 1
End If

Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = root
sh.Environment("PROCESS")("VIRTUAL_ENV") = root & "\.venv"
sh.Environment("PROCESS")("PYTHONPATH") = root & "\.venv\Lib\site-packages"
sh.Environment("PROCESS")("PYTHONNOUSERSITE") = "1"

' 1 keeps the Qt dashboard visible while pythonw suppresses a console window.
sh.Run """" & pyw & """ """ & app & """", 1, False
