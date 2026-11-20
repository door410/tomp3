' Create the desktop shortcut "tomp3". PURE ASCII ONLY.
Option Explicit
Dim sh, fso, base, lnk
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)

Set lnk = sh.CreateShortcut(sh.SpecialFolders("Desktop") & "\tomp3.lnk")
lnk.TargetPath       = sh.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\wscript.exe"
lnk.Arguments        = """" & base & "\start.vbs"""
lnk.WorkingDirectory = base
lnk.IconLocation     = base & "\icon.ico,0"
lnk.Description      = "Video URL to MP3"
lnk.Save
