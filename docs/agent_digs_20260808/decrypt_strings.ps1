$ErrorActionPreference = "Stop"
$exe = "C:\tmp\gs139\GameScript139.exe"
$bytes = [System.IO.File]::ReadAllBytes($exe)
$asm = [System.Reflection.Assembly]::Load($bytes)
$t = $asm.GetType("NWLFP6HZsKdxwd2bsw5.RwU4kqHvJsUfGu6JDcD", $false)
if (-not $t) { Write-Output "TYPE_NOT_FOUND"; exit 1 }
Write-Output ("type: " + $t.FullName)
$dec = $t.GetMethod("kwNHFygbLQ", [System.Reflection.BindingFlags]"Static,NonPublic,Public")
if (-not $dec) { Write-Output "DECRYPTOR_NOT_FOUND"; exit 1 }
Write-Output "decryptor OK"
# warmup via log helper I8Te3CkC6O
$warm = $null
$types = @()
try { $types = $asm.GetTypes() } catch [System.Reflection.ReflectionTypeLoadException] { $types = $_.Exception.Types | Where-Object { $_ -ne $null } }
foreach ($ty in $types) {
    $m = $ty.GetMethod("I8Te3CkC6O", [System.Reflection.BindingFlags]"Static,Public,NonPublic")
    if ($m) { $warm = $m; break }
}
if ($warm) {
    Write-Output ("warmup found in: " + $warm.DeclaringType.FullName)
    try { $null = $warm.Invoke($null, @([string]"")) } catch { Write-Output ("warmup threw (expected ok): " + $_.Exception.InnerException.Message) }
} else {
    Write-Output "WARMUP_NOT_FOUND"
}
# test a couple of keys
foreach ($k in 7236, 7254, 7276, 7296, 7320, 7358, 8254, 5282) {
    try {
        $s = $dec.Invoke($null, @([int]$k))
        Write-Output ("key " + $k + " = [" + $s + "]")
    } catch {
        Write-Output ("key " + $k + " ERR: " + $_.Exception.InnerException.Message)
    }
}
# full dump 0..29999
$out = "C:\tmp\agent_out\decrypted_strings.txt"
$sw = New-Object System.IO.StreamWriter($out, $false, [System.Text.Encoding]::UTF8)
for ($k = 0; $k -lt 30000; $k++) {
    try {
        $s = $dec.Invoke($null, @([int]$k))
        if ($s -ne $null -and $s.Length -gt 0 -and $s.Length -lt 1024) {
            $sw.WriteLine($k.ToString() + "`t" + $s)
        }
    } catch {}
}
$sw.Close()
Write-Output "DUMP_DONE"
