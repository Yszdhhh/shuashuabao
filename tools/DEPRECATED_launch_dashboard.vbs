' Launch ShuaBao dashboard: no console, GUI visible, inherit admin from the shortcut.
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
venvPyw = root & "\.venv\Scripts\pythonw.exe"
app = root & "\desktop_app.py"

' Previous SW_HIDE launches can sit invisible and hold ShuaBao.lock.
On Error Resume Next
Set wmi = GetObject("winmgmts:")
Set procs = wmi.ExecQuery("Select * from Win32_Process Where Name='pythonw.exe'")
For Each p In procs
  path = ""
  cmd = ""
  path = p.ExecutablePath
  cmd = p.CommandLine
  If InStr(1, path, venvPyw, 1) > 0 Then p.Terminate
  If InStr(1, cmd, "desktop_app.py", 1) > 0 Then p.Terminate
Next
On Error GoTo 0

home = ""
cfg = root & "\.venv\pyvenv.cfg"
If fso.FileExists(cfg) Then
  Set ts = fso.OpenTextFile(cfg, 1)
  Do Until ts.AtEndOfStream
    line = ts.ReadLine
    If Left(line, 7) = "home = " Then home = Mid(line, 8)
  Loop
  ts.Close
End If
pyw = home & "\pythonw.exe"
If home = "" Or Not fso.FileExists(pyw) Then pyw = venvPyw

Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = root
sh.Environment("PROCESS")("VIRTUAL_ENV") = root & "\.venv"
sh.Environment("PROCESS")("PYTHONPATH") = root & "\.venv\Lib\site-packages"
sh.Environment("PROCESS")("PYTHONNOUSERSITE") = "1"
' 1 = normal window. Style 0 hid the Qt UI as well as the console.
sh.Run """" & pyw & """ """ & app & """", 1, False
