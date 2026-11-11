<#
.SYNOPSIS
  AI Trading Intelligence Windows kurulum dosyasını (…_x64-setup.exe) kendi bilgisayarınızda
  derler. GitHub Actions kullanılamadığında (ör. ücretsiz dakika bitti) içindir.

.DESCRIPTION
  Yönetici PowerShell'inde, depo ZIP'inin çıkarıldığı klasörde çalıştırın:

    cd C:\Kurulum\Can-claude-laughing-hawking-wmt8mo
    Get-ChildItem -Recurse | Unblock-File
    powershell -ExecutionPolicy Bypass -File .\deploy\derle-uygulama.ps1

  Eksikse winget ile kurar: Visual Studio 2022 Build Tools (C++), Rust, Node.js, uv (Python).
  İlk çalıştırmada indirme ~4 GB, süre 45-90 dakika; sonrakiler 10-20 dakika.
  Gerekli boş alan: en az 15 GB. Adımlar GitHub'daki derleme işiyle (desktop.yml) aynıdır.
#>
$ErrorActionPreference = "Stop"
$Kok = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Adim([string]$Metin) { Write-Host ""; Write-Host "==> $Metin" -ForegroundColor Cyan }
function Bilgi([string]$Metin) { Write-Host "    $Metin" }
function Hata([string]$Metin) { Write-Host ""; Write-Host "HATA: $Metin" -ForegroundColor Red; exit 1 }

function Yolu-Yenile {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
        [Environment]::GetEnvironmentVariable("Path", "User") + ";" + (Join-Path $env:USERPROFILE ".cargo\bin")
}

function Var([string]$Komut) { return [bool](Get-Command $Komut -ErrorAction SilentlyContinue) }

function Winget-Kur([string]$Kimlik, [string[]]$Ek = @()) {
    if (-not (Var "winget")) {
        Hata "winget bulunamadı. Microsoft Store'dan 'Uygulama Yükleyici' (App Installer) güncelleyin ve tekrar deneyin."
    }
    Bilgi "Kuruluyor: $Kimlik (birkaç dakika sürebilir)..."
    $argumanlar = @("install", "--id", $Kimlik, "-e", "--accept-package-agreements", "--accept-source-agreements", "--silent") + $Ek
    & winget @argumanlar
    # winget "zaten kurulu" durumunda da sıfırdan farklı kod dönebilir; asıl denetim aşağıda yapılır.
    Yolu-Yenile
}

function Calistir([string]$Aciklama, [scriptblock]$Is) {
    $eski = $ErrorActionPreference
    $ErrorActionPreference = "Continue"   # 5.1: araçların stderr çıktısı hata sayılmasın
    & $Is
    $kod = $LASTEXITCODE
    $ErrorActionPreference = $eski
    if ($kod -ne 0) { Hata "$Aciklama başarısız (çıkış kodu $kod). Ekranın görüntüsünü gönderin." }
}

if (-not (Test-Path (Join-Path $Kok "desktop\src-tauri\tauri.conf.json"))) {
    Hata "Betik depo klasörünün içinden çalıştırılmalı (deploy\derle-uygulama.ps1). Bulunan kök: $Kok"
}
$surum = (Get-Content (Join-Path $Kok "desktop\src-tauri\tauri.conf.json") -Raw | ConvertFrom-Json).version
Write-Host "AI Trading Intelligence $surum — Windows kurulum dosyası derleniyor" -ForegroundColor Green

# ---------------------------------------------------------------------------------------------
Adim "Ön denetimler"
$surucu = Get-PSDrive -Name ($Kok.Substring(0, 1))
if ($surucu.Free -lt 15GB) { Hata "Bu sürücüde en az 15 GB boş alan gerekli (şu an $([math]::Round($surucu.Free / 1GB, 1)) GB)." }
Yolu-Yenile

# ---------------------------------------------------------------------------------------------
Adim "Visual Studio 2022 Build Tools (C++ derleyici)"
$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
function Cpp-Var {
    if (-not (Test-Path $vswhere)) { return $false }
    $yol = & $vswhere -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    return [bool]$yol
}
if (-not (Cpp-Var)) {
    Bilgi "C++ derleme araçları yok; kuruluyor (~3 GB, 15-40 dakika)."
    Winget-Kur "Microsoft.VisualStudio.2022.BuildTools" @("--override", "--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended")
    if (-not (Cpp-Var)) { Hata "C++ derleme araçları kurulamadı. Bilgisayarı yeniden başlatıp betiği tekrar çalıştırın." }
}
Bilgi "C++ derleme araçları hazır."

# ---------------------------------------------------------------------------------------------
Adim "Rust"
if (-not (Var "cargo")) {
    Winget-Kur "Rustlang.Rustup"
    if (Var "rustup") { Calistir "Rust kurulumu" { & rustup default stable-x86_64-pc-windows-msvc } }
}
if (-not (Var "cargo")) { Hata "Rust kurulamadı. Bilgisayarı yeniden başlatıp betiği tekrar çalıştırın." }
Bilgi (& cargo --version)

# ---------------------------------------------------------------------------------------------
Adim "Node.js"
$nodeTamam = $false
if (Var "node") {
    $ana = [int]((& node --version).TrimStart("v").Split(".")[0])
    $nodeTamam = $ana -ge 20
}
if (-not $nodeTamam) {
    Winget-Kur "OpenJS.NodeJS.LTS"
    if (-not (Var "node")) { Hata "Node.js kurulamadı. Bilgisayarı yeniden başlatıp betiği tekrar çalıştırın." }
}
Bilgi "Node.js $(& node --version)"

# ---------------------------------------------------------------------------------------------
Adim "uv (Python)"
if (-not (Var "uv")) {
    Winget-Kur "astral-sh.uv"
    if (-not (Var "uv")) { Hata "uv kurulamadı. Bilgisayarı yeniden başlatıp betiği tekrar çalıştırın." }
}
Bilgi (& uv --version)

# ---------------------------------------------------------------------------------------------
Adim "İşlem motoru paketleniyor (PyInstaller, 5-10 dakika)"
Push-Location (Join-Path $Kok "engine")
try {
    Calistir "Motor bağımlılıkları" { & uv sync --locked --group packaging --python 3.13 }
    Calistir "Motor paketleme" { & uv run --group packaging pyinstaller packaging/ati-engine.spec --noconfirm --distpath build/dist --workpath build/work }
    Calistir "Paketlenmiş motor denetimi" { & .\build\dist\ati-engine\ati-engine.exe version }
} finally { Pop-Location }
$kaynak = Join-Path $Kok "desktop\src-tauri\resources\engine"
if (Test-Path $kaynak) { Remove-Item $kaynak -Recurse -Force }
New-Item -ItemType Directory -Force $kaynak | Out-Null
Copy-Item -Recurse -Force (Join-Path $Kok "engine\build\dist\ati-engine\*") $kaynak

# ---------------------------------------------------------------------------------------------
Adim "Kurulum dosyası derleniyor (Tauri + NSIS, ilk seferde 10-20 dakika)"
Push-Location (Join-Path $Kok "desktop")
try {
    Calistir "Arayüz bağımlılıkları" { & npm.cmd ci }
    $tamam = $false
    for ($i = 1; $i -le 3 -and -not $tamam; $i++) {
        $eski = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & npx.cmd tauri build --bundles nsis
        $kod = $LASTEXITCODE
        $ErrorActionPreference = $eski
        if ($kod -eq 0) { $tamam = $true } elseif ($i -lt 3) {
            Bilgi "Deneme $i başarısız (genelde geçici indirme hatası); 20 sn sonra yeniden deneniyor."
            Start-Sleep -Seconds 20
        }
    }
    if (-not $tamam) { Hata "Kurulum dosyası 3 denemede derlenemedi. Ekranın görüntüsünü gönderin." }
} finally { Pop-Location }

# ---------------------------------------------------------------------------------------------
$kurulum = Get-ChildItem (Join-Path $Kok "desktop\src-tauri\target\release\bundle\nsis\*-setup.exe") |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $kurulum) { Hata "Kurulum dosyası bulunamadı." }
$cikti = Join-Path $Kok "cikti"
New-Item -ItemType Directory -Force $cikti | Out-Null
$hedef = Join-Path $cikti $kurulum.Name
Copy-Item $kurulum.FullName $hedef -Force
$ozet = (Get-FileHash $hedef -Algorithm SHA256).Hash.ToLower()

Write-Host ""
Write-Host "Derleme tamamlandı." -ForegroundColor Green
Write-Host "  Dosya   : $hedef"
Write-Host "  Sürüm   : $surum"
Write-Host "  Boyut   : $($kurulum.Length) bayt"
Write-Host "  SHA-256 : $ozet"
Write-Host ""
Write-Host "Bu bilgisayara kurmak için dosyaya çift tıklayın (eski sürümün üzerine kurulur; lisans ve ayarlar korunur)."
Write-Host "Müşterilere yayınlamak için dosyayı sunucuya kopyalayıp: yonet.ps1 surum-hazirla -Dosya `"<dosya yolu>`""
Start-Process explorer.exe $cikti
