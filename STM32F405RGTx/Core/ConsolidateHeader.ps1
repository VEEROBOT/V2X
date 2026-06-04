# --- CONFIGURATION ---
# 1. Set the file extension(s) you want to include (e.g., "*.py", "*.js").
# Use "*" to match all files, or multiple extensions like: "*.py", "*.js"
$Extensions = "*.h"

# 2. Set the name for the final, consolidated file
$OutputFileName = "CONSOLIDATED_HEADER.txt"
# ---------------------

# Remove the output file if it already exists to start fresh
Remove-Item -Path $OutputFileName -ErrorAction SilentlyContinue

# Find all files recursively that match the extensions
$FilesToProcess = Get-ChildItem -Path . -Recurse -Include $Extensions | Where-Object { -not $_.PSIsContainer }

Write-Host "Found $($FilesToProcess.Count) files matching the extensions: $($Extensions -join ', ')"
Write-Host "Consolidating files into: $OutputFileName"
Write-Host "---"

# Loop through each file and append its content with a header
foreach ($File in $FilesToProcess) {
    # 1. Create a clear header showing the file path
    $Header = "`n`n" + ("#" * 70) + "`n"
    $Header += "# --- FILE: $($File.FullName) ---`n"
    $Header += ("#" * 70) + "`n"
    
    # 2. Add the header to the consolidated file
    Add-Content -Path $OutputFileName -Value $Header

    # 3. Add the content of the file
    Get-Content -Path $File.FullName -Raw | Add-Content -Path $OutputFileName
    
    Write-Host "  -> Added $($File.Name)"
}

Write-Host "---"
Write-Host "Consolidation Complete! File saved as: $OutputFileName"