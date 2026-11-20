# tomp3 - Windows one-line install / update. PURE ASCII ONLY.
#
#   irm https://raw.githubusercontent.com/door410/tomp3/main/install.ps1 | iex
#
# First run : installs Python + Git if missing (winget), clones to
#             %USERPROFILE%\tomp3, installs packages (incl. ffmpeg via
#             imageio-ffmpeg), makes the desktop shortcut "tomp3".
# Later runs: git pull + packages + shortcut. Same command.
# Completely separate from transcript: own folder, own port, own shortcut.
$ErrorActionPreference = 'Continue'
$Repo = 'https://github.com/door410/tomp3.git'
$Dir  = Join-Path $env:USERPROFILE 'tomp3'

function Say($m) { Write-Host "  $m" }
function RefreshPath {
  $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
              [Environment]::GetEnvironmentVariable('Path', 'User')
}
function Has($cmd) {
  try { & $cmd --version *> $null; return ($LASTEXITCODE -eq 0) } catch { return $false }
}

Write-Host ''
Say '=== tomp3 ==='

if (-not (Has 'git')) {
  Say 'Installing Git...'
  winget install -e --id Git.Git --silent --accept-package-agreements --accept-source-agreements
  RefreshPath
}
if (-not (Has 'python')) {
  Say 'Installing Python 3.12...'
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements `
    --override '/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1'
  RefreshPath
}
if (-not (Has 'git') -or -not (Has 'python')) {
  Say '[ERROR] Git or Python still not found. Close this window, open a new'
  Say 'PowerShell and run the same command again.'
  return
}

if (Test-Path (Join-Path $Dir '.git')) {
  Say 'Updating...'
  git -C $Dir pull --ff-only
  if ($LASTEXITCODE -ne 0) { Say '[ERROR] git pull failed (see message above).'; return }
} else {
  Say "Downloading to $Dir ..."
  git clone $Repo $Dir
  if ($LASTEXITCODE -ne 0) { Say '[ERROR] git clone failed.'; return }
}

Say 'Installing packages (yt-dlp, ffmpeg)... first time takes about 1 minute.'
python -m pip install --quiet --upgrade -r (Join-Path $Dir 'requirements.txt')
python -c "import yt_dlp, imageio_ffmpeg; imageio_ffmpeg.get_ffmpeg_exe()" 2>$null
if ($LASTEXITCODE -ne 0) {
  Say '[ERROR] Package install failed. Check your internet and run the same command again.'
  return
}
cscript //nologo (Join-Path $Dir 'make_shortcut.vbs')
Say 'Done. Double-click "tomp3" on the desktop.'
Say '(If tomp3 was open, close its browser tab first; the new version starts next time.)'
