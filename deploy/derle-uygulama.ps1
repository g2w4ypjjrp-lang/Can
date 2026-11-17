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
  Gerekli boş alan: ilk çalıştırmada 15 GB, araçlar kuruluysa 8 GB. Adımlar GitHub'daki derleme işiyle (desktop.yml) aynıdır.

  Aynı klasörde tekrar çalıştırıldığında paketlenmiş motor yeniden kullanılır (zaman kazanılır);
  her şeyi baştan derlemek için: -Temiz
#>
param([switch]$Temiz)
$ErrorActionPreference = "Stop"
$Kok = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Cikti = Join-Path $Kok "cikti"
# Ekranda görünen her şey bu dosyaya da yazılır (pencere kapansa da hata okunabilsin).
$Gunluk = Join-Path $Kok "derleme-gunlugu.txt"
try { Start-Transcript -Path $Gunluk -Force | Out-Null } catch { }

function Adim([string]$Metin) { Write-Host ""; Write-Host "==> $Metin" -ForegroundColor Cyan }
function Bilgi([string]$Metin) { Write-Host "    $Metin" }
function Hata([string]$Metin) {
    Write-Host ""
    Write-Host "HATA: $Metin" -ForegroundColor Red
    Write-Host "Kurulum dosyası OLUŞMADI. Tüm çıktı şu dosyada: $Gunluk" -ForegroundColor Yellow
    try { Stop-Transcript | Out-Null } catch { }
    exit 1
}

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
    # Satırlar metne çevrilip ekrana yazılır; böylece günlük dosyasına da girer.
    & $Is 2>&1 | ForEach-Object { "$_" } | Out-Host
    $kod = $LASTEXITCODE
    $ErrorActionPreference = $eski
    if ($kod -ne 0) { Hata "$Aciklama başarısız (çıkış kodu $kod). Ekranın görüntüsünü gönderin." }
}

if (-not (Test-Path (Join-Path $Kok "desktop\src-tauri\tauri.conf.json"))) {
    Hata "Betik depo klasörünün içinden çalıştırılmalı (deploy\derle-uygulama.ps1). Bulunan kök: $Kok"
}
$surum = (Get-Content (Join-Path $Kok "desktop\src-tauri\tauri.conf.json") -Raw | ConvertFrom-Json).version
Write-Host "AI Trading Intelligence $surum — Windows kurulum dosyası derleniyor" -ForegroundColor Green
Write-Host "Bitince kurulum dosyası: $Cikti\AI Trading Intelligence_$($surum)_x64-setup.exe (ve masaüstüne kopyası)"
Write-Host "Pencereyi 'Derleme tamamlandı' ya da 'HATA' yazana kadar kapatmayın."

# ---------------------------------------------------------------------------------------------
Adim "Ön denetimler"
$surucu = Get-PSDrive -Name ($Kok.Substring(0, 1))
Yolu-Yenile
# İlk kurulumda araçlar (~4 GB) da indirilir; araçlar kuruluysa derleme için 8 GB yeter.
$araclarVar = (Var "cargo") -and (Test-Path (Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"))
$gerekli = if ($araclarVar) { 8GB } else { 15GB }
if ($surucu.Free -lt $gerekli) {
    Hata "Bu sürücüde en az $($gerekli / 1GB) GB boş alan gerekli (şu an $([math]::Round($surucu.Free / 1GB, 1)) GB). Geçici dosyaları ve eski derleme klasörlerini silip tekrar deneyin."
}

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
$paketliMotor = Join-Path $Kok "engine\build\dist\ati-engine\ati-engine.exe"
# Motor kaynağının özeti: yeni ZIP eski klasörün üzerine açıldıysa eski motor kullanılmaz.
function Kaynak-Ozeti {
    $dosyalar = @(Get-ChildItem (Join-Path $Kok "engine\src") -Recurse -File |
        Where-Object { $_.FullName -notmatch '\\__pycache__\\|\.egg-info\\' } | Sort-Object FullName)
    $dosyalar += Get-Item (Join-Path $Kok "engine\uv.lock")
    $metin = ($dosyalar | ForEach-Object { (Get-FileHash $_.FullName -Algorithm SHA256).Hash }) -join ""
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $bayt = $sha.ComputeHash([System.Text.Encoding]::ASCII.GetBytes($metin))
    return ([System.BitConverter]::ToString($bayt) -replace "-", "")
}
$damga = Join-Path $Kok "engine\build\dist\kaynak-ozeti.txt"
$ozetSimdi = Kaynak-Ozeti
$ozetEski = if (Test-Path $damga) { (Get-Content $damga -Raw).Trim() } else { "" }
if ((Test-Path $paketliMotor) -and -not $Temiz -and $ozetEski -eq $ozetSimdi) {
    Bilgi "Motor kaynağı değişmemiş; önceki paket kullanılıyor (baştan derlemek için -Temiz)."
} else {
    if ((Test-Path $paketliMotor) -and $ozetEski -ne $ozetSimdi) { Bilgi "Motor kaynağı değişmiş; yeniden paketleniyor." }
    Push-Location (Join-Path $Kok "engine")
    try {
        Calistir "Motor bağımlılıkları" { & uv sync --locked --group packaging --python 3.13 }
        Calistir "Motor paketleme" { & uv run --group packaging pyinstaller packaging/ati-engine.spec --noconfirm --distpath build/dist --workpath build/work }
    } finally { Pop-Location }
    Set-Content -Path $damga -Value $ozetSimdi -Encoding ASCII
}
Calistir "Paketlenmiş motor denetimi" { & $paketliMotor version }
$kaynak = Join-Path $Kok "desktop\src-tauri\resources\engine"
if (Test-Path $kaynak) { Remove-Item $kaynak -Recurse -Force }
New-Item -ItemType Directory -Force $kaynak | Out-Null
Copy-Item -Recurse -Force (Join-Path $Kok "engine\build\dist\ati-engine\*") $kaynak

# ---------------------------------------------------------------------------------------------
Adim "NSIS kurulum aracı (Tauri'nin beklediği sürüm)"
# Tauri NSIS'i kendi indiricisiyle GitHub'dan alır; bazı bağlantılarda "timeout: global" ile
# başarısız olur. Aynı dosyalar burada Windows'un indiricisiyle (uzun bekleme + tekrar deneme)
# önceden kurulur ve Tauri'nin denetlediği SHA-1 özetleriyle doğrulanır (tauri-bundler 2.10.4).
$NsisZipUrl = "https://github.com/tauri-apps/binary-releases/releases/download/nsis-3.13/nsis-3.13.zip"
$NsisZipSha1 = "DB14F8AF2EA346B786C6AE19343F61AAF5E09B8E"
$NsisExeSha1 = "6D45D4E8CCF18FE1FDAC9164058F356102A2ECF2"
$UtilsUrl = "https://github.com/tauri-apps/nsis-tauri-utils/releases/download/nsis_tauri_utils-v0.5.3/nsis_tauri_utils.dll"
$UtilsSha1 = "75197FEE3C6A814FE035788D1C34EAD39349B860"
$TauriAraclar = Join-Path $env:LOCALAPPDATA "tauri"
$NsisDizin = Join-Path $TauriAraclar "NSIS"
$UtilsHedef = Join-Path $NsisDizin "Plugins\x86-unicode\additional\nsis_tauri_utils.dll"
$Indirilenler = Join-Path $env:USERPROFILE "Downloads"

function Sha1([string]$Yol) {
    if (-not (Test-Path $Yol)) { return "" }
    return (Get-FileHash $Yol -Algorithm SHA1).Hash.ToUpper()
}

function Dosya-Getir([string]$Url, [string]$Ozet, [string]$Ad) {
    # Önce İndirilenler'de tarayıcıyla indirilmiş doğru dosya var mı bakılır.
    $hazir = Join-Path $Indirilenler $Ad
    if ((Sha1 $hazir) -eq $Ozet) { Bilgi "İndirilenler'deki $Ad kullanılıyor."; return $hazir }
    $gecici = Join-Path $env:TEMP $Ad
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $eskiIlerleme = $ProgressPreference
    $ProgressPreference = "SilentlyContinue"   # 5.1'de ilerleme çubuğu indirmeyi çok yavaşlatır
    try {
        for ($i = 1; $i -le 4; $i++) {
            try {
                Bilgi "İndiriliyor: $Ad (deneme $i)"
                Invoke-WebRequest -Uri $Url -OutFile $gecici -UseBasicParsing -TimeoutSec 600
                if ((Sha1 $gecici) -eq $Ozet) { return $gecici }
                Bilgi "Dosya özeti tutmadı; yeniden indiriliyor."
            } catch {
                Bilgi "İndirilemedi: $($_.Exception.Message)"
            }
            Start-Sleep -Seconds (5 * $i)
        }
    } finally { $ProgressPreference = $eskiIlerleme }
    Write-Host ""
    Write-Host "Bu dosya indirilemedi. Tarayıcıda şu bağlantıyı açın (İndirilenler klasörüne iner)," -ForegroundColor Yellow
    Write-Host "sonra bu betiği tekrar çalıştırın:" -ForegroundColor Yellow
    Write-Host "  $Url" -ForegroundColor Yellow
    Hata "$Ad indirilemedi."
}

$nsisTamam = $false
if (Test-Path (Join-Path $NsisDizin "makensis.exe")) {
    $nsisTamam = (Sha1 (Join-Path $NsisDizin "NSIS.exe")) -eq $NsisExeSha1
}
if (-not $nsisTamam) {
    $zip = Dosya-Getir $NsisZipUrl $NsisZipSha1 "nsis-3.13.zip"
    if (Test-Path $NsisDizin) { Remove-Item $NsisDizin -Recurse -Force }
    $acilan = Join-Path $TauriAraclar "nsis-3.13"
    if (Test-Path $acilan) { Remove-Item $acilan -Recurse -Force }
    New-Item -ItemType Directory -Force $TauriAraclar | Out-Null
    Expand-Archive -Path $zip -DestinationPath $TauriAraclar -Force
    if (-not (Test-Path $acilan)) { Hata "NSIS arşivi beklenen biçimde açılmadı ($acilan yok)." }
    Rename-Item $acilan $NsisDizin
    if ((Sha1 (Join-Path $NsisDizin "NSIS.exe")) -ne $NsisExeSha1) { Hata "NSIS kurulumu doğrulanamadı." }
}
if ((Sha1 $UtilsHedef) -ne $UtilsSha1) {
    $dll = Dosya-Getir $UtilsUrl $UtilsSha1 "nsis_tauri_utils.dll"
    New-Item -ItemType Directory -Force (Split-Path $UtilsHedef) | Out-Null
    Copy-Item $dll $UtilsHedef -Force
}
Bilgi "NSIS hazır: $NsisDizin"

# ---------------------------------------------------------------------------------------------
Adim "Kurulum dosyası derleniyor (Tauri + NSIS, ilk seferde 10-20 dakika)"
Push-Location (Join-Path $Kok "desktop")
try {
    Calistir "Arayüz bağımlılıkları" { & npm.cmd ci }
    $tamam = $false
    for ($i = 1; $i -le 3 -and -not $tamam; $i++) {
        $eski = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & npx.cmd tauri build --bundles nsis 2>&1 | ForEach-Object { "$_" } | Out-Host
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
$kurulum = Get-ChildItem (Join-Path $Kok "desktop\src-tauri\target\release\bundle\nsis\*-setup.exe") -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $kurulum) { Hata "Kurulum dosyası bulunamadı." }
if ($kurulum.Name -notlike "*_$($surum)_*") {
    Hata "Derlenen dosya ($($kurulum.Name)) beklenen sürüm ($surum) değil."
}
New-Item -ItemType Directory -Force $Cikti | Out-Null
$hedef = Join-Path $Cikti $kurulum.Name
Copy-Item $kurulum.FullName $hedef -Force
$ozet = (Get-FileHash $hedef -Algorithm SHA256).Hash.ToLower()
$masaustu = [Environment]::GetFolderPath("Desktop")
if ($masaustu -and (Test-Path $masaustu)) { Copy-Item $hedef (Join-Path $masaustu $kurulum.Name) -Force }

Write-Host ""
Write-Host "Derleme tamamlandı." -ForegroundColor Green
Write-Host "  Dosya   : $hedef"
Write-Host "  Kopya   : masaüstünüzde aynı adla"
Write-Host "  Sürüm   : $surum"
Write-Host "  Boyut   : $($kurulum.Length) bayt"
Write-Host "  SHA-256 : $ozet"
Write-Host ""
Write-Host "Bu bilgisayara kurmak için dosyaya çift tıklayın (eski sürümün üzerine kurulur; lisans ve ayarlar korunur)."
Write-Host "Müşterilere yayınlamak için dosyayı sunucuya kopyalayıp: yonet.ps1 surum-hazirla -Dosya `"<dosya yolu>`""
try { Stop-Transcript | Out-Null } catch { }
Start-Process explorer.exe $Cikti
