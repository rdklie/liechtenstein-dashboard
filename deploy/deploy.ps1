# Deployment nach cyon (Hosting rdkli@s033): Code -> ~/daten-li/app, venv -> ~/daten-li/venv,
# DB -> ~/daten-li/data/liechtenstein.sqlite (ausserhalb des Webroots), Webroot ~/public_html/datasites
# enthaelt nur die .htaccess (Proxy auf lokalen gunicorn).
#
# Normal:                   .\deploy\deploy.ps1
# Erster Lauf / Umschalten: .\deploy\deploy.ps1 -Htaccess -RunWorker
#   -Htaccess   schreibt deploy/server/htaccess nach ~/public_html/datasites/.htaccess (Backup .htaccess.bak)
#   -ForceHttps wie -Htaccess, aber mit HTTP->HTTPS-Weiterleitung + HSTS (erst nach Zertifikat im cyon-Panel!)
#   -RunWorker  startet den Datenabruf sofort (Dauer ca. 3 Min.), sonst erst per Cron um 06:00 UTC
#   -ImportPolice   einmaliger Import der Landespolizei-Jahresberichte (Download 17 PDFs, ca. 1 Min.)
#   -ImportFactbook  einmaliger Import des CIA-World-Factbook-Archivs (Liechtenstein) von GitHub, ca. 1 Min.
#   -RunDiscover startet den opendata.li-Discovery-Lauf sofort (ca. 1 Min.), sonst sonntags 05:30 UTC
param(
    [switch]$Htaccess,
    [switch]$ForceHttps,
    [switch]$RunWorker,
    [switch]$RunDiscover,
    [switch]$ImportFactbook,
    [switch]$ImportPolice
)
$ErrorActionPreference = 'Continue'  # stderr-Warnungen von ssh/pip sind kein Fehler; Exitcodes werden explizit geprueft
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)

$Root    = Split-Path $PSScriptRoot -Parent
$Key     = Join-Path $env:USERPROFILE '.ssh\bnutt_cyon_ed25519'
$Remote  = 'rdkli@s033.cyon.net'
$SshOpts = @('-i', $Key, '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes')
$Pkg     = Join-Path $env:TEMP 'daten-li-deploy.tgz'

Write-Host '1/5 Paket schnueren ...'
Remove-Item $Pkg -ErrorAction SilentlyContinue
Push-Location $Root
tar -czf $Pkg app.py ui.py tab_wohnen.py tab_opendata.py tab_factbook.py tab_imf.py tab_migration.py migration.py tab_police.py police.py opendata.py imf.py factbook_import.py discover.py data_fetcher.py db.py worker.py requirements.txt assets deploy/server
if ($LASTEXITCODE -ne 0) { throw 'tar fehlgeschlagen' }
Pop-Location

Write-Host '2/5 Hochladen ...'
ssh @SshOpts $Remote 'mkdir -p ~/daten-li/_staging && rm -rf ~/daten-li/_staging/*'
scp @SshOpts $Pkg "${Remote}:daten-li/_staging/pkg.tgz"
if ($LASTEXITCODE -ne 0) { throw 'scp fehlgeschlagen' }

Write-Host '3/5 Auf dem Server einspielen ...'
$remoteScript = @'
set -e
B=~/daten-li
cd $B/_staging && tar -xzf pkg.tgz
sed -i 's/\r$//' deploy/server/*   # Sicherheitsnetz gegen CRLF aus Windows
mkdir -p $B/app $B/bin $B/data $B/cache $B/logs
chmod 700 $B $B/data
rsync -a --delete --exclude=__pycache__ app.py ui.py tab_wohnen.py tab_opendata.py tab_factbook.py tab_imf.py tab_migration.py migration.py tab_police.py police.py opendata.py imf.py factbook_import.py discover.py data_fetcher.py db.py worker.py requirements.txt assets $B/app/
install -m 755 deploy/server/keepalive.sh deploy/server/stop.sh deploy/server/run-worker.sh deploy/server/run-discover.sh deploy/server/run-factbook-import.sh deploy/server/run-police-import.sh $B/bin/

# venv + Abhaengigkeiten (nur bei geaenderter requirements.txt)
[ -x $B/venv/bin/python ] || /opt/alt/python311/bin/python3.11 -m venv $B/venv
if ! cmp -s $B/app/requirements.txt $B/requirements.installed; then
  $B/venv/bin/pip install -q --disable-pip-version-check -r $B/app/requirements.txt
  cp $B/app/requirements.txt $B/requirements.installed
fi

# Crontab: eigenen Block ersetzen, alles andere unveraendert lassen
( crontab -l 2>/dev/null | sed '/^# >>> daten-li/,/^# <<< daten-li/d'; cat deploy/server/crontab.txt ) | crontab -

if [ "$DO_HTACCESS" = 1 ]; then
  H=~/public_html/datasites/.htaccess
  [ -f $H.bak ] || cp $H $H.bak
  if [ "$DO_HTTPS" = 1 ]; then sed 's/^#FORCE_HTTPS#//' deploy/server/htaccess > $H; else cp deploy/server/htaccess $H; fi
  chmod 644 $H
  echo ".htaccess installiert (Backup: .htaccess.bak)"
fi

# gunicorn neu starten
$B/bin/stop.sh
$B/bin/keepalive.sh
rm -rf $B/_staging
echo "Deploy ok"
'@
$remoteScript = $remoteScript -replace "`r", ''
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($remoteScript))
$h = if ($Htaccess -or $ForceHttps) { 1 } else { 0 }
$https = if ($ForceHttps) { 1 } else { 0 }
ssh @SshOpts $Remote "echo $b64 | base64 -d | DO_HTACCESS=$h DO_HTTPS=$https bash"
if ($LASTEXITCODE -ne 0) { throw 'Remote-Schritt fehlgeschlagen' }

if ($RunWorker) {
    Write-Host '4/5 Datenabruf (worker.py) ...'
    ssh @SshOpts $Remote '~/daten-li/bin/run-worker.sh; tail -n 15 ~/daten-li/logs/worker.log'
} else {
    Write-Host '4/5 Datenabruf uebersprungen (-RunWorker)'
}

if ($ImportPolice) {
    Write-Host '4d/5 Polizei-Jahresberichte (police.py) ...'
    ssh @SshOpts $Remote '~/daten-li/bin/run-police-import.sh | tail -n 22'
}

if ($ImportFactbook) {
    Write-Host '4c/5 Factbook-Archiv (factbook_import.py) ...'
    ssh @SshOpts $Remote '~/daten-li/bin/run-factbook-import.sh | tail -n 8'
}

if ($RunDiscover) {
    Write-Host '4b/5 Discovery (discover.py) ...'
    ssh @SshOpts $Remote '~/daten-li/bin/run-discover.sh; tail -n 25 ~/daten-li/logs/discover.log'
}

Write-Host '5/5 Smoke-Test ...'
# gunicorn braucht mit --preload einige Sekunden zum Hochfahren
$local = ssh @SshOpts $Remote "for i in 1 2 3 4 5 6 7 8 9 10; do c=`$(curl -s -o /dev/null -w %{http_code} http://127.0.0.1:38517/); [ `"`$c`" = 200 ] && break; sleep 2; done; echo `$c"
Write-Host "  gunicorn lokal -> $local"
$code = curl.exe -s -o NUL -w '%{http_code}' https://daten.li/
Write-Host "  https://daten.li/ -> $code"
