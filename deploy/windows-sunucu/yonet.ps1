<#
.SYNOPSIS
  Sunucudaki AI Trading Intelligence servislerini yönetir (yönetici PowerShell'inden).

.EXAMPLE
  C:\ATI\betikler\yonet.ps1 durum
  C:\ATI\betikler\yonet.ps1 yeniden
  C:\ATI\betikler\yonet.ps1 davet -Eposta siz@ornek.com -Ad "Ad Soyad"
  C:\ATI\betikler\yonet.ps1 loglar -Servis api
  C:\ATI\betikler\yonet.ps1 yedek
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("durum", "baslat", "durdur", "yeniden", "davet", "loglar", "yedek")]
    [string]$Komut,
    [string]$Eposta,
    [string]$Ad,
    [string]$Rol = "super_admin",
    [string]$Servis = "api",
    [switch]$Sessiz
)

$ErrorActionPreference = "Stop"
$Kok = "C:\ATI"
$Surekli = @("API", "Aktarma", "Web", "Caddy")

function Gorev-Var([string]$Ad) {
    return [bool](Get-ScheduledTask -TaskPath "\ATI\" -TaskName $Ad -ErrorAction SilentlyContinue)
}

function Durdur {
    foreach ($ad in $Surekli) {
        if (Gorev-Var $ad) { Stop-ScheduledTask -TaskPath "\ATI\" -TaskName $ad }
    }
    # Görev durunca gözetim betiği kapanır; başlattığı süreçler ayrıca kapatılır.
    $surecler = Get-CimInstance Win32_Process | Where-Object {
        $_.ProcessId -ne $PID -and (
            ($_.CommandLine -and $_.CommandLine -like "*\ATI\betikler\calistir.ps1*") -or
            ($_.ExecutablePath -and $_.ExecutablePath -like "$Kok\*") -or
            ($_.Name -eq "node.exe" -and $_.CommandLine -like "*$Kok\uygulama\web*"))
    }
    foreach ($s in $surecler) { Invoke-CimMethod -InputObject $s -MethodName Terminate | Out-Null }
    if (-not $Sessiz) { Write-Host "Servisler durduruldu." }
}

function Baslat {
    foreach ($ad in $Surekli) {
        if (-not (Gorev-Var $ad)) { throw "Görev bulunamadı: \ATI\$ad (önce kur.ps1 çalıştırın)" }
        Start-ScheduledTask -TaskPath "\ATI\" -TaskName $ad
    }
    Write-Host "Servisler başlatıldı."
}

function Yanit([string]$Url) {
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
        return "$($r.StatusCode) $($r.Content.Substring(0, [math]::Min(60, $r.Content.Length)))"
    } catch {
        return "YANIT YOK ($($_.Exception.Message))"
    }
}

function Yukle-Env([string]$Ad) {
    foreach ($satir in [System.IO.File]::ReadAllLines((Join-Path "$Kok\ayarlar" $Ad))) {
        $t = $satir.Trim()
        if ($t -eq "" -or $t.StartsWith("#")) { continue }
        $i = $t.IndexOf("=")
        if ($i -gt 0) { [Environment]::SetEnvironmentVariable($t.Substring(0, $i), $t.Substring($i + 1), "Process") }
    }
}

switch ($Komut) {
    "durdur" { Durdur }
    "baslat" { Baslat }
    "yeniden" { Durdur; Start-Sleep -Seconds 2; Baslat }
    "durum" {
        Get-ScheduledTask -TaskPath "\ATI\" -ErrorAction SilentlyContinue |
            Select-Object TaskName, State | Format-Table -AutoSize
        Write-Host "API (127.0.0.1:8000/ready):        $(Yanit 'http://127.0.0.1:8000/ready')"
        Write-Host "Aktarma (127.0.0.1:8765/health):   $(Yanit 'http://127.0.0.1:8765/health')"
        Write-Host "Web (127.0.0.1:3000/robots.txt):   $(Yanit 'http://127.0.0.1:3000/robots.txt')"
        $pg = Get-Service postgresql-x64-16 -ErrorAction SilentlyContinue
        Write-Host "PostgreSQL:                        $(if ($pg) { $pg.Status } else { 'kurulu değil' })"
        $son = Get-ChildItem "$Kok\yedekler" -Filter "ati-*.dump" -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
        Write-Host "Son yedek:                         $(if ($son) { $son.Name } else { 'henüz yok' })"
    }
    "davet" {
        if (-not $Eposta -or -not $Ad) { throw "Kullanım: yonet.ps1 davet -Eposta <e-posta> -Ad `"<Ad Soyad>`"" }
        Yukle-Env "bulut.env"
        & "$Kok\uygulama\cloud\.venv\Scripts\ati-cloud-admin.exe" invite --email $Eposta --name $Ad --role $Rol
        Write-Host ""
        Write-Host "Bağlantıyı 72 saat içinde açın; parola, doğrulama uygulaması ve kurtarma kodları istenir."
    }
    "loglar" {
        foreach ($dosya in "$Servis-gozetim.log", "$Servis.log", "$Servis-hata.log") {
            $yol = Join-Path "$Kok\loglar" $dosya
            if (Test-Path $yol) { Write-Host "--- $dosya"; Get-Content $yol -Tail 30 }
        }
    }
    "yedek" {
        Start-ScheduledTask -TaskPath "\ATI\" -TaskName "Yedek"
        Write-Host "Yedek başlatıldı; birkaç saniye sonra 'durum' ile kontrol edin ($Kok\yedekler)."
    }
}
