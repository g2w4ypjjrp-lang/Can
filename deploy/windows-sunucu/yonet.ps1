<#
.SYNOPSIS
  Sunucudaki AI Trading Intelligence servislerini yönetir (yönetici PowerShell'inden).

.EXAMPLE
  C:\ATI\betikler\yonet.ps1 durum
  C:\ATI\betikler\yonet.ps1 yeniden
  C:\ATI\betikler\yonet.ps1 davet -Eposta siz@ornek.com -Ad "Ad Soyad"
  C:\ATI\betikler\yonet.ps1 yonetici-sifirla -Eposta siz@ornek.com
  C:\ATI\betikler\yonet.ps1 loglar -Servis api
  C:\ATI\betikler\yonet.ps1 yedek
  C:\ATI\betikler\yonet.ps1 eposta-ayarla
  C:\ATI\betikler\yonet.ps1 eposta-dene -Eposta siz@ornek.com
  C:\ATI\betikler\yonet.ps1 guncelleme-anahtari
  C:\ATI\betikler\yonet.ps1 surum-hazirla -Dosya "C:\Users\...\AI Trading Intelligence_1.0.0_x64-setup.exe"
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("durum", "baslat", "durdur", "yeniden", "davet", "yonetici-sifirla", "loglar", "yedek", "eposta-ayarla", "eposta-dene", "guncelleme-anahtari", "surum-hazirla", "yedek-bulut-ayarla", "yedek-bulut-dene")]
    [string]$Komut,
    [string]$Eposta,
    [string]$Dosya,
    [string]$Ad,
    [string]$Rol = "super_admin",
    [string]$Servis = "api",
    [switch]$Sessiz
)

$ErrorActionPreference = "Stop"
$Kok = "C:\ATI"
$Surekli = @("API", "Aktarma", "Web", "Caddy", "Eposta")
$NpmCmd = "C:\Program Files\nodejs\npm.cmd"
$GuncellemeAnahtari = "$Kok\ayarlar\guncelleme.key"

# Tauri imzalayıcısı (sürüm sabit). CI=true: parolasız anahtar, soru sorulmaz. Aracın bilgi
# satırları hata kanalına yazılır; Windows PowerShell bunları kırmızı "hata" gibi göstermesin diye
# düz metne çevrilir (gerçek hata çıkış koduyla anlaşılır).
function Tauri-Imzalayici([string[]]$Argumanlar) {
    $env:CI = "true"
    $eski = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $NpmCmd exec --yes --package=@tauri-apps/cli@2.12.4 -- tauri signer @Argumanlar 2>&1 | ForEach-Object { "$_" } | Out-Host
    $kod = $LASTEXITCODE
    $ErrorActionPreference = $eski
    if ($kod -ne 0) { throw "İmzalayıcı hata verdi (çıkış kodu $kod)" }
}

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
    # Bir süreç kapanınca alt süreçleri de kapanır; listedeki süreç o an çoktan bitmiş olabilir
    # ("Not found"). Bu durum hata değildir, yok sayılır.
    $kimlikler = @($surecler | ForEach-Object { $_.ProcessId })
    foreach ($no in $kimlikler) {
        Stop-Process -Id $no -Force -ErrorAction SilentlyContinue
    }
    # Dosyalar serbest kalsın diye süreçlerin gerçekten kapanması beklenir (en çok ~15 sn).
    for ($i = 0; $i -lt 30; $i++) {
        $yasayan = @($kimlikler | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
        if ($yasayan.Count -eq 0) { break }
        Start-Sleep -Milliseconds 500
    }
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
        } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
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
    "yonetici-sifirla" {
        # Parolasını ya da doğrulama telefonunu kaybeden yönetici (son süper yönetici dahil):
        # yeni davet bağlantısıyla yeni parola ve doğrulama uygulaması kurulur.
        if (-not $Eposta) { throw "Kullanım: yonet.ps1 yonetici-sifirla -Eposta <yönetici e-postası>" }
        Yukle-Env "bulut.env"
        & "$Kok\uygulama\cloud\.venv\Scripts\ati-cloud-admin.exe" reset --email $Eposta
        if ($LASTEXITCODE -ne 0) { throw "Sıfırlanamadı (e-postayı kontrol edin)." }
        Write-Host ""
        Write-Host "Bağlantıyı 72 saat içinde açın: yeni parola ve doğrulama uygulaması (QR) kurulur, yeni kurtarma kodları verilir."
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
        $port = Sor "Port (465 = SSL, 587 = STARTTLS; sağlayıcınız engelliyorsa 2465 = SSL, 2587 = STARTTLS)" "465"
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
        $exe = "$Kok\uygulama\cloud\.venv\Scripts\ati-cloud-mail.exe"
        # Sunucu eski sürümse e-posta servisi ve bu komut yoktur.
        if (-not (Test-Path $exe) -or -not (Gorev-Var "Eposta")) {
            Write-Host "[HATA] E-posta servisi kurulu değil: sunucudaki kurulum eski." -ForegroundColor Red
            Write-Host "       Son ZIP'i indirip kur.ps1'i yeniden çalıştırın (ayarlar ve veriler korunur)."
            exit 1
        }
        $gorev = Get-ScheduledTask -TaskPath "\ATI\" -TaskName "Eposta"
        if ($gorev.State -eq "Running") {
            Write-Host "[ OK ] E-posta servisi çalışıyor (zamanlanmış görev \ATI\Eposta)"
        } else {
            Write-Host "[HATA] E-posta servisi çalışmıyor (durum: $($gorev.State)). Başlatmak için: yonet.ps1 yeniden" -ForegroundColor Red
        }
        Yukle-Env "bulut.env"
        & $exe test --to $Eposta
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Son kayıtlar için: yonet.ps1 loglar -Servis eposta"
        }
    }
    "guncelleme-anahtari" {
        # Otomatik güncelleme imza anahtarı (bir kez). Gizli kısım bu sunucuda kalır; açık kısım
        # uygulamaya gömülür. Kaybolursa kurulu uygulamalar yeni sürümlere kendiliğinden geçemez.
        if (-not (Test-Path $GuncellemeAnahtari)) {
            Write-Host "Güncelleme imza anahtarı oluşturuluyor (yalnızca bir kez)..."
            Tauri-Imzalayici @("generate", "--ci", "-w", $GuncellemeAnahtari)
        }
        if (-not (Test-Path "$GuncellemeAnahtari.pub")) { throw "Açık anahtar bulunamadı: $GuncellemeAnahtari.pub" }
        Write-Host ""
        Write-Host "AÇIK ANAHTAR (gizli değildir; uygulamaya gömülmesi için Claude'a gönderin):" -ForegroundColor Green
        Write-Host (Get-Content "$GuncellemeAnahtari.pub" -Raw).Trim()
        Write-Host ""
        Write-Host "GİZLİ ANAHTAR: $GuncellemeAnahtari - kimseyle paylaşmayın; bulut.env ile birlikte yedekleyin."
    }
    "surum-hazirla" {
        # Kurulum dosyasını indirme klasörüne değişmeyen adla koyar, güncelleme imzasını atar ve
        # yönetim paneli -> Sürümler formuna girilecek değerleri yazar.
        if (-not $Dosya -or -not (Test-Path $Dosya)) { throw "Kullanım: yonet.ps1 surum-hazirla -Dosya <...-setup.exe yolu>" }
        if (-not (Test-Path $GuncellemeAnahtari)) { throw "Önce: yonet.ps1 guncelleme-anahtari" }
        $ad = Split-Path $Dosya -Leaf
        if ($ad -notmatch '_(\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?)_x64-setup\.exe$') { throw "Dosya adı tanınmadı (beklenen: ..._1.2.3_x64-setup.exe): $ad" }
        $surum = $Matches[1]
        $hedefAd = "AI-Trading-Intelligence_$($surum)_x64-setup.exe"
        $hedef = Join-Path "$Kok\indir" $hedefAd
        $ozet = (Get-FileHash $Dosya -Algorithm SHA256).Hash.ToLower()
        if (Test-Path $hedef) {
            if ((Get-FileHash $hedef -Algorithm SHA256).Hash.ToLower() -ne $ozet) {
                throw "$hedefAd zaten var ve farklı: yayınlanan dosya değiştirilemez, sürüm numarasını artırın."
            }
        } else {
            Copy-Item $Dosya $hedef
        }
        # Anahtar parolasız oluşturuldu (generate --ci); boş parola verilmezse araç gizli parola sorup bekler.
        Tauri-Imzalayici @("sign", "-f", $GuncellemeAnahtari, "--password=", $hedef)
        $imza = (Get-Content "$hedef.sig" -Raw).Trim()
        Write-Host ""
        Write-Host "Yönetim paneli -> Sürümler -> Yeni sürüm formuna girin:" -ForegroundColor Green
        Write-Host "  Sürüm numarası : $surum"
        Write-Host "  İndirme adresi : https://indir.canarslan.net.tr/$hedefAd"
        Write-Host "  SHA-256        : $ozet"
        Write-Host "  Boyut (bayt)   : $((Get-Item $hedef).Length)"
        Write-Host "  Güncelleme imzası (tek satır, tamamını kopyalayın):"
        Write-Host $imza
        Set-Clipboard -Value $imza -ErrorAction SilentlyContinue
        Write-Host "(İmza panoya da kopyalandı.)"
    }
    "yedek-bulut-ayarla" {
        Write-Host "Sunucu dışı yedek (Cloudflare R2 ya da başka S3 uyumlu depo)."
        Write-Host "Cloudflare -> R2 -> Create bucket (ör. ati-yedek); R2 -> Manage API tokens -> Create API token"
        Write-Host "(izin: Object Read & Write, yalnızca bu bucket). Hesap kimliğiniz R2 sayfasının sağında yazar."
        $hesap = Sor "Cloudflare hesap kimliği (Account ID)" ""
        if (-not $hesap) { throw "Hesap kimliği gerekli" }
        $bucket = Sor "Bucket adı" "ati-yedek"
        $erisim = Sor "Access Key ID" ""
        $gizli = Read-Host "Secret Access Key (yazarken görünmez)" -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($gizli)
        try { $parola = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
        if ([string]::IsNullOrWhiteSpace($erisim) -or [string]::IsNullOrWhiteSpace($parola)) { throw "Anahtarlar boş olamaz" }
        Yukle-Env "bulut.env"
        $yeni = @{
            ATI_OFFSITE_ENDPOINT = "https://$hesap.r2.cloudflarestorage.com"; ATI_OFFSITE_BUCKET = $bucket
            ATI_OFFSITE_ACCESS_KEY = $erisim.Trim(); ATI_OFFSITE_SECRET_KEY = $parola.Trim()
        }
        if (-not $env:ATI_OFFSITE_ENCRYPTION_KEY) {
            $yeni.ATI_OFFSITE_ENCRYPTION_KEY = (& "$Kok\uygulama\cloud\.venv\Scripts\ati-cloud-offsite.exe" new-key).Trim()
            Write-Host "Yeni şifreleme anahtarı üretildi (bulut.env içinde)."
        }
        Env-Guncelle "bulut.env" $yeni
        $parola = $null
        Write-Host "Kaydedildi. Her gece yedek şifrelenip bu depoya da yüklenir." -ForegroundColor Green
        Write-Host "ÖNEMLİ: bulut.env dosyasının bir kopyasını sunucu dışında saklayın; şifreleme anahtarı olmadan yedek açılamaz."
        Write-Host "Cloudflare R2 -> bucket -> Settings -> Object lifecycle rules: 30 gün sonra silme kuralı ekleyin."
        Write-Host "Hemen denemek için: yonet.ps1 yedek-bulut-dene"
    }
    "yedek-bulut-dene" {
        Yukle-Env "bulut.env"
        if (-not $env:ATI_OFFSITE_BUCKET) { throw "Önce: yonet.ps1 yedek-bulut-ayarla" }
        $son = Get-ChildItem "$Kok\yedekler" -Filter "ati-*.dump" | Sort-Object Name -Descending | Select-Object -First 1
        if (-not $son) { throw "Henüz yerel yedek yok: önce yonet.ps1 yedek" }
        & "$Kok\uygulama\cloud\.venv\Scripts\ati-cloud-offsite.exe" upload $son.FullName
        if ($LASTEXITCODE -eq 0) { Write-Host "Sunucu dışı yedek çalışıyor." -ForegroundColor Green }
    }
    "yedek" {
        Start-ScheduledTask -TaskPath "\ATI\" -TaskName "Yedek"
        Write-Host "Yedek başlatıldı; birkaç saniye sonra 'durum' ile kontrol edin ($Kok\yedekler)."
    }
}
