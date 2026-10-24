# Plan: Write `test.txt` to the Desktop

## Goal
Create a plain text file named `test.txt` on the Windows Desktop.

## Environment findings
- Platform: Windows (VS Code settings reference `c:/Users/owner/...`).
- User profile: `C:\Users\owner`
- Current working directory: `C:\Users\owner\Desktop\build-your-own-coding-agent-main`
  (confirmed: listing the parent of `.` shows Desktop contents such as `desktop.ini`,
  `01273plumbers.com - Shortcut.lnk`, plus sibling project folders).
- Therefore the Desktop is the **parent** of the current project directory:
  `C:\Users\owner\Desktop`

## Target path
```
C:\Users\owner\Desktop\test.txt
```
Relative from the project root: `..\test.txt`

## Steps
1. Confirm the resolved Desktop path is `C:\Users\owner\Desktop` (and not an
   OneDrive-redirected Desktop such as `C:\Users\owner\OneDrive\Desktop`).
   - Check with: `$env:USERPROFILE; Test-Path "$env:USERPROFILE\Desktop"; Test-Path "$env:USERPROFILE\OneDrive\Desktop"`
2. Create the file with a one-line placeholder, e.g. `hello world`.
   - PowerShell: `"hello world" | Set-Content -Path "$env:USERPROFILE\Desktop\test.txt" -Encoding utf8`
3. Verify it exists and print contents:
   - `Get-Item "$env:USERPROFILE\Desktop\test.txt"; Get-Content "$env:USERPROFILE\Desktop\test.txt"`

## Notes / risks
- **Sandbox restriction:** write tools are typically limited to the workspace root
  (`build-your-own-coding-agent-main`). Writing to `..\test.txt` may be refused.
  If so, options are:
  - ask the user to approve/allow writes outside the workspace, or
  - write the file inside the project (`test.txt`) and let the user move it, or
  - the user runs the one-line PowerShell command above themselves.
- **OneDrive redirection:** if `Desktop` is redirected, the true desktop path differs;
  Step 1 catches this.
- Content was not specified; using a placeholder — tell me if you want specific text.

## Not in scope
- No changes to project source, config, or git-tracked files.
