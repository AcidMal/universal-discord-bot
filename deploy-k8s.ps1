# Deploy to the current kubectl context. See deploy_k8s.py --help.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$python = $null
foreach ($name in @("python", "python3")) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) {
        $python = $cmd.Source
        break
    }
}
if (-not $python) {
    throw "Python is not installed. Install Python 3, then run this script again."
}

& $python (Join-Path $PSScriptRoot "deploy_k8s.py") @args
exit $LASTEXITCODE
