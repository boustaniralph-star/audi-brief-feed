#!/usr/bin/env python3
"""Audi Capital Daily Brief - cloud mailer.
Finds today's BRIEF-PACKAGE email (sent by the cloud writer to the owner's own mailbox), rebuilds the PDF with the
same builder, runs the checks and emails the brief. Modes:  detect | send
Secrets (env): GMAIL_USER, GMAIL_APP_PASSWORD, PACKAGE_TOKEN, RECIPIENTS_TEST, RECIPIENTS_LIVE.  BRIEF_MODE: test|live."""
import datetime as dt, email, email.utils, hashlib, imaplib, json, os, re, shutil, smtplib, subprocess, sys
from email.message import EmailMessage

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
RIYADH = dt.timezone(dt.timedelta(hours=3))
NOW = dt.datetime.now(RIYADH)
STAMP = NOW.strftime("%d.%m.%Y")
ISO = NOW.strftime("%Y-%m-%d")
MODE = os.environ.get("BRIEF_MODE", "test").strip().lower()
MODE = MODE if MODE in ("test", "live") else "test"
USER = os.environ.get("GMAIL_USER", "")
PW = os.environ.get("GMAIL_APP_PASSWORD", "")
TOKEN = os.environ.get("PACKAGE_TOKEN", "")
OWNER = [a.strip() for a in os.environ.get("RECIPIENTS_TEST", USER).split(",") if a.strip()]
RECIP = [a.strip() for a in os.environ.get("RECIPIENTS_LIVE" if MODE == "live" else "RECIPIENTS_TEST", "").split(",") if a.strip()] or OWNER
MARK = os.path.join(HERE, "sent", f"{STAMP}-{MODE}.json")
DRY = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")   # build and check only: no email, no markers
ALERT = os.path.join(HERE, "sent", f"{STAMP}-alert.json")
STALE = os.path.join(HERE, "sent", f"{STAMP}-stale.json")


def out(k, v):
    p = os.environ.get("GITHUB_OUTPUT")
    if p:
        open(p, "a").write(f"{k}={v}\n")


def smtp_send(msg):
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=60) as s:
        s.starttls(); s.login(USER, PW); s.send_message(msg)


def alert(subject, body):
    if DRY:
        print("[dry run] alert not sent:", subject); return
    m = EmailMessage(); m["From"] = USER; m["To"] = ", ".join(OWNER)
    m["Subject"] = "[BRIEF ALERT] " + subject; m.set_content(body)
    try:
        smtp_send(m)
    except Exception as e:
        print("alert send failed:", type(e).__name__)


def find_package():
    M = imaplib.IMAP4_SSL("imap.gmail.com")
    M.login(USER, PW); M.select("INBOX")
    typ, d = M.search(None, "X-GM-RAW", f'"subject:BRIEF-PACKAGE newer_than:2d"')
    ids = d[0].split() if typ == "OK" else []
    best = None
    for i in reversed(ids):
        typ, data = M.fetch(i, "(RFC822)")
        msg = email.message_from_bytes(data[0][1])
        subj = str(email.header.make_header(email.header.decode_header(msg.get("Subject", ""))))
        if f"BRIEF-PACKAGE {STAMP}" not in subj:
            continue
        if email.utils.parseaddr(msg.get("From", ""))[1].lower() != USER.lower():
            continue
        body = ""
        for part in (msg.walk() if msg.is_multipart() else [msg]):
            if part.get_content_type() == "text/plain":
                body = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace"); break
        if f"TOKEN: {TOKEN}" not in body or f"DATE: {STAMP}" not in body:
            continue
        best = body; break
    M.logout()
    return best


def sections(body):
    s = {}
    for name in ("TXT", "CONTENT", "HERO"):
        m = re.search(rf"=====\s*{name}\s*=====\r?\n(.*?)\r?\n=====", body, re.S)
        if not m:
            raise ValueError(f"missing section {name}")
        s[name] = m.group(1).strip("\r\n") + "\n"
    json.loads(s["CONTENT"]); json.loads(s["HERO"])
    return s


def stale_feed_watchdog():
    """From 06:30 UTC, alert once per day if market_data.json is not from today."""
    utc = NOW.astimezone(dt.timezone.utc)
    if utc.hour * 60 + utc.minute < 6 * 60 + 30 or os.path.exists(STALE) or not (USER and PW):
        return
    try:
        gen = json.load(open(os.path.join(HERE, "market_data.json"), encoding="utf-8-sig")).get("generatedAt", "")
    except Exception:
        gen = ""
    if gen[:10] == ISO:
        return
    alert(f"stale feed {STAMP}", f"market_data.json generatedAt is '{gen or 'unreadable'}', not {ISO}, at 09:30 Riyadh. "
          "The market-data workflow has not produced today's feed. Run it from the Actions tab.")
    os.makedirs(os.path.dirname(STALE), exist_ok=True)
    json.dump({"alert": "stale feed", "generatedAt": gen}, open(STALE, "w")); out("commit", "true")
    print("stale feed alert sent")


def detect():
    if DRY:
        body = find_package() if (USER and PW and TOKEN) else None
        if body is None:
            print("[dry run] no package for today"); out("found", "false"); return 0
        os.makedirs(WORK, exist_ok=True)
        open(os.path.join(WORK, "package.txt"), "w", encoding="utf-8").write(body)
        out("found", "true"); return 0
    if os.path.exists(MARK):
        print("already sent today"); out("found", "false"); return 0
    stale_feed_watchdog()
    body = find_package() if (USER and PW and TOKEN) else None
    if body is None:
        hr = NOW.astimezone(dt.timezone.utc).hour * 60 + NOW.astimezone(dt.timezone.utc).minute
        if hr >= 7 * 60 + 40 and not os.path.exists(ALERT) and USER and PW:
            alert(f"No brief package received for {STAMP}", "The cloud writer did not deliver today's package by 10:40 Riyadh. The brief was not built or sent by the cloud chain.")
            os.makedirs(os.path.dirname(ALERT), exist_ok=True)
            json.dump({"alert": "no package"}, open(ALERT, "w")); out("commit", "true")
        print("no package yet"); out("found", "false"); return 0
    os.makedirs(WORK, exist_ok=True)
    open(os.path.join(WORK, "package.txt"), "w", encoding="utf-8").write(body)
    out("found", "true"); return 0


def send():
    body = open(os.path.join(WORK, "package.txt"), encoding="utf-8").read()
    sec = sections(body)
    for f in ("build_brief_v2.py", "extras_v2.py", "pulse_check.py", "brief_v2.css", "wordmark.png", "circles.png"):
        shutil.copy(os.path.join(HERE, "kit", f), WORK)
    for f in ("market_data.json", "series.json"):
        shutil.copy(os.path.join(HERE, f), WORK)
    base = f"Audi Capital Daily Brief - {STAMP}"
    txtp = os.path.join(WORK, base + ".txt"); pdfp = os.path.join(WORK, base + ".pdf")
    content, hero, txt = json.loads(sec["CONTENT"]), json.loads(sec["HERO"]), sec["TXT"]
    md = json.load(open(os.path.join(WORK, "market_data.json"), encoding="utf-8-sig"))
    # Bring the package up to the desktop standard (enrich.py), then build the richest variant that still passes
    # the builder's overlap check and fits 2 pages. The last variant is the package exactly as sent.
    variants = []
    try:
        sys.path.insert(0, os.path.join(HERE, "kit"))
        import enrich
        content, hero, ns = enrich.scrub(content, hero)
        print("enrich: provider names removed from", ns, "caption(s)")
        c_ytd, t_ytd, n = enrich.ytd(content, txt, md)
        print("enrich: YTD added to", n, "bullet(s)")
        has_hero = bool(hero.get("rows") or hero.get("values") or hero.get("ret") or hero.get("type"))
        if not has_hero:
            try:
                h_auto, c_auto = enrich.auto_hero(c_ytd, md)
            except Exception as e:
                h_auto = None; print("enrich: auto hero skipped:", type(e).__name__, e)
            if h_auto:
                print("enrich: auto hero", h_auto["names"], len(h_auto["rows"]), "points")
                for lab, c_lay in enrich.relayouts(c_auto):
                    variants.append((f"auto hero + YTD, {lab}", c_lay, h_auto, t_ytd))
                    variants.append((f"auto hero (short) + YTD, {lab}", c_lay, dict(h_auto, height=1.2), t_ytd))
        if n:
            variants.append(("YTD", c_ytd, hero, t_ytd))
    except Exception as e:
        print("enrich: skipped:", type(e).__name__, e)
    variants.append(("as sent (captions scrubbed)", content, hero, txt))
    for label, c, h, t in variants:
        json.dump(c, open(os.path.join(WORK, "content_v2.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        json.dump(h, open(os.path.join(WORK, "hero_data.json"), "w", encoding="utf-8"), ensure_ascii=False)
        open(txtp, "w", encoding="utf-8").write(t)
        if os.path.exists(pdfp):
            os.remove(pdfp)
        b = subprocess.run([sys.executable, "build_brief_v2.py", "content_v2.json", "market_data.json", "hero_data.json", base + ".pdf"],
                           cwd=WORK, capture_output=True, text=True)
        log = (b.stdout + b.stderr)[-1500:]
        npg = re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", pdfp], capture_output=True, text=True).stdout or "") if os.path.exists(pdfp) else None
        ok = b.returncode == 0 and npg and npg.group(1) == "2"
        print(f"build [{label}]:", "ok" if ok else f"rejected (exit {b.returncode}, pages {npg.group(1) if npg else '?'})")
        if ok:
            sec["TXT"] = t
            break
    if not ok:
        alert(f"Build failed for {STAMP}", f"Builder exit {b.returncode}. Nothing was sent.\n\n{log}"); print(log); return 1
    p = subprocess.run([sys.executable, "pulse_check.py", "content_v2.json", "market_data.json", "hero_data.json", base + ".pdf",
                        "--txt", base + ".txt", "--today", ISO], cwd=WORK, capture_output=True, text=True)
    plog = p.stdout.strip()
    if p.returncode != 0:
        alert(f"Pulse check FAILED for {STAMP}", "Nothing was sent.\n\n" + plog); print(plog); return 1
    pages = re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", pdfp], capture_output=True, text=True).stdout).group(1)
    lay = hashlib.sha1(subprocess.run(["pdftotext", "-layout", pdfp, "-"], capture_output=True, text=True).stdout.encode()).hexdigest()[:12]
    words = len(sec["TXT"].split()); kb = os.path.getsize(pdfp) // 1024
    if DRY:
        os.makedirs(os.path.join(WORK, "out"), exist_ok=True)
        shutil.copy(pdfp, os.path.join(WORK, "out", base + ".pdf"))
        print(plog); print("[dry run] built", pages, "pages", kb, "KB; nothing sent, no marker written")
        return 0
    subject = f"Morning Briefing - {NOW.strftime('%A')}, {NOW.strftime('%d %B %Y')}"
    msg = EmailMessage(); msg["From"] = USER; msg["To"] = ", ".join(RECIP)
    if MODE == "test":
        msg["Subject"] = "[CLOUD TEST] " + subject
        foot = f"\n\n--- cloud build check ---\npages {pages} | words {words} | pdf {kb} KB | layout {lay}\n{plog.splitlines()[-1] if plog else ''}\n"
        msg.set_content(sec["TXT"] + foot)
    else:
        msg["Subject"] = subject; msg.set_content(sec["TXT"])
    msg.add_attachment(open(pdfp, "rb").read(), maintype="application", subtype="pdf", filename=base + ".pdf")
    smtp_send(msg)
    json.dump({"mode": MODE, "sentAt": NOW.strftime("%H:%M"), "pages": int(pages), "words": words, "kb": kb, "layout": lay,
               "pulse": plog.splitlines()[-1] if plog else "", "recipients": len(RECIP)}, open(MARK, "w"))
    print("sent", MODE, pages, "pages", kb, "KB", lay)
    return 0


if __name__ == "__main__":
    sys.exit(detect() if sys.argv[1:] == ["detect"] else send())
