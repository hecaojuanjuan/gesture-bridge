$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$audioDirectory = Join-Path $projectRoot 'headvoice\audio'
New-Item -ItemType Directory -Force -Path $audioDirectory | Out-Null
$voice = New-Object -ComObject SAPI.SpVoice
$token = $voice.GetVoices() | Where-Object { $_.GetDescription() -match 'Huihui.*Chinese' } | Select-Object -First 1
if (-not $token) { throw 'Microsoft Huihui Chinese voice is required' }
$voice.Voice = $token
$voice.Rate = 0
$phrases = [ordered]@{ AA = '我想喝水。'; AB = '我想休息一下。'; BA = '请过来协助我。'; BB = '我想自己来。' }
foreach ($code in $phrases.Keys) {
    $stream = New-Object -ComObject SAPI.SpFileStream
    $stream.Format.Type = 18 # SAFT16kHz16BitMono
    $stream.Open((Join-Path $audioDirectory "$code.wav"), 3)
    $voice.AudioOutputStream = $stream
    [void]$voice.Speak($phrases[$code])
    $stream.Close()
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($stream)
}
