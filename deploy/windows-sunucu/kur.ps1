#Requires -RunAsAdministrator
<#
.SYNOPSIS
  AI Trading Intelligence — canarslan.net.tr bulut servislerini Windows Server'a kurar veya günceller.

.DESCRIPTION
  Kurulanlar (C:\ATI altında):
    * PostgreSQL 16 (yalnızca bu makineden erişilir), Node.js 22, uv (Python), Caddy (otomatik HTTPS)
    * Web sitesi + müşteri paneli + yönetim paneli, hesap/lisans/ödeme API'si, iPhone aktarma servisi
    * Zamanlanmış görevler: servisler açılışta başlar ve çökerse yeniden başlar (YEREL HİZMET hesabı,
      yönetici yetkisi yok), ödeme bakımı 10 dakikada bir, veritabanı yedeği her gece.

  İşlem motoru bu sunucuya KURULMAZ; kendi bilgisayarınızda çalışır. Bu sunucu Binance anahtarı tutmaz.

  Aynı betik güncelleme için de çalıştırılır: ayarlar, gizli anahtarlar ve veritabanı korunur.

.PARAMETER Eposta
  Let's Encrypt sertifika bildirimleri için e-posta adresi (isteğe bağlı).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\deploy\windows-sunucu\kur.ps1 -Eposta siz@ornek.com
#>
param(
    [string]$Eposta = "",
    [string]$AlanAdi = "canarslan.net.tr"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest'i çok hızlandırır
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Kok = "C:\ATI"
$Kaynak = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Uygulama = Join-Path $Kok "uygulama"
$Araclar = Join-Path $Kok "araclar"
$Ayarlar = Join-Path $Kok "ayarlar"
$Betikler = Join-Path $Kok "betikler"
$Loglar = Join-Path $Kok "loglar"
$PgKlasor = "C:\Program Files\PostgreSQL\16"
$PgServis = "postgresql-x64-16"
$NodeExe = "C:\Program Files\nodejs\node.exe"
$NpmCmd = "C:\Program Files\nodejs\npm.cmd"

# Sabitlenmiş sürümler ve resmi SHA-256 / SHA-512 özetleri (indirilen dosya doğrulanmadan çalıştırılmaz).
$Paketler = @{
    node  = @{ Url = "https://nodejs.org/dist/v22.21.1/node-v22.21.1-x64.msi"
               Algoritma = "SHA256"; Ozet = "fd7a63fec3a54a665851e2d3d93e07cfead2ffb4521675ffdbceb1bb5ac009bb" }
    uv    = @{ Url = "https://github.com/astral-sh/uv/releases/download/0.11.32/uv-x86_64-pc-windows-msvc.zip"
               Algoritma = "SHA256"; Ozet = "acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984" }
    caddy = @{ Url = "https://github.com/caddyserver/caddy/releases/download/v2.10.2/caddy_2.10.2_windows_amd64.zip"
               Algoritma = "SHA512"; Ozet = "88347875f0cd4b5e26bb39cd1f359613f932d54158d560e03244004d1ba6e61aae0cd625ba7c913bd46df096ef973fef2249396b0bb81143414378cb4447aeb8" }
    pg    = @{ Url = "https://get.enterprisedb.com/postgresql/postgresql-16.11-1-windows-x64.exe"
               Algoritma = "SHA256"; Ozet = "d34d22f00c85ff046f2771d86f6198c8d3ddc176bb68275af490c3da3d24a55f" }
}

# Hesaplar SID ile (Türkçe Windows'ta adlar yerelleştirilmiştir).
$SidYerelHizmet = "S-1-5-19"
$SidSistem = "S-1-5-18"
$SidYoneticiler = "S-1-5-32-544"

function Adim([string]$Metin) { Write-Host ""; Write-Host "==> $Metin" -ForegroundColor Cyan }
function Bilgi([string]$Metin) { Write-Host "    $Metin" }
function Hata([string]$Metin) { Write-Host ""; Write-Host "HATA: $Metin" -ForegroundColor Red; exit 1 }

function Yaz-Utf8([string]$Yol, [string]$Metin) {
    # BOM'suz UTF-8 (.env ve Caddyfile ayrıştırıcıları BOM'u anahtarın parçası sayar).
    [System.IO.File]::WriteAllText($Yol, $Metin, (New-Object System.Text.UTF8Encoding $false))
}

function Rastgele-Base64([int]$Bayt) {
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $buf = New-Object byte[] $Bayt
    $rng.GetBytes($buf)
    return [Convert]::ToBase64String($buf)
}

function Rastgele-Hex([int]$Bayt) {
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $buf = New-Object byte[] $Bayt
    $rng.GetBytes($buf)
    return (($buf | ForEach-Object { $_.ToString("x2") }) -join "")
}

function Oku-Env([string]$Yol) {
    $degerler = [ordered]@{}
    if (Test-Path $Yol) {
        foreach ($satir in [System.IO.File]::ReadAllLines($Yol)) {
            $t = $satir.Trim()
            if ($t -eq "" -or $t.StartsWith("#")) { continue }
            $i = $t.IndexOf("=")
            if ($i -gt 0) { $degerler[$t.Substring(0, $i)] = $t.Substring($i + 1) }
        }
    }
    return $degerler
}

function Yaz-Env([string]$Yol, $Degerler, [string]$Baslik) {
    $satirlar = @("# $Baslik", "# Bu dosya gizli bilgi içerir: kimseyle paylaşmayın, güvenli bir yere yedekleyin.")
    foreach ($k in $Degerler.Keys) { $satirlar += "$k=$($Degerler[$k])" }
    Yaz-Utf8 $Yol (($satirlar -join "`r`n") + "`r`n")
}

function Indir-Dogrula([string]$Ad) {
    $p = $Paketler[$Ad]
    $hedef = Join-Path $env:TEMP ([System.IO.Path]::GetFileName($p.Url))
    if (-not (Test-Path $hedef) -or (Get-FileHash $hedef -Algorithm $p.Algoritma).Hash.ToLower() -ne $p.Ozet) {
        Bilgi "İndiriliyor: $($p.Url)"
        Invoke-WebRequest -Uri $p.Url -OutFile $hedef -UseBasicParsing
    }
    $ozet = (Get-FileHash $hedef -Algorithm $p.Algoritma).Hash.ToLower()
    if ($ozet -ne $p.Ozet) {
        Remove-Item $hedef -Force
        Hata "$Ad dosyasının özeti beklenenle aynı değil (bozuk veya değiştirilmiş indirme). Tekrar deneyin."
    }
    Bilgi "Doğrulandı ($($p.Algoritma)): $([System.IO.Path]::GetFileName($p.Url))"
    return $hedef
}

function Calistir([string]$Dosya, [string[]]$Argumanlar, [string]$Dizin = $null) {
    $eski = Get-Location
    if ($Dizin) { Set-Location $Dizin }
    try {
        & $Dosya @Argumanlar
        if ($LASTEXITCODE -ne 0) { Hata "Komut başarısız ($LASTEXITCODE): $Dosya $($Argumanlar -join ' ')" }
    } finally {
        Set-Location $eski
    }
}

function Izin([string]$Yol, [string]$Hak) {
    # Örn. Izin C:\ATI "*S-1-5-19:(OI)(CI)RX"
    # (OI)(CI) kalıtımla alt klasör ve dosyalara da uygulanır.
    & icacls.exe $Yol /grant $Hak /C /Q | Out-Null
}

# ---------------------------------------------------------------------------------------------
Adim "Ön denetimler"
$os = Get-CimInstance Win32_OperatingSystem
Bilgi "$($os.Caption) — bellek $([math]::Round($os.TotalVisibleMemorySize / 1MB, 1)) GB"
if ($os.TotalVisibleMemorySize -lt 1900000) {
    Write-Host "    UYARI: 2 GB'tan az bellek. Site derlemesi yavaşlayabilir veya başarısız olabilir." -ForegroundColor Yellow
}
if (-not (Test-Path (Join-Path $Kaynak "cloud\pyproject.toml")) -or -not (Test-Path (Join-Path $Kaynak "web\package.json"))) {
    Hata "Betik depo klasörünün içinden çalıştırılmalı (deploy\windows-sunucu\kur.ps1). Bulunan kök: $Kaynak"
}
$surucu = Get-PSDrive -Name C
if ($surucu.Free -lt 6GB) { Hata "C: sürücüsünde en az 6 GB boş alan gerekli (şu an $([math]::Round($surucu.Free / 1GB, 1)) GB)." }
foreach ($port in 80, 443) {
    $dinleyen = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($d in $dinleyen) {
        $surec = Get-Process -Id $d.OwningProcess -ErrorAction SilentlyContinue
        if ($surec -and $surec.Name -ne "caddy") {
            Hata "Port $port başka bir program tarafından kullanılıyor: $($surec.Name) (PID $($surec.Id)). IIS kuruluysa durdurun veya kaldırın."
        }
    }
}
foreach ($k in $Kok, $Araclar, $Ayarlar, $Betikler, $Loglar, "$Kok\veri\caddy", "$Kok\indir", "$Kok\yedekler", "$Kok\python") {
    New-Item -ItemType Directory -Force -Path $k | Out-Null
}
# C:\ATI yalnızca Yöneticiler ve SYSTEM'e açık (varsayılan C:\ izinleri tüm kullanıcılara okuma verir).
# Servis hesabına aşağıda yalnızca gereken klasörlerde izin verilir.
& icacls.exe $Kok /inheritance:r /grant:r "*${SidYoneticiler}:(OI)(CI)(F)" "*${SidSistem}:(OI)(CI)(F)" /Q | Out-Null

# ---------------------------------------------------------------------------------------------
Adim "Araçlar (Node.js 22, uv, Caddy)"
if (-not (Test-Path $NodeExe) -or -not ((& $NodeExe --version) -like "v22.*")) {
    $msi = Indir-Dogrula "node"
    $p = Start-Process msiexec.exe -ArgumentList "/i", "`"$msi`"", "/qn", "/norestart" -Wait -PassThru
    if ($p.ExitCode -ne 0) { Hata "Node.js kurulamadı (msiexec $($p.ExitCode))" }
}
Bilgi "Node.js $(& $NodeExe --version)"

$UvExe = Join-Path $Araclar "uv.exe"
if (-not (Test-Path $UvExe) -or -not ((& $UvExe --version) -like "uv 0.11.32*")) {
    $zip = Indir-Dogrula "uv"
    Expand-Archive -Path $zip -DestinationPath $Araclar -Force
}
Bilgi (& $UvExe --version)

$CaddyExe = Join-Path $Araclar "caddy.exe"
if (-not (Test-Path $CaddyExe) -or -not ((& $CaddyExe version) -like "v2.10.2*")) {
    Get-Process caddy -ErrorAction SilentlyContinue | Stop-Process -Force
    $zip = Indir-Dogrula "caddy"
    $gecici = Join-Path $env:TEMP "caddy-acilan"
    Expand-Archive -Path $zip -DestinationPath $gecici -Force
    Copy-Item (Join-Path $gecici "caddy.exe") $CaddyExe -Force
}
Bilgi "Caddy $(& $CaddyExe version)"

# ---------------------------------------------------------------------------------------------
Adim "PostgreSQL 16 (yalnızca bu makineden erişilir)"
$PgSifreDosyasi = Join-Path $Ayarlar "postgres-yonetici.txt"
$Psql = Join-Path $PgKlasor "bin\psql.exe"
$PgGunluk = Join-Path $env:TEMP "install-postgresql.log"
# Veritabanı adresi ayar dosyasına yalnızca ilk kurulum başarıyla bittikten sonra yazılır.
$ilkKurulumBitti = (Oku-Env (Join-Path $Ayarlar "bulut.env")).Contains("ATI_DATABASE_URL")

function Pg-Sifre {
    if (-not (Test-Path $PgSifreDosyasi)) { return $null }
    return ([System.IO.File]::ReadAllText($PgSifreDosyasi).Split(":")[-1]).Trim()
}

function Pg-Baglaniyor([string]$Sifre) {
    if (-not $Sifre -or -not (Test-Path $Psql)) { return $false }
    $servis = Get-Service -Name $PgServis -ErrorAction SilentlyContinue
    if (-not $servis) { return $false }
    if ($servis.Status -ne "Running") {
        try { Start-Service $PgServis } catch { return $false }
    }
    $env:PGPASSWORD = $Sifre
    for ($i = 0; $i -lt 10; $i++) {
        $ErrorActionPreference = "Continue"   # 5.1: yönlendirilen stderr hata sayılmasın
        & $Psql -h 127.0.0.1 -U postgres -d postgres -tAc "SELECT 1" 2>&1 | Out-Null
        $kod = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
        if ($kod -eq 0) { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Pg-Kaldir {
    Bilgi "Yarım kalan PostgreSQL kurulumu kaldırılıyor (içinde veri yok)…"
    if (Get-Service -Name $PgServis -ErrorAction SilentlyContinue) {
        try { Stop-Service $PgServis -Force } catch { }
    }
    $kaldirici = Join-Path $PgKlasor "uninstall-postgresql.exe"
    if (Test-Path $kaldirici) { Start-Process $kaldirici -ArgumentList "--mode", "unattended" -Wait | Out-Null }
    if (Get-Service -Name $PgServis -ErrorAction SilentlyContinue) { & sc.exe delete $PgServis | Out-Null }
    Start-Sleep -Seconds 3
    if (Test-Path $PgKlasor) {
        try { Remove-Item $PgKlasor -Recurse -Force }
        catch { Hata "$PgKlasor silinemedi. Bilgisayarı yeniden başlatıp betiği tekrar çalıştırın." }
    }
}

function Pg-Kur {
    $sifre = Rastgele-Hex 24
    Yaz-Utf8 $PgSifreDosyasi "postgres kullanıcısının parolası (yalnızca bakım için): $sifre`r`n"
    $kurulum = Indir-Dogrula "pg"
    $imza = Get-AuthenticodeSignature $kurulum
    if ($imza.Status -ne "Valid") { Hata "PostgreSQL kurulum dosyasının dijital imzası geçersiz: $($imza.Status)" }
    Bilgi "Kuruluyor (birkaç dakika sürebilir)…"
    # --locale C: Türkçe Windows'un yerel ayar adı ("Turkish_Türkiye.1254") veritabanı kümesinin
    # oluşturulmasını bozar. Türkçe karakterler etkilenmez (veritabanı UTF-8).
    $p = Start-Process $kurulum -Wait -PassThru -ArgumentList @(
        "--mode", "unattended", "--unattendedmodeui", "none",
        "--superpassword", $sifre, "--serverport", "5432", "--servicename", $PgServis,
        "--prefix", "`"$PgKlasor`"", "--locale", "C",
        "--enable-components", "server,commandlinetools", "--disable-components", "pgAdmin,stackbuilder")
    if (-not (Pg-Baglaniyor $sifre)) {
        if (Test-Path $PgGunluk) {
            Write-Host "    Kurulum günlüğündeki hata satırları:" -ForegroundColor Yellow
            Select-String -Path $PgGunluk -Pattern "error|fail|problem|unable|invalid" |
                Select-Object -Last 15 | ForEach-Object { Write-Host "    $($_.Line)" }
        }
        Hata "PostgreSQL kurulamadı (çıkış kodu $($p.ExitCode)). Bu ekranın görüntüsünü gönderin. Günlük: $PgGunluk"
    }
    if ($p.ExitCode -ne 0) { Bilgi "Kurulum programı $($p.ExitCode) koduyla bitti ama veritabanı çalışıyor; devam ediliyor." }
}

$super = Pg-Sifre
$pgServisi = Get-Service -Name $PgServis -ErrorAction SilentlyContinue
if (-not $super -and ($pgServisi -or (Test-Path $PgKlasor))) {
    Hata "Bu makinede bu betikle kurulmamış bir PostgreSQL 16 var ($PgKlasor). postgres parolasını $PgSifreDosyasi dosyasına 'postgres kullanıcısının parolası (yalnızca bakım için): <parola>' biçiminde yazıp tekrar çalıştırın."
}
if (-not (Pg-Baglaniyor $super)) {
    if ($ilkKurulumBitti) {
        Hata "PostgreSQL çalışmıyor. Veri kaybını önlemek için otomatik onarım yapılmaz. 'Get-Service $PgServis' çıktısını ve $PgKlasor\data\log klasöründeki son günlüğü gönderin."
    }
    if ($pgServisi -or (Test-Path $PgKlasor)) { Pg-Kaldir }
    Pg-Kur
    $super = Pg-Sifre
}
$env:PGPASSWORD = $super
function Sql([string]$Komut, [string]$Veritabani = "postgres") {
    $sonuc = & $Psql -h 127.0.0.1 -U postgres -d $Veritabani -v ON_ERROR_STOP=1 -tAc $Komut
    if ($LASTEXITCODE -ne 0) { Hata "SQL başarısız: $Komut" }
    return $sonuc
}

$bulutEnvYolu = Join-Path $Ayarlar "bulut.env"
$bulut = Oku-Env $bulutEnvYolu
if (-not $bulut.Contains("ATI_DATABASE_URL")) {
    $appSifre = Rastgele-Hex 24
    if ((Sql "SELECT 1 FROM pg_roles WHERE rolname = 'ati_app'") -eq "1") {
        Sql "ALTER ROLE ati_app WITH LOGIN PASSWORD '$appSifre'" | Out-Null
    } else {
        Sql "CREATE ROLE ati_app LOGIN PASSWORD '$appSifre'" | Out-Null
    }
    $bulut["ATI_DATABASE_URL"] = "postgresql://ati_app:$appSifre@127.0.0.1:5432/ati"
}
if ((Sql "SELECT 1 FROM pg_database WHERE datname = 'ati'") -ne "1") {
    Sql "CREATE DATABASE ati OWNER ati_app ENCODING 'UTF8' TEMPLATE template0" | Out-Null
}
Sql "CREATE EXTENSION IF NOT EXISTS citext" "ati" | Out-Null
if ((Sql "SHOW listen_addresses") -ne "localhost") {
    Sql "ALTER SYSTEM SET listen_addresses = 'localhost'" | Out-Null
    Restart-Service $PgServis
    Start-Sleep -Seconds 3
}
Remove-Item Env:PGPASSWORD
Bilgi "Veritabanı hazır (yalnızca 127.0.0.1)."

# ---------------------------------------------------------------------------------------------
Adim "Ayarlar ve gizli anahtarlar"
$sabit = [ordered]@{
    ATI_ENVIRONMENT            = "production"
    ATI_PUBLIC_WEB_URL         = "https://$AlanAdi"
    ATI_WEB_ORIGINS            = "[`"https://$AlanAdi`"]"
    ATI_SESSION_COOKIE_SECURE  = "true"
    ATI_ADMIN_PUBLIC_URL       = "https://admin.$AlanAdi"
    ATI_ADMIN_ORIGINS          = "[`"https://admin.$AlanAdi`"]"
    ATI_PUBLIC_API_URL         = "https://api.$AlanAdi"
    ATI_FORWARDED_HOPS         = "1"
    ATI_RELEASE_DOWNLOAD_HOSTS = "[`"indir.$AlanAdi`",`"$AlanAdi`"]"
}
foreach ($k in $sabit.Keys) { $bulut[$k] = $sabit[$k] }
if (-not $bulut.Contains("ATI_PAYMENTS_LIVE_ALLOWED")) { $bulut["ATI_PAYMENTS_LIVE_ALLOWED"] = "false" }  # G3 onayıyla değişir
$yeniAnahtar = $false
foreach ($k in "ATI_LICENSE_PEPPER", "ATI_LICENSE_KEK", "ATI_LEASE_SIGNING_KEY", "ATI_ADMIN_SECRET_KEK") {
    if (-not $bulut.Contains($k) -or $bulut[$k] -eq "") { $bulut[$k] = Rastgele-Base64 32; $yeniAnahtar = $true }
}
Yaz-Env $bulutEnvYolu $bulut "Bulut servisleri (API, ödeme bakımı)"

$web = [ordered]@{
    NODE_ENV                = "production"
    ATI_ENVIRONMENT         = "production"
    ATI_PUBLIC_WEB_URL      = "https://$AlanAdi"
    ATI_PUBLIC_API_URL      = "https://api.$AlanAdi"
    ATI_API_URL             = "http://127.0.0.1:8000"
    ATI_PLANS_REVALIDATE_S  = "300"
    ATI_ADMIN_HOST          = "admin.$AlanAdi"
    NEXT_TELEMETRY_DISABLED = "1"
}
Yaz-Env (Join-Path $Ayarlar "web.env") $web "Web sitesi"

$caddyEnv = [ordered]@{ XDG_DATA_HOME = "$Kok\veri\caddy"; XDG_CONFIG_HOME = "$Kok\veri\caddy" }
Yaz-Env (Join-Path $Ayarlar "caddy.env") $caddyEnv "Caddy (sertifikalar burada saklanır)"

$genel = if ($Eposta) { "{`r`n`temail $Eposta`r`n}`r`n`r`n" } else { "" }
$logYolu = ($Loglar -replace "\\", "/")
$indirYolu = ("$Kok\indir" -replace "\\", "/")
$caddyfile = @"
$genel$AlanAdi {
	encode zstd gzip
	reverse_proxy 127.0.0.1:3000
	log {
		output file $logYolu/caddy-site.log {
			roll_size 20MiB
			roll_keep 5
		}
	}
}

www.$AlanAdi {
	redir https://$AlanAdi{uri} permanent
}

admin.$AlanAdi {
	reverse_proxy 127.0.0.1:3000
}

api.$AlanAdi {
	reverse_proxy 127.0.0.1:8000
}

relay.$AlanAdi {
	reverse_proxy 127.0.0.1:8765
}

indir.$AlanAdi {
	root * $indirYolu
	header Cache-Control "public, max-age=3600"
	header X-Content-Type-Options nosniff
	file_server
}
"@
Yaz-Utf8 (Join-Path $Ayarlar "Caddyfile") ($caddyfile -replace "`r?`n", "`r`n")
# Windows PowerShell 5.1'de yönlendirilen stderr satırları hata sayılır; bu adımda kapatılır.
$ErrorActionPreference = "Continue"
$dogrulama = & $CaddyExe validate --config (Join-Path $Ayarlar "Caddyfile") --adapter caddyfile 2>&1
$ErrorActionPreference = "Stop"
if ($LASTEXITCODE -ne 0) { Hata "Caddyfile geçersiz: $Ayarlar\Caddyfile`r`n$($dogrulama -join "`r`n")" }

# Gizli dosyalar: yalnızca Yöneticiler, SYSTEM ve servis hesabı (YEREL HİZMET, salt okuma).
foreach ($dosya in "bulut.env", "web.env", "caddy.env", "Caddyfile", "postgres-yonetici.txt") {
    $yol = Join-Path $Ayarlar $dosya
    if (-not (Test-Path $yol)) { continue }
    & icacls.exe $yol /inheritance:r /grant:r "*${SidYoneticiler}:(F)" "*${SidSistem}:(F)" | Out-Null
    if ($dosya -ne "postgres-yonetici.txt") { & icacls.exe $yol /grant "*${SidYerelHizmet}:(R)" | Out-Null }
}
if ($yeniAnahtar) {
    Write-Host "    ÖNEMLİ: Yeni gizli anahtarlar üretildi: $bulutEnvYolu" -ForegroundColor Yellow
    Write-Host "    Bu dosyanın bir kopyasını sunucu dışında güvenli bir yere (parola yöneticisi) kaydedin." -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------------------------
Adim "Servisler durduruluyor (güncelleme)"
& (Join-Path $PSScriptRoot "yonet.ps1") durdur -Sessiz

Adim "Uygulama dosyaları kopyalanıyor"
if (Test-Path $Uygulama) {
    $onceki = "$Uygulama-onceki"
    if (Test-Path $onceki) { Remove-Item $onceki -Recurse -Force }
    Rename-Item $Uygulama $onceki
}
foreach ($parca in "cloud", "web", "deploy") {
    & robocopy.exe (Join-Path $Kaynak $parca) (Join-Path $Uygulama $parca) /E /NFL /NDL /NJH /NJS /NP `
        /XD node_modules .venv .next test-results playwright-report __pycache__ .mypy_cache .ruff_cache .pytest_cache | Out-Null
    if ($LASTEXITCODE -ge 8) { Hata "Dosyalar kopyalanamadı: $parca" }
}
Copy-Item (Join-Path $PSScriptRoot "*.ps1") $Betikler -Force

Adim "Bulut servisleri derleniyor (Python)"
$env:UV_PYTHON_INSTALL_DIR = "$Kok\python"
$env:UV_CACHE_DIR = "$Kok\onbellek\uv"
$env:UV_LINK_MODE = "copy"
$env:UV_PYTHON_PREFERENCE = "only-managed"   # Python C:\ATI\python altına kurulur (servis hesabı erişebilsin)
Calistir $UvExe @("sync", "--locked", "--no-dev", "--no-editable", "--python", "3.13") (Join-Path $Uygulama "cloud")

Adim "Web sitesi derleniyor (Node.js; birkaç dakika sürebilir)"
$env:NEXT_TELEMETRY_DISABLED = "1"
$webDizin = Join-Path $Uygulama "web"
Calistir $NpmCmd @("ci", "--no-audit", "--no-fund") $webDizin
Calistir $NpmCmd @("run", "build") $webDizin
Calistir $NpmCmd @("prune", "--omit=dev", "--no-audit", "--no-fund") $webDizin
New-Item -ItemType Directory -Force -Path (Join-Path $webDizin ".next\cache") | Out-Null

Adim "Dosya izinleri (servis hesabı yalnızca okur; günlük, sertifika ve önbellek klasörlerine yazar)"
# Node.js yolları çözerken üst klasörü de okur (lstat C:\ATI); yalnızca bu klasörün kendisi için,
# alt klasörlere geçmeyen okuma izni. Ayarlar klasöründeki dosyaların kendi izinleri vardır.
& icacls.exe $Kok /grant "*${SidYerelHizmet}:(RX)" /C /Q | Out-Null
foreach ($k in $Uygulama, "$Kok\python", $Betikler, $Araclar, "$Kok\indir") {
    Izin $k "*${SidYerelHizmet}:(OI)(CI)RX"
}
foreach ($k in $Loglar, "$Kok\veri\caddy", "$Kok\yedekler", (Join-Path $webDizin ".next\cache")) {
    Izin $k "*${SidYerelHizmet}:(OI)(CI)M"
}

Adim "Veritabanı geçişleri"
$migrate = Join-Path $Uygulama "cloud\.venv\Scripts\ati-cloud-migrate.exe"
foreach ($k in $bulut.Keys) { [Environment]::SetEnvironmentVariable($k, $bulut[$k], "Process") }
Calistir $migrate @()

Adim "Zamanlanmış görevler"
$hesap = (New-Object System.Security.Principal.SecurityIdentifier $SidYerelHizmet).Translate([System.Security.Principal.NTAccount]).Value
$kimlik = New-ScheduledTaskPrincipal -UserId $hesap -LogonType ServiceAccount -RunLevel Limited
$surekli = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
$kisa = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1) -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
$calistir = Join-Path $Betikler "calistir.ps1"
function Gorev([string]$Ad, [string]$Servis, $Tetik, $Ayar) {
    $eylem = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$calistir`" -Servis $Servis"
    Register-ScheduledTask -TaskName $Ad -TaskPath "\ATI\" -Action $eylem -Trigger $Tetik -Principal $kimlik `
        -Settings $Ayar -Force | Out-Null
    Bilgi "\ATI\$Ad"
}
$acilis = New-ScheduledTaskTrigger -AtStartup
Gorev "API" "api" $acilis $surekli
Gorev "Aktarma" "aktarma" $acilis $surekli
Gorev "Web" "web" $acilis $surekli
Gorev "Caddy" "caddy" $acilis $surekli
Gorev "Eposta" "eposta" $acilis $surekli
Gorev "Odeme-Bakimi" "odeme" (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 3650)) $kisa
Gorev "Yedek" "yedek" (New-ScheduledTaskTrigger -Daily -At "03:30") $kisa

Adim "Güvenlik duvarı (80 ve 443 açık; veritabanı ve iç servisler kapalı)"
if (-not (Get-NetFirewallRule -DisplayName "ATI HTTP-HTTPS" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "ATI HTTP-HTTPS" -Direction Inbound -Protocol TCP -LocalPort 80, 443 -Action Allow | Out-Null
}
Bilgi "Sağlayıcınızın panelinde ayrıca bir güvenlik duvarı varsa 80 ve 443 portlarını orada da açın."

Adim "Servisler başlatılıyor"
& (Join-Path $Betikler "yonet.ps1") baslat
Start-Sleep -Seconds 20
& (Join-Path $Betikler "yonet.ps1") durum

Write-Host ""
Write-Host "Kurulum tamamlandı." -ForegroundColor Green
Write-Host "Sıradaki adımlar (deploy\windows-sunucu\README.md):"
Write-Host "  1. Cloudflare DNS kayıtları bu sunucunun IP adresine (DNS only) yönlendirilmiş olmalı."
Write-Host "  2. İlk yönetici:  powershell -ExecutionPolicy Bypass -File C:\ATI\betikler\yonet.ps1 davet -Eposta <e-posta> -Ad `"<Ad Soyad>`""
Write-Host "  3. Gizli anahtar dosyasını yedekleyin: $bulutEnvYolu"
if (-not $bulut.Contains("ATI_SMTP_HOST")) {
    Write-Host "  4. E-posta gönderimi için: powershell -ExecutionPolicy Bypass -File C:\ATI\betikler\yonet.ps1 eposta-ayarla"
}
