<#
.SYNOPSIS
  Sunucudaki AI Trading Intelligence servislerini yönetir (yönetici PowerShell'inden).

.EXAMPLE
  C:\ATI\betikler\yonet.ps1 durum
  C:\ATI\betikler\yonet.ps1 yeniden
  C:\ATI\betikler\yonet.ps1 davet -Eposta siz@ornek.com -Ad "Ad Soyad"
  C:\ATI\betikler\yonet.ps1 loglar -Servis api
  C:\ATI\betikler\yonet.ps1 yedek
  C:\ATI\betikler\yonet.ps1 eposta-ayarla
  C:\ATI\betikler\yonet.ps1 eposta-dene -Eposta siz@ornek.com
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("durum", "baslat", "durdur", "yeniden", "davet", "loglar", "yedek", "eposta-ayarla", "eposta-dene")]
    [string]$Komut,
    [string]$Eposta,
    [string]$Ad,
    [string]$Rol = "super_admin",
    [string]$Servis = "api",
    [switch]$Sessiz
)

$ErrorActionPreference = "Stop"
$Kok = "C:\ATI"
$Surekli = @("API", "Aktarma", "Web", "Caddy", "Eposta")

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

function Env-Guncelle([string]$Ad, [hashtable]$Yeni) {
    # Dosyanın izinleri korunur (yalnızca içeriği yazılır); diğer satırlara dokunulmaz.
    $yol = Join-Path "$Kok\ayarlar" $Ad
    $satirlar = New-Object System.Collections.Generic.List[string]
    $kalan = @{} + $Yeni
    foreach ($satir in [System.IO.File]::ReadAllLines($yol)) {
        $i = $satir.IndexOf("=")
        $anahtar = if ($i -gt 0 -and -not $satir.TrimStart().StartsWith("#")) { $satir.Substring(0, $i) } else { $null }
        if ($anahtar -and $kalan.ContainsKey($anahtar)) {
            $satirlar.Add("$anahtar=$($kalan[$anahtar])")
            $kalan.Remove($anahtar)
        } else {
            $satirlar.Add($satir)
        }
    }
    foreach ($k in $kalan.Keys) { $satirlar.Add("$k=$($kalan[$k])") }
    [System.IO.File]::WriteAllText($yol, (($satirlar -join "`r`n") + "`r`n"), (New-Object System.Text.UTF8Encoding $false))
}

function Sor([string]$Soru, [string]$Varsayilan) {
    $cevap = Read-Host "$Soru [$Varsayilan]"
    if ([string]::IsNullOrWhiteSpace($cevap)) { return $Varsayilan }
    return $cevap.Trim()
}

function Eposta-Yeniden {
    if (Gorev-Var "Eposta") {
        Stop-ScheduledTask -TaskPath "\ATI\" -TaskName "Eposta"
        Get-CimInstance Win32_Process | Where-Object {
            ($_.CommandLine -like "*calistir.ps1*-Servis eposta*") -or ($_.Name -eq "ati-cloud-mail.exe")
        } | ForEach-Object { Invoke-CimMethod -InputObject $_ -MethodName Terminate | Out-Null }
        Start-ScheduledTask -TaskPath "\ATI\" -TaskName "Eposta"
    }
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
    "eposta-ayarla" {
        Write-Host "E-posta gönderim ayarları (Resend için varsayılanları Enter ile kabul edin)."
        $sunucu = Sor "SMTP sunucusu" "smtp.resend.com"
        $port = Sor "Port (465 = SSL, 587 = STARTTLS)" "465"
        $kullanici = Sor "Kullanıcı adı" "resend"
        $gizli = Read-Host "API anahtarı / SMTP parolası (yazarken görünmez)" -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($gizli)
        try { $parola = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
        if ([string]::IsNullOrWhiteSpace($parola)) { throw "API anahtarı boş olamaz" }
        $gonderen = Sor "Gönderen" "AI Trading Intelligence <bildirim@canarslan.net.tr>"
        $guvenlik = if ($port -eq "465" -or $port -eq "2465") { "ssl" } else { "starttls" }
        Env-Guncelle "bulut.env" @{
            ATI_SMTP_HOST = $sunucu; ATI_SMTP_PORT = $port; ATI_SMTP_SECURITY = $guvenlik
            ATI_SMTP_USERNAME = $kullanici; ATI_SMTP_PASSWORD = $parola.Trim(); ATI_MAIL_FROM = $gonderen
        }
        $parola = $null
        Eposta-Yeniden
        Write-Host "Kaydedildi ve e-posta servisi yeniden başlatıldı. Denemek için:"
        Write-Host "  powershell -ExecutionPolicy Bypass -File C:\ATI\betikler\yonet.ps1 eposta-dene -Eposta <adresiniz>"
    }
    "eposta-dene" {
        if (-not $Eposta) { throw "Kullanım: yonet.ps1 eposta-dene -Eposta <adresiniz>" }
        Yukle-Env "bulut.env"
        & "$Kok\uygulama\cloud\.venv\Scripts\ati-cloud-mail.exe" test --to $Eposta
        if ($LASTEXITCODE -eq 0) { Write-Host "Gelen kutunuzu (ve istenmeyen klasörünü) kontrol edin." }
    }
    "yedek" {
        Start-ScheduledTask -TaskPath "\ATI\" -TaskName "Yedek"
        Write-Host "Yedek başlatıldı; birkaç saniye sonra 'durum' ile kontrol edin ($Kok\yedekler)."
    }
}
