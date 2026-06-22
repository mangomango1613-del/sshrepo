# Fixing Antivirus False Positives (Gen:Variant.Mikey / Bitdefender)

## Why this happens

Bitdefender's `Gen:Variant.Mikey.190211` is a **known false positive** for
Nuitka-compiled Python applications. Nuitka's onefile mode packs everything
into one exe that self-extracts at runtime — the same pattern used by
malware "droppers". Bitdefender's heuristic engine triggers on this pattern.

This build uses `--onefile-tempdir-spec={LOCALAPPDATA}\PyTermSSH\runtime\`
so the exe extracts to a fixed, recognisable path instead of a random
`%TEMP%\onefile_<PID>_<RANDOM>` path, which already reduces the score.

---

## Fix 1 — Submit to Bitdefender (FREE, 24-48h, PERMANENT for your exe hash)

Run: `tools\submit_fp.bat`

Or manually:
1. Go to https://www.bitdefender.com/submit/
2. Upload `dist\PyTermSSH.exe`
3. Select: **False Positive**
4. Description:
   > This is a Nuitka-compiled Python SSH client (PyTermSSH). The
   > Gen:Variant.Mikey detection is a known false positive for Nuitka
   > compiled applications. Source: https://github.com/yourusername/PyTermSSH

Bitdefender reviews within 24-48 hours and adds the hash to their whitelist.

---

## Fix 2 — Add Bitdefender exception RIGHT NOW (immediate, just your machine)

1. Open Bitdefender
2. **Protection → Antivirus → Settings → Exceptions**
3. Click **Add Exception**
4. Browse to `dist\PyTermSSH.exe` → Save

This lets the exe run immediately on your machine while the false positive
report is processed.

---

## Fix 3 — Self-signed certificate (FREE, reduces AV score)

```cmd
tools\sign_exe.bat self
```

Signs the exe with a certificate tied to your Windows account. Reduces
Bitdefender's heuristic score significantly. Still shows "Unknown Publisher"
on other machines unless they install your certificate.

---

## Fix 4 — Commercial code signing certificate (PERMANENT, all machines)

Eliminates ALL AV false positives and Windows SmartScreen warnings.

| Vendor | Price/yr | Notes |
|---|---|---|
| SSL.com | ~$80 | Cheapest, OV cert |
| Sectigo | ~$120 | Popular choice |
| DigiCert | ~$200 | High reputation |
| SignPath.io | ~$300 | EV cert, instant SmartScreen |

After buying:
```cmd
tools\sign_exe.bat pfx "your_cert.pfx" "your_password"
```

---

## Fix 5 — Also submit to Microsoft (stops Windows Defender too)

https://www.microsoft.com/en-us/wdsi/filesubmission  
Select: **Software developer → Submit file for analysis**

---

## Why the exe won't start at all

If Bitdefender **quarantines** the file (moves it to vault), the exe won't
start even if you try to run it. Fix:

1. **Restore from quarantine:**
   Bitdefender → Notifications → View quarantined files → Restore

2. **Then immediately add exception** (Fix 2 above) so it doesn't get
   quarantined again.

3. **Run:** `tools\unblock_exe.bat` to remove the Windows internet zone mark
   (right-click the exe → Properties → Unblock also works).

---

## For GitHub Actions / CI builds

Add your code signing certificate as a GitHub Secret and the workflow
(`build.yml`) will sign automatically on every build.

See the signing steps in `.github/workflows/build.yml`.
