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

$count = (Get-ChildItem -Path $dst -Recurse -File).Count
Write-Host "Copied $count files. Ready for Nix build."
