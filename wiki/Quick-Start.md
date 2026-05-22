# Quick Start

Get a full migration done in 3 steps.

## Step 1: Connect Consoles

Launch the app and go to **Connections**. Fill in both consoles:

| Field | Description | Example |
|-------|-------------|---------|
| **Name** | Friendly name | `Production US` |
| **URL** | Console URL or short name | `usea1-021` or `https://usea1-021.sentinelone.net` |
| **API Token** | Service User API token | `eyJ…` |

Click **Save & Connect** for each.

### Pro Tip: Paste from Ticket

Copy a migration ticket to your clipboard, then click **Paste from Ticket**. It auto-fills:
- Source/destination connection fields
- Backup page filters (account, site)
- Restore page filters + mangle rename

Expected clipboard format:
```
Source console: Acme Corp
URL: https://usea1-acme.sentinelone.net
Token1: eyJ…
Target Console: Acme New
URL2: https://usea1-new.sentinelone.net
Token2: eyJ…
Source Site: Default Site
Target Account: Acme New Account
```

## Step 2: Backup Source

Navigate to **Backup Source**:

1. Select levels to backup (Accounts, Sites, Groups)
2. Optionally filter by account/site/group name
3. Choose elements to include (or leave all 26 checked)
4. Click **▶ Start Backup**
5. Pick a save location for the JSON file

The progress table shows real-time status for each node (account → site → group).

## Step 3: Restore to Destination

Navigate to **Restore to Dest**:

1. The latest backup file loads automatically
2. Set restore scope and filters
3. If needed, use **Mangle Rename** to map source names → destination names
4. Click **▶ Restore Now**
5. Click **Export Log** for a professional HTML report

### Automatic Handling

The restore process handles common issues automatically:

- **Duplicate items** → Detected and skipped
- **License bundle mismatch** → Prompts to fix SKU
- **Expired STAR rules** → Auto-extends expiration
- **Missing sites/groups** → Auto-created on destination
- **Expired/deleted sites** → Skipped automatically
