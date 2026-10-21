' VBScript silent runner for IDX Stock Signal Daily Pipeline
' Executes run_scheduled_pipeline.ps1 completely in background without popup console window.
Dim WshShell, FSO, ScriptDir, Runner, Cmd
Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
ScriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)
Runner = ScriptDir & "\run_scheduled_pipeline.ps1"

Cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & Runner & """"
WshShell.Run Cmd, 0, False
