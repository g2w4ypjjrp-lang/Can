<#
.SYNOPSIS
  Bir servisi ayar dosyasıyla başlatır ve gözetir (zamanlanmış görevlerden çağrılır).

  Sürekli servisler (api, aktarma, web, caddy) kapanırsa artan beklemeyle (5 sn → 60 sn) yeniden
  başlatılır. Tek seferlik işler (odeme, yedek) bir kez çalışıp çıkar. Çıktılar C:\ATI\loglar altında.
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("api", "aktarma", "web", "caddy", "odeme", "yedek")]
    [string]$Servis
)

$ErrorActionPreference = "Stop"
$Kok = "C:\ATI"
$Uygulama = Join-Path $Kok "uygulama"
$Scripts = Join-Path $Uygulama "cloud\.venv\Scripts"
$Loglar = Join-Path $Kok "loglar"

$Tanimlar = @{
    api     = @{ Dosya = "$Scripts\ati-cloud-api.exe"; Arg = @("--host", "127.0.0.1", "--port", "8000")
                 Env = "bulut.env"; Dizin = "$Uygulama\cloud"; Surekli = $true }
    aktarma = @{ Dosya = "$Scripts\ati-cloud-relay.exe"; Arg = @("--host", "127.0.0.1", "--port", "8765")
                 Env = $null; Dizin = "$Uygulama\cloud"; Surekli = $true }
    web     = @{ Dosya = "C:\Program Files\nodejs\node.exe"
                 Arg = @("$Uygulama\web\node_modules\next\dist\bin\next", "start", "-H", "127.0.0.1", "-p", "3000")
                 Env = "web.env"; Dizin = "$Uygulama\web"; Surekli = $true }
    caddy   = @{ Dosya = "$Kok\araclar\caddy.exe"; Arg = @("run", "--config", "$Kok\ayarlar\Caddyfile", "--adapter", "caddyfile")
                 Env = "caddy.env"; Dizin = $Kok; Surekli = $true }
    odeme   = @{ Dosya = "$Scripts\ati-cloud-payments.exe"; Arg = @("maintain")
                 Env = "bulut.env"; Dizin = "$Uygulama\cloud"; Surekli = $false }
    yedek   = @{ Dosya = "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe"; Arg = @()
                 Env = "bulut.env"; Dizin = $Kok; Surekli = $false }
}
$T = $Tanimlar[$Servis]
$Gozetim = Join-Path $Loglar "$Servis-gozetim.log"

function Gunluk([string]$Metin) {
    $satir = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Metin"
    Add-Content -Path $Gozetim -Value $satir -Encoding UTF8
}

function Yukle-Env([string]$Ad) {
    if (-not $Ad) { return }
    $yol = Join-Path "$Kok\ayarlar" $Ad
    foreach ($satir in [System.IO.File]::ReadAllLines($yol)) {
        $t = $satir.Trim()
        if ($t -eq "" -or $t.StartsWith("#")) { continue }
        $i = $t.IndexOf("=")
        if ($i -gt 0) { [Environment]::SetEnvironmentVariable($t.Substring(0, $i), $t.Substring($i + 1), "Process") }
    }
}

function Dondur-Log([string]$Yol) {
    if ((Test-Path $Yol) -and (Get-Item $Yol).Length -gt 10MB) { Move-Item $Yol "$Yol.1" -Force }
}

Yukle-Env $T.Env
$env:PYTHONUNBUFFERED = "1"

if ($Servis -eq "yedek") {
    $klasor = Join-Path $Kok "yedekler"
    $dosya = Join-Path $klasor ("ati-" + (Get-Date -Format "yyyyMMdd-HHmm") + ".dump")
    $ErrorActionPreference = "Continue"   # 5.1: yönlendirilen stderr satırları hata sayılmasın
    & $T.Dosya "--format=custom" "--no-owner" "--file=$dosya" $env:ATI_DATABASE_URL 2>> (Join-Path $Loglar "yedek.log")
    if ($LASTEXITCODE -ne 0) { Gunluk "yedek başarısız ($LASTEXITCODE)"; exit 1 }
    Gunluk "yedek alındı: $dosya ($([math]::Round((Get-Item $dosya).Length / 1KB)) KB)"
    Get-ChildItem $klasor -Filter "ati-*.dump" | Sort-Object Name -Descending | Select-Object -Skip 14 | Remove-Item -Force
    exit 0
}

$bekleme = 5
while ($true) {
    $cikti = Join-Path $Loglar "$Servis.log"
    $hata = Join-Path $Loglar "$Servis-hata.log"
    Dondur-Log $cikti
    Dondur-Log $hata
    $baslangic = Get-Date
    Gunluk "başlatılıyor: $($T.Dosya)"
    try {
        $p = Start-Process -FilePath $T.Dosya -ArgumentList $T.Arg -WorkingDirectory $T.Dizin -NoNewWindow -PassThru `
            -RedirectStandardOutput $cikti -RedirectStandardError $hata
        $null = $p.Handle   # çıkış kodunu okuyabilmek için
        $p.WaitForExit()
        $kod = $p.ExitCode
    } catch {
        $kod = -1
        Gunluk "başlatılamadı: $($_.Exception.Message)"
    }
    if (-not $T.Surekli) {
        Gunluk "bitti (çıkış kodu $kod)"
        exit $kod
    }
    $sure = ((Get-Date) - $baslangic).TotalSeconds
    if ($sure -gt 600) { $bekleme = 5 }
    Gunluk "durdu (çıkış kodu $kod, $([math]::Round($sure)) sn çalıştı); $bekleme sn sonra yeniden başlatılacak"
    Start-Sleep -Seconds $bekleme
    $bekleme = [math]::Min($bekleme * 2, 60)
}
