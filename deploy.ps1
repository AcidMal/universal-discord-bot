# Universal deploy for Windows PowerShell.
# Requires Docker Desktop (docker compose).
param(
    [switch]$NonInteractive,
    [int]$Replicas = 1,
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

if ($Replicas -lt 1) {
    throw "Replicas must be a positive integer."
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is not installed. Install Docker Desktop, then run this script again."
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker is installed but the daemon is not running."
}

function Get-Kv([string]$Key) {
    $line = Select-String -Path .env -Pattern "^$Key=" | Select-Object -Last 1
    if (-not $line) { return "" }
    return ($line.Line -replace "^$Key=", "")
}

function Set-Kv([string]$Key, [string]$Value) {
    $lines = @()
    if (Test-Path .env) { $lines = Get-Content .env }
    $found = $false
    $next = foreach ($line in $lines) {
        if ($line -like "$Key=*") {
            $found = $true
            "$Key=$Value"
        } else {
            $line
        }
    }
    if (-not $found) { $next += "$Key=$Value" }
    Set-Content -Path .env -Value $next
}

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "Created .env from .env.example"
}

function Prompt-Value([string]$Key, [string]$Label, [switch]$Secret) {
    $current = Get-Kv $Key
    if ($current) { return }
    $fromEnv = [Environment]::GetEnvironmentVariable($Key)
    if ($fromEnv) { Set-Kv $Key $fromEnv; return }
    if ($NonInteractive) { return }
    if ($Secret) {
        $secure = Read-Host $Label -AsSecureString
        $entered = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        )
    } else {
        $entered = Read-Host $Label
    }
    if ($entered) { Set-Kv $Key $entered }
}

Prompt-Value DISCORD_TOKEN "Discord bot token" -Secret
Prompt-Value DISCORD_CLIENT_ID "Discord application client ID"
Prompt-Value DISCORD_CLIENT_SECRET "Discord application client secret" -Secret

if (-not (Get-Kv PUBLIC_URL)) {
    if ($NonInteractive) {
        $url = [Environment]::GetEnvironmentVariable("PUBLIC_URL")
        if (-not $url) { $url = "http://localhost:5173" }
        Set-Kv PUBLIC_URL $url
    } else {
        $entered = Read-Host "Public dashboard URL [http://localhost:5173]"
        if (-not $entered) { $entered = "http://localhost:5173" }
        Set-Kv PUBLIC_URL $entered
    }
}

if (-not (Get-Kv SESSION_SECRET)) {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    Set-Kv SESSION_SECRET (([BitConverter]::ToString($bytes) -replace "-", "").ToLower())
}

if (-not (Get-Kv SHARD_COUNT)) { Set-Kv SHARD_COUNT "0" }
Set-Kv NODE_ID ""

$composeArgs = @("compose", "up", "-d")
if (-not $NoBuild) { $composeArgs += "--build" }
if ($Replicas -gt 1) { $composeArgs += @("--scale", "bot=$Replicas") }

Write-Host "Starting Postgres, API, dashboard, and $Replicas bot replica(s)..."
& docker @composeArgs
if ($LASTEXITCODE -ne 0) { throw "docker compose up failed" }

$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 3
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch {
        Start-Sleep -Seconds 2
    }
}

$clientId = Get-Kv DISCORD_CLIENT_ID
$publicUrl = (Get-Kv PUBLIC_URL).TrimEnd("/")
if (-not $publicUrl) { $publicUrl = "http://localhost:5173" }

Write-Host ""
Write-Host "Dashboard: $publicUrl"
Write-Host "API health: http://localhost:8000/health"
Write-Host "Command reference: COMMANDS.md"
Write-Host ""
Write-Host "Discord Developer Portal"
Write-Host "  1. OAuth2 redirect: $publicUrl/auth/callback"
Write-Host "  2. Privileged intents: Message Content, Server Members"
Write-Host "  3. Invite the bot:"
if ($clientId) {
    Write-Host "     https://discord.com/oauth2/authorize?client_id=$clientId&scope=bot%20applications.commands&permissions=1099780156438"
} else {
    Write-Host "     Set DISCORD_CLIENT_ID in .env, then run .\deploy.ps1 again."
}

if (-not $ready) {
    throw "The API did not answer /health yet. Check logs with: docker compose logs api"
}

Write-Host ""
Write-Host "API is up. Slash commands sync after the bot connects."
