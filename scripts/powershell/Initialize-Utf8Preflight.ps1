[CmdletBinding()]
param([switch]$Check)

$ErrorActionPreference = 'Stop'

function New-Utf8NoBomEncoding {
    return New-Object System.Text.UTF8Encoding($false)
}

function Test-Utf8NoBomEncoding {
    param([System.Text.Encoding]$Encoding)
    return $null -ne $Encoding -and $Encoding.WebName -eq 'utf-8' -and $Encoding.GetPreamble().Length -eq 0
}

function Initialize-Utf8Preflight {
    $utf8NoBom = New-Utf8NoBomEncoding
    [Console]::InputEncoding = $utf8NoBom
    [Console]::OutputEncoding = $utf8NoBom
    Set-Variable -Name OutputEncoding -Scope Global -Value $utf8NoBom -Force
    [Environment]::SetEnvironmentVariable('PYTHONIOENCODING', 'utf-8', 'Process')
    $global:KadodeUtf8PreflightVersion = 1
}

function Test-Utf8Preflight {
    $outputEncoding = (Get-Variable -Name OutputEncoding -Scope Global -ErrorAction SilentlyContinue).Value
    return $global:KadodeUtf8PreflightVersion -eq 1 -and
        (Test-Utf8NoBomEncoding -Encoding ([Console]::InputEncoding)) -and
        (Test-Utf8NoBomEncoding -Encoding ([Console]::OutputEncoding)) -and
        (Test-Utf8NoBomEncoding -Encoding $outputEncoding) -and
        [Environment]::GetEnvironmentVariable('PYTHONIOENCODING', 'Process') -eq 'utf-8'
}

function Test-Utf8ReadBack {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)

    $utf8NoBom = New-Utf8NoBomEncoding
    $expected = [System.IO.File]::ReadAllText($LiteralPath, $utf8NoBom)
    $nodeBase64 = & node.exe -e 'process.stdout.write(require(''fs'').readFileSync(process.argv[1]).toString(''base64''))' -- $LiteralPath
    if ($LASTEXITCODE -ne 0) { return $false }
    $pythonBase64 = & python.exe -c 'import base64,pathlib,sys;sys.stdout.write(base64.b64encode(pathlib.Path(sys.argv[1]).read_bytes()).decode())' $LiteralPath
    if ($LASTEXITCODE -ne 0) { return $false }
    $nodeText = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($nodeBase64))
    $pythonText = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($pythonBase64))
    return $nodeText -ceq $expected -and $pythonText -ceq $expected
}

if ($Check) {
    if (-not (Test-Utf8Preflight)) {
        [Console]::Error.WriteLine('UTF-8 preflight has not been applied or is invalid.')
        exit 1
    }
    exit 0
}

Initialize-Utf8Preflight
