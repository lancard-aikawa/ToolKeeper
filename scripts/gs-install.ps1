# Install a new Ghostscript and point PATH at it (docs/design.md section 3.3).
# ToolKeeper runs this elevated (one UAC prompt) after checking the installer's SHA-256 and signature:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\gs-install.ps1 -Installer <gsNNNNNw64.exe> -NewVersion 10.08.0 -OldVersion 10.05.1 -Log <file>
#
# 1. Read the bin folder of OldVersion from HKLM\SOFTWARE\GPL Ghostscript\<version> (GS_DLL) BEFORE installing:
#    the 10.08.0 installer removes the old version (folder, registry, uninstall entry) by itself (2026-10-28).
# 2. Run the NSIS installer with /S and wait.
# 3. Read the install folder of NewVersion from the registry.
# 4. In the machine and user PATH, replace the old bin folder with the new one, unless the installer already did
#    (10.08.0 does: it removes the old entry and appends the new one). PATH is read and written as REG_EXPAND_SZ
#    without expanding (keeps %SystemRoot% and the like). If the old folder is not in PATH, PATH is left as it is.
#
# Keep this file ASCII only. Windows PowerShell 5.1 reads a file without BOM as the ANSI code page
# (cp932 on Japanese Windows), so non-ASCII text breaks the parser. pwsh (7) is not always installed.
# Exit codes: 0 = done, 10 = installer failed, 11 = new version not found after install, 12 = PATH update failed.
param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [Parameter(Mandatory = $true)][string]$NewVersion,
    [string]$OldVersion = "",
    [Parameter(Mandatory = $true)][string]$Log
)
$ErrorActionPreference = "Stop"

function Say([string]$Text) {
    Add-Content -LiteralPath $Log -Value $Text -Encoding ASCII
}

function Get-GsBin([string]$Version) {
    $key = "HKLM:\SOFTWARE\GPL Ghostscript\$Version"
    if (-not (Test-Path $key)) { return $null }
    $dll = (Get-ItemProperty $key).GS_DLL
    if (-not $dll) { return $null }
    return Split-Path -Parent $dll
}

function Update-PathValue([Microsoft.Win32.RegistryKey]$Key, [string]$Old, [string]$New, [string]$Label) {
    $raw = $Key.GetValue("Path", $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    if ($null -eq $raw) { Say "PATH ($Label): not set"; return }
    $kind = $Key.GetValueKind("Path")
    # If the installer already added the new folder, drop the old one instead of replacing it (no duplicates).
    $hasNew = @($raw -split ";" | Where-Object { $_.TrimEnd("\") -ieq $New.TrimEnd("\") }).Count -gt 0
    $changed = $false
    $parts = foreach ($p in ($raw -split ";")) {
        if ($p.TrimEnd("\") -ieq $Old.TrimEnd("\")) {
            $changed = $true
            if (-not $hasNew) { $New }
        } else { $p }
    }
    if (-not $changed) {
        if ($hasNew) { Say "PATH ($Label): already points to $New" } else { Say "PATH ($Label): old folder not found, left as it is" }
        return
    }
    $Key.SetValue("Path", ($parts -join ";"), $kind)
    Say "PATH ($Label): $Old -> $New"
}

$oldBin = $null
if ($OldVersion) {
    $oldBin = Get-GsBin $OldVersion
    if (-not $oldBin) { Say "old version $OldVersion not found in the registry, PATH will be left as it is" }
}
Say "installer: $Installer"
$p = Start-Process -FilePath $Installer -ArgumentList "/S" -Wait -PassThru
Say "installer exit code: $($p.ExitCode)"
if ($p.ExitCode -ne 0) { exit 10 }

$newBin = Get-GsBin $NewVersion
if (-not $newBin -or -not (Test-Path (Join-Path $newBin "gswin64c.exe"))) {
    Say "new version $NewVersion not found in the registry after install"
    exit 11
}
Say "new bin: $newBin"

if ($oldBin) {
    try {
        $machine = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey("SYSTEM\CurrentControlSet\Control\Session Manager\Environment", $true)
        Update-PathValue $machine $oldBin $newBin "machine"
        $machine.Close()
        $user = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey("Environment", $true)
        Update-PathValue $user $oldBin $newBin "user"
        $user.Close()
    } catch {
        Say "PATH update failed: $($_.Exception.Message)"
        exit 12
    }
    # Tell running programs (Explorer) that the environment changed, so new windows see the new PATH.
    Add-Type -Namespace TK -Name Native -MemberDefinition '[DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern System.IntPtr SendMessageTimeout(System.IntPtr h, uint msg, System.UIntPtr w, string l, uint flags, uint timeout, out System.UIntPtr result);'
    $r = [System.UIntPtr]::Zero
    [TK.Native]::SendMessageTimeout([System.IntPtr]0xffff, 0x1A, [System.UIntPtr]::Zero, "Environment", 2, 5000, [ref]$r) | Out-Null
}
Say "done"
exit 0
