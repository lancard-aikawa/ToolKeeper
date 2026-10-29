# Write machine environment variables chosen in ToolKeeper (docs/design.md section 3.7).
# ToolKeeper runs this elevated (one UAC prompt):
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\env-set.ps1 -Request <env-request.json> -Log <file>
#
# The request is a JSON array of {"name": ..., "old": ..., "new": ...} written by ToolKeeper with ASCII escapes.
# Every value is compared with "old" (read without expanding %...%) BEFORE anything is written; if one differs,
# nothing is written. Values keep their registry type (REG_EXPAND_SZ stays REG_EXPAND_SZ).
# Only existing values are changed; this script never creates or deletes a variable.
#
# Keep this file ASCII only. Windows PowerShell 5.1 reads a file without BOM as the ANSI code page
# (cp932 on Japanese Windows), so non-ASCII text breaks the parser. pwsh (7) is not always installed.
# Exit codes: 0 = done, 10 = bad request, 11 = a value changed since it was chosen, 12 = write failed.
param(
    [Parameter(Mandatory = $true)][string]$Request,
    [Parameter(Mandatory = $true)][string]$Log,
    # Tests only: write to HKCU\<TestKey> instead of the machine key (no elevation needed)
    [string]$TestKey = ""
)
$ErrorActionPreference = "Stop"

function Say([string]$Text) {
    Add-Content -LiteralPath $Log -Value $Text -Encoding ASCII
}

try {
    # Not piped: in 5.1 a piped ConvertFrom-Json emits the whole array as one object
    $parsed = ConvertFrom-Json -InputObject (Get-Content -LiteralPath $Request -Raw -Encoding UTF8)
    $items = @($parsed)
} catch {
    Say "cannot read request: $_"
    exit 10
}
if ($items.Count -eq 0) { Say "empty request"; exit 10 }

$sub = "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
$opt = [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
try {
    if ($TestKey) {
        $sub = $TestKey
        $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($sub, $true)
    } else {
        $key = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey($sub, $true)
    }
    if ($null -eq $key) { throw "key not found" }
} catch {
    Say "cannot open HKLM\$sub for writing: $_"
    exit 12
}

foreach ($it in $items) {
    if (-not $it.name -or $null -eq $it.new) { Say "bad item"; $key.Close(); exit 10 }
    $cur = $key.GetValue([string]$it.name, $null, $opt)
    if ($null -eq $cur) { Say "$($it.name): not set"; $key.Close(); exit 11 }
    if ($cur -cne [string]$it.old) { Say "$($it.name): changed since it was chosen"; $key.Close(); exit 11 }
}

try {
    foreach ($it in $items) {
        $kind = $key.GetValueKind([string]$it.name)
        $key.SetValue([string]$it.name, [string]$it.new, $kind)
        Say "$($it.name): written ($kind)"
    }
} catch {
    Say "write failed: $_"
    $key.Close()
    exit 12
}
$key.Close()
exit 0
