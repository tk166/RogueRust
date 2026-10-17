# The environment THIS SHELL IS MISSING, and the reason most of the setup
# failures on this machine happened. USERPROFILE, TEMP, windir and
# NUMBER_OF_PROCESSORS are about all that survive; LOCALAPPDATA, APPDATA,
# ProgramFiles(x86) and PROCESSOR_ARCHITECTURE are null.
#
# What that costs, both met in practice:
#   * dotnet-install.ps1 cannot detect the architecture and installs nothing.
#   * NuGet restore dies with "Value cannot be null. (Parameter 'path1')":
#     NuGet.Configuration.XPlatMachineWideSetting calls Path.Combine on
#     ProgramFiles(x86) to find the machine-wide config.
#   * MSBuild reuses worker nodes for 15 minutes, so a node started while the
#     environment was still broken keeps failing AFTER it is fixed - which is
#     why the errors stayed pinned to the same two projects. Hence
#     MSBUILDDISABLENODEREUSE.
#
# Dot-source it:  . "$PSScriptRoot\env.ps1"

$StandardEnv = @{
  "DOTNET_ROOT"                 = "C:\Users\TK11\AppData\Local\Microsoft\dotnet"
  "DOTNET_CLI_HOME"             = "C:\Users\TK11"
  "DOTNET_CLI_TELEMETRY_OPTOUT" = "1"
  "DOTNET_NOLOGO"               = "1"
  "DOTNET_SKIP_FIRST_TIME_EXPERIENCE" = "1"
  "MSBUILDDISABLENODEREUSE"     = "1"
  "USERPROFILE"                 = "C:\Users\TK11"
  "USERNAME"                    = "TK11"
  "USERDOMAIN"                  = "H610"
  "LOCALAPPDATA"                = "C:\Users\TK11\AppData\Local"
  "APPDATA"                     = "C:\Users\TK11\AppData\Roaming"
  "HOMEDRIVE"                   = "C:"
  "HOMEPATH"                    = "\Users\TK11"
  "TEMP"                        = "C:\Users\TK11\AppData\Local\Temp"
  "TMP"                         = "C:\Users\TK11\AppData\Local\Temp"
  "ProgramData"                 = "C:\ProgramData"
  "ALLUSERSPROFILE"             = "C:\ProgramData"
  "ProgramFiles"                = "C:\Program Files"
  "ProgramFiles(x86)"           = "C:\Program Files (x86)"
  "ProgramW6432"                = "C:\Program Files"
  "CommonProgramFiles"          = "C:\Program Files\Common Files"
  "CommonProgramFiles(x86)"     = "C:\Program Files (x86)\Common Files"
  "SystemRoot"                  = "C:\Windows"
  "windir"                      = "C:\Windows"
  # MSBuild reads $(OS) straight from this environment variable. Empty, it stops being
  # "Windows_NT" and NativeAOT's cross-OS guard flips the wrong way round: it sees a win
  # target and concludes you are cross-compiling from Linux, then refuses to build.
  "OS"                          = "Windows_NT"
  "PROCESSOR_ARCHITECTURE"      = "AMD64"
  "PATHEXT"                     = ".COM;.EXE;.BAT;.CMD"
  "NUGET_PACKAGES"              = "C:\Users\TK11\.nuget\packages"
  "HTTP_PROXY"                  = "http://127.0.0.1:7897"
  "HTTPS_PROXY"                 = "http://127.0.0.1:7897"
  "NO_PROXY"                    = "localhost,127.0.0.1"
  "PATH"                        = "C:\Users\TK11\AppData\Local\Microsoft\dotnet;C:\Windows\System32;C:\Windows"
}
