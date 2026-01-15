# Gemini CLI Configuration

## API Key

**GEMINI_API_KEY:** `AIzaSyBlS5W18pCPUkIBUJdrMTIrYgv5_1_LXmQ`

## Usage

```bash
# Set environment variable and run
GEMINI_API_KEY="AIzaSyBlS5W18pCPUkIBUJdrMTIrYgv5_1_LXmQ" gemini -p "your prompt" --model gemini-2.5-pro

# With file context
GEMINI_API_KEY="AIzaSyBlS5W18pCPUkIBUJdrMTIrYgv5_1_LXmQ" gemini -p "your prompt" --model gemini-2.5-pro -a "path/to/file.ts"
```

## Available Models

- `gemini-2.5-pro` - Latest stable Pro (use for complex tasks)
- `gemini-2.0-flash-exp` - Fast model for simple tasks
- `gemini-3-pro-preview` - Preview of next gen

## Permanent Setup

To avoid setting the env var each time, add to your shell config:

**Windows (PowerShell profile):**
```powershell
$env:GEMINI_API_KEY = "AIzaSyBlS5W18pCPUkIBUJdrMTIrYgv5_1_LXmQ"
```

**Or add to Gemini settings file:**
Edit `C:\Users\joeva\.gemini\settings.json`:
```json
{
  "selectedAuthType": "api-key",
  "apiKey": "AIzaSyBlS5W18pCPUkIBUJdrMTIrYgv5_1_LXmQ"
}
```

---
Source: `C:\Projects\Shadow Ledger\.claude\gemini-config.md`
