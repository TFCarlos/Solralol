$ErrorActionPreference = "Stop"

Set-Location "D:\Accesos\Desktop\Solralol"

$directories = @(
    "app",
    "app\ui",
    "app\services",
    "app\models",
    "app\utils",
    "data",
    "logs"
)

foreach ($directory in $directories) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

$files = @(
    "app\__init__.py",
    "app\models\__init__.py",
    "app\models\game_types.py",
    "app\services\__init__.py",
    "app\services\game_service.py",
    "app\services\game_calculator.py",
    "app\ui\__init__.py",
    "app\ui\styles.py",
    "app\ui\inventory.py",
    "app\ui\champion_card.py",
    "app\ui\overlay_window.py",
    "app\ui\control_window.py",
    "app\utils\__init__.py",
    "app\utils\cache.py"
)

foreach ($file in $files) {
    if (-not (Test-Path $file)) {
        New-Item -ItemType File -Force -Path $file | Out-Null
    }
}

$gitignore = @"
.venv/
__pycache__/
*.py[cod]
*.log
config.local.json
data/item_icons/
data/champion_icons/
data/champion_data/
"@

Set-Content -Path ".gitignore" -Value $gitignore -Encoding utf8

Write-Host "Estructura creada correctamente." -ForegroundColor Green
Get-ChildItem -Recurse -File | Select-Object FullName
