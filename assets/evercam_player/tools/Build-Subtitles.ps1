param(
    [Parameter(Mandatory = $false)]
    [AllowEmptyString()]
    [string]$CourseFolder
)

# Project: https://github.com/kaoshou/evercam-subtitle-player
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function ConvertTo-CanonicalLanguage {
    param([string]$Language)

    $parts = $Language -split "-"
    if ($parts.Count -eq 1) {
        return $parts[0].ToLowerInvariant()
    }

    $normalized = @($parts[0].ToLowerInvariant())
    for ($index = 1; $index -lt $parts.Count; $index += 1) {
        if ($parts[$index].Length -eq 2) {
            $normalized += $parts[$index].ToUpperInvariant()
        }
        else {
            $normalized += $parts[$index]
        }
    }
    return ($normalized -join "-")
}

function ConvertTo-Seconds {
    param([string]$Timecode)

    $match = [regex]::Match(
        $Timecode.Trim(),
        "^(?:(?<hours>\d+):)?(?<minutes>\d{2}):(?<seconds>\d{2})[,.](?<fraction>\d{1,3})"
    )
    if (-not $match.Success) {
        throw "Invalid subtitle timecode: $Timecode"
    }

    $hours = if ($match.Groups["hours"].Success) {
        [int]$match.Groups["hours"].Value
    }
    else {
        0
    }
    $minutes = [int]$match.Groups["minutes"].Value
    $seconds = [int]$match.Groups["seconds"].Value
    $fractionText = $match.Groups["fraction"].Value.PadRight(3, "0")
    $milliseconds = [int]$fractionText.Substring(0, 3)

    return ($hours * 3600) + ($minutes * 60) + $seconds + ($milliseconds / 1000)
}

function ConvertTo-PlainCueText {
    param([string]$Text)

    $clean = [regex]::Replace($Text, "(?i)<br\s*/?>", "`n")
    $clean = [regex]::Replace($clean, "\{\\[^}]+\}", "")
    $clean = [regex]::Replace($clean, "<[^>]+>", "")
    $clean = [System.Net.WebUtility]::HtmlDecode($clean)
    return $clean.Trim()
}

function Read-SubtitleCues {
    param([System.IO.FileInfo]$File)

    $content = [System.IO.File]::ReadAllText($File.FullName)
    $content = $content.TrimStart([char]0xFEFF)
    $content = $content.Replace("`r`n", "`n").Replace("`r", "`n")
    $lines = $content -split "`n"
    $cues = @()
    $lineIndex = 0

    while ($lineIndex -lt $lines.Count) {
        $line = $lines[$lineIndex].Trim()
        if ($line -notmatch "-->") {
            $lineIndex += 1
            continue
        }

        $timing = $line -split "\s+-->\s+", 2
        if ($timing.Count -ne 2) {
            $lineIndex += 1
            continue
        }

        $endToken = ($timing[1].Trim() -split "\s+", 2)[0]
        try {
            $start = ConvertTo-Seconds $timing[0]
            $end = ConvertTo-Seconds $endToken
        }
        catch {
            Write-Warning "Skipped malformed cue in $($File.Name): $line"
            $lineIndex += 1
            continue
        }

        $lineIndex += 1
        $textLines = @()
        while ($lineIndex -lt $lines.Count -and $lines[$lineIndex].Trim().Length -gt 0) {
            $textLines += $lines[$lineIndex]
            $lineIndex += 1
        }

        $text = ConvertTo-PlainCueText ($textLines -join "`n")
        if ($text.Length -gt 0 -and $end -gt $start) {
            $cues += [ordered]@{
                start = $start
                end = $end
                text = $text
            }
        }
        $lineIndex += 1
    }

    return @($cues)
}

$normalizedCourseFolder = $CourseFolder.Trim().Trim('"')
if ([string]::IsNullOrWhiteSpace($normalizedCourseFolder)) {
    $scriptFolder = Split-Path -Parent $MyInvocation.MyCommand.Path
    $normalizedCourseFolder = Split-Path -Parent $scriptFolder
}
$resolvedFolder = [System.IO.Path]::GetFullPath($normalizedCourseFolder)
if (-not [System.IO.Directory]::Exists($resolvedFolder)) {
    throw "Course folder not found: $resolvedFolder"
}

$subtitlePattern = "^media\.(?<language>[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*)\.(?<format>srt|vtt)$"
$genericSubtitlePattern = "^media\.(?<format>srt|vtt)$"
$namedSubtitleFiles = @(
    Get-ChildItem -LiteralPath $resolvedFolder -File |
        Where-Object { $_.Name -match $subtitlePattern } |
        Sort-Object Name
)

$subtitleEntries = @()
$hasTraditionalChinese = $false
foreach ($file in $namedSubtitleFiles) {
    $match = [regex]::Match($file.Name, $subtitlePattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    $language = ConvertTo-CanonicalLanguage $match.Groups["language"].Value
    if ($language.Equals("zh-TW", [System.StringComparison]::OrdinalIgnoreCase)) {
        $hasTraditionalChinese = $true
    }
    $subtitleEntries += [PSCustomObject]@{
        File = $file
        Language = $language
    }
}

$genericSubtitleFiles = @(
    Get-ChildItem -LiteralPath $resolvedFolder -File |
        Where-Object { $_.Name -match $genericSubtitlePattern } |
        Sort-Object Name
)

if (-not $hasTraditionalChinese -and $genericSubtitleFiles.Count -gt 1) {
    throw "Both media.srt and media.vtt were found. Keep only one generic subtitle file for Traditional Chinese (zh-TW)."
}
if (-not $hasTraditionalChinese -and $genericSubtitleFiles.Count -eq 1) {
    $subtitleEntries += [PSCustomObject]@{
        File = $genericSubtitleFiles[0]
        Language = "zh-TW"
    }
}

$tracks = @()
$usedLanguages = @{}
foreach ($entry in $subtitleEntries) {
    $file = $entry.File
    $language = $entry.Language
    $languageKey = $language.ToLowerInvariant()

    if ($usedLanguages.ContainsKey($languageKey)) {
        throw "Duplicate subtitle language '$language'. Keep only one SRT or VTT file for each language."
    }

    $cues = @(Read-SubtitleCues $file)
    if ($cues.Count -eq 0) {
        Write-Warning "No valid cues found in $($file.Name)."
    }

    $usedLanguages[$languageKey] = $true
    $tracks += [ordered]@{
        language = $language
        source = $file.Name
        cues = $cues
    }
}

$defaultLanguage = $null
if ($usedLanguages.ContainsKey("zh-tw")) {
    $defaultLanguage = "zh-TW"
}
elseif ($tracks.Count -gt 0) {
    $defaultLanguage = $tracks[0].language
}

$payload = [ordered]@{
    version = 1
    generatedAt = [DateTime]::UtcNow.ToString("o")
    defaultLanguage = $defaultLanguage
    tracks = @($tracks)
}

$json = $payload | ConvertTo-Json -Depth 8 -Compress
$javascript = "/* Generated by Update-Subtitles.cmd. Do not edit by hand. */`r`nwindow.EVERCAM_SUBTITLES = $json;`r`n"
$outputPath = [System.IO.Path]::Combine($resolvedFolder, "subtitles-data.js")
$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($outputPath, $javascript, $utf8WithoutBom)

Write-Host "Subtitle update completed."
Write-Host "Tracks: $($tracks.Count)"
foreach ($track in $tracks) {
    Write-Host "  $($track.language): $($track.cues.Count) cues ($($track.source))"
}
