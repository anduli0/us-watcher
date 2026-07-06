' US-WATCHER hidden autostart launcher (IDEMPOTENT).
' Starts API (8088), WEB (3002), WORKER, and ensures the Tailscale Funnel,
' all without visible console windows. Idempotent: a component is launched only
' if it is not already up, so re-running at logon OR from the health-guard never
' creates duplicate supervisors. Each .bat is itself single-instance + auto-restart.
Dim sh, base
Set sh = CreateObject("WScript.Shell")
base = "C:\Users\andul\us-watcher\"

If Not PortUp(8088) Then sh.Run "cmd /c """ & base & "_usw-api.bat""", 0, False
WScript.Sleep 1500
If Not PortUp(3002) Then sh.Run "cmd /c """ & base & "_usw-web.bat""", 0, False
' Worker has no port; its .bat is single-instance via a lockfile, so launching it
' again is a safe no-op (the duplicate sees the held lock and exits).
sh.Run "cmd /c """ & base & "_usw-worker.bat""", 0, False
WScript.Sleep 1000
sh.Run "cmd /c ""C:\Program Files\Tailscale\tailscale.exe"" funnel --bg --https=10000 3002", 0, False

Function PortUp(port)
  ' True if something is accepting TCP connections on 127.0.0.1:port.
  Dim cmd
  cmd = "powershell -NoProfile -Command ""try { $c = New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1'," & port & "); $c.Close(); exit 0 } catch { exit 1 }"""
  PortUp = (sh.Run(cmd, 0, True) = 0)
End Function
