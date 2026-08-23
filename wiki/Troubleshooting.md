# Troubleshooting

## Connection Issues

### "Connection refused — invalid or expired API token"
- Verify the API token is correct and not expired
- Generate a new token: **S1 Console → Settings → Users → Service Users**
- Make sure the token has sufficient permissions (see [[API Token Permissions]])

### "Cannot reach console"
- Check the URL is correct: `usea1-021` or full `https://usea1-021.sentinelone.net`
- Verify network connectivity to the console
- Check if a VPN is required

### Test button shows "Failed"
- The test calls `/private/my-user` — if this fails, the token or URL is wrong
- Try the full URL instead of the short name

## Backup Issues

### Backup Returns 0 Nodes
- Verify SOURCE console is connected (check sidebar indicators)
- Check account/site name filters — they are substring matches, case-insensitive
- Ensure the API token has `Accounts.view` and `Sites.view` permissions
- Try clearing filters and backing up without any scope restriction

### Backup Is Slow
- Large consoles with many sites/groups take time — each node requires multiple API calls
- The progress table shows which node is currently being read
- Use scope filters to backup only the accounts/sites you need

### Backup Cancelled — Partial Data
- When you click Stop, completed nodes are preserved
- The output file contains whatever was captured before cancellation
- Re-run the backup without cancelling for a complete file

## Restore Issues

### SKU Mismatch Dialog
- Source and destination have different license bundles (e.g. Core vs Complete)
- Click **Yes** to auto-fix SKU references in the backup data
- Click **No** to attempt restore as-is (may fail on some elements)

### "Site returns 404"
- A previous failed restore may have created a phantom site
- The app detects this and offers to map to the existing default site
- Check the destination console for duplicate/expired sites

### Duplicate Items Skipped
- Expected behavior — the restore detects existing items by name/value
- Check the restore report for details on what was skipped vs created
- Duplicates are shown as "exist" in the progress table

### Restore Fails on Firewall Rules
- Firewall rules require location tags to exist first
- The restore creates locations before rules, but permission issues can block this
- Ensure the token has full `Firewall.create` permission

### Tags Restored, But the Destination Console Shows None
- Open **Tags** (Operations → Inventory), pick DESTINATION, and click **Run Audit** — it lists what the console genuinely holds, so you know whether the tags are missing or just somewhere you didn't look
- Tags can land at the account while you're looking at the site: the audit shows the level that owns each tag, and **Show inherited tags** reveals tags coming from a parent
- If the audit finds no endpoint tags at all, click **Diagnose endpoint tags** (writes throwaway tags and deletes them) — it distinguishes a request the console rejects, from one it accepts and discards, from one it stores where this tool isn't looking
- **If the diagnosis says the console claimed a create nothing can read**, search the console's own tag list for `s1cc-probe-`. Finding them means the write works and the listing route is wrong — those probe tags must then be deleted by hand, since cleanup can only remove what it can find
- **If nothing was stored and nothing was claimed**, check that the token has `Tag Management.create` — a **separate permission** from `Tags.create` (see [[API Token Permissions]]). Note that a global-admin service user with Unified Tags granted has still shown this symptom, so a granted permission doesn't close the question; save the diagnosis report and compare what the console answered for each request format
- Endpoint tags are key/value pairs from Tag Manager; firewall, network-quarantine and device-inventory tags are different objects with different permissions, so one type restoring fine says nothing about the others

## STAR Rule Issues

### "can not create rule with higher scope None:tenant"
- The API token is scoped to an account or a site, and the import was aimed at the tenant (global) scope — a token can't create a rule above itself, so every rule is rejected
- On **STAR Rules** (Operations → Detection & Response), fill in **Account** — and **Site** if the rules belong to a site — then import again. The same boxes scope **Load STAR Rules**
- A token that can reach exactly one account is redirected there automatically and the summary says which scope the rules landed in
- Creating rules also needs `STAR.create` on the token's role (see [[API Token Permissions]])

## Purple AI Issues

### "Purple AI returned an error"
- **ENTITLEMENT**: Tenant doesn't have Purple AI license
- **PERMISSION**: Token's role can't use Purple AI
- Contact your S1 admin to enable Purple AI on the tenant

### Empty Response
- Purple AI may return a scope-refusal if the question is outside its domain
- It only answers about SDL telemetry (process/network/file events)
- For console entities (alerts, agents, sites), use the REST pages instead

## Unified Alerts Issues

### "GraphQL: UAM error"
- UAM may not be enabled on the tenant
- The token needs alert-related permissions
- Try with an Admin-scoped service user token

### Triage Fails
- Triage actions require account scope IDs — the app auto-fetches the first account
- If you have no accounts or the token lacks account read permission, triage will fail

## macOS Issues

### "App is not from an identified developer"
See [[Installation#macOS First Launch]]

### App crashes on launch
- Ensure Python 3.10+ is installed
- Reinstall dependencies: `pip install -r requirements.txt`
- Check the terminal for error messages

## Windows Issues

### DPI Scaling Issues
- CustomTkinter handles DPI scaling automatically
- If widgets look small, check Windows display scaling settings

### "python is not recognized"
- Add Python to your PATH during installation
- Or use the full path: `C:\Python312\python.exe main.py`
