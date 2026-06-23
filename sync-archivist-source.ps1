# Sync Archivist backend source into the Nix build context.
# Run from the Fauxnix workspace root (E:\Fauxnix).

$src = "E:\Archivist\app"
$dst = "E:\Fauxnix\remote-nixos\archivist_app"

if (-not (Test-Path -LiteralPath $src)) {
    Write-Error "Archivist source not found at $src"
    exit 1
}

Write-Host "Syncing Archivist app source..."
Write-Host "  from: $src"
Write-Host "  to:   $dst"

# Remove old files
if (Test-Path -LiteralPath $dst) {
    Remove-Item -Recurse -Force "$dst\*" -ErrorAction SilentlyContinue
}

New-Item -ItemType Directory -Path $dst -Force | Out-Null

# Copy Python files only (.py, .txt, .json, .md)
Get-ChildItem -Path $src -Recurse -File | Where-Object {
    $_.Extension -match '\.(py|txt|json|md|yaml|yml)$'
} | ForEach-Object {
    $rel = $_.FullName.Substring($src.Length + 1)
    $target = Join-Path $dst $rel
    $targetDir = Split-Path $target -Parent
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    Copy-Item -LiteralPath $_.FullName -Destination $target
}

# Keep the bundled backend writable when it runs from the read-only Nix store.
$configPath = Join-Path $dst "config.py"
if (Test-Path -LiteralPath $configPath) {
    $configText = Get-Content -LiteralPath $configPath -Raw
    $dataDirPatch = @'
DATA_DIR = Path(
    os.getenv(
        "ARCHIVIST_DATA_DIR",
        os.getenv("FAUXNIX_ARCHIVIST_DATA", str(BASE_DIR / "data")),
    )
).expanduser()
'@.Trim()
    $configText = $configText.Replace('DATA_DIR = BASE_DIR / "data"', $dataDirPatch)
    Set-Content -LiteralPath $configPath -Value $configText -NoNewline
}

# Serve generated previews/thumbs from the configured runtime data directory.
$mainPath = Join-Path $dst "main.py"
if (Test-Path -LiteralPath $mainPath) {
    $mainText = Get-Content -LiteralPath $mainPath -Raw
    $mainText = $mainText.Replace(
        'app.mount("/data", StaticFiles(directory="data"), name="data")',
        'app.mount("/data", StaticFiles(directory=str(DATA_DIR)), name="data")'
    )
    Set-Content -LiteralPath $mainPath -Value $mainText -NoNewline
}

$count = (Get-ChildItem -Path $dst -Recurse -File).Count
Write-Host "Copied $count files. Ready for Nix build."
