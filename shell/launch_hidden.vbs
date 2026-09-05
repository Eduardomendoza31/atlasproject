' Lanza Atlas usando python.exe del entorno virtual (el unico que carga
' bien todas las dependencias via el acceso directo - pythonw.exe se
' relanza internamente en Windows y pierde el entorno virtual) pero sin
' mostrar la ventana de consola, usando WScript.Shell.Run con estilo de
' ventana oculto (0).
Set objShell = CreateObject("WScript.Shell")
strPython = """C:\Users\Eduardo Mendoza\Desktop\ATLAS\.venv\Scripts\python.exe"""
strScript = """C:\Users\Eduardo Mendoza\Desktop\ATLAS\shell\main.py"""
objShell.CurrentDirectory = "C:\Users\Eduardo Mendoza\Desktop\ATLAS"
objShell.Run strPython & " " & strScript, 0, False
