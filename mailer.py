#!/usr/bin/env python3
"""Audi Capital Daily Brief - cloud mailer.
Finds today's BRIEF-PACKAGE email (sent by the cloud writer to the owner's own mailbox), rebuilds the PDF with the
same builder, runs the checks and emails the brief. Modes:  detect | send
Secrets (env): GMAIL_USER, GMAIL_APP_PASSWORD, PACKAGE_TOKEN, RECIPIENTS_TEST, RECIPIENTS_LIVE.  BRIEF_MODE: test|live."""
import datetime as dt, email, email.utils, hashlib, imaplib, json, os, re, shutil, smtplib, subprocess, sys, time
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
# pipeline alerts go to the owner's own mailbox only, never to the brief's other recipients
OWNER = [USER] if USER else [a.strip() for a in os.environ.get("RECIPIENTS_TEST", "").split(",") if a.strip()][:1]
RECIP = [a.strip() for a in os.environ.get("RECIPIENTS_LIVE" if MODE == "live" else "RECIPIENTS_TEST", "").split(",") if a.strip()] or OWNER
MARK = os.path.join(HERE, "sent", f"{STAMP}-{MODE}.json")
DRY = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")   # build and check only: no email, no markers
ALERT = os.path.join(HERE, "sent", f"{STAMP}-alert.json")
# Ralph, 26.10.2026: "never hold a brief, resolve it". Every package is repaired where code can repair it (kit/repair.py),
# built and sent; what no code can fix is reported to the owner afterwards, never a reason to stop.
# pulse_check classes that mean a reader would see a wrong, repeated, unsourced or non-compliant line
BLOCKING = ("FACTS", "REPETITION", "CONTRADICTION", "TEASER", "CAUSE", "CURRENCY", "VALUE", "COMPLIANCE")
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


def already_emailed():
    """True when today's brief is already in the owner's Sent mail: the guard that still holds if the sent/ marker
    was not visible to this run (25.10.2026: two runs a minute apart both sent the brief)."""
    subject = f"Morning Briefing - {NOW.strftime('%A')}, {NOW.strftime('%d %B %Y')}"
    try:
        M = imaplib.IMAP4_SSL("imap.gmail.com"); M.login(USER, PW); M.select('"[Gmail]/Sent Mail"', readonly=True)
        typ, d = M.search(None, "X-GM-RAW", f'"subject:(\\"{subject}\\") newer_than:1d"')
        M.logout()
        return typ == "OK" and bool(d[0].split())
    except Exception as e:
        print("sent-mail check skipped:", type(e).__name__)
        return False


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
    m = re.search(r"=====\s*LEDGER\s*=====\r?\n(.*?)\r?\n=====", body, re.S)
    s["LEDGER"] = m.group(1).strip() if m else ""
    m = re.search(r"=====\s*SOURCES\s*=====\r?\n(.*?)\r?\n=====", body, re.S)
    s["SOURCES"] = m.group(1).strip() if m else ""
    m = re.search(r"=====\s*FACTS\s*=====\r?\n(.*?)\r?\n=====", body, re.S)
    s["FACTS"] = m.group(1).strip() if m else ""
    m = re.search(r"=====\s*SEARCHES\s*=====\r?\n(.*?)\r?\n=====", body, re.S)
    s["SEARCHES"] = m.group(1).strip() if m else ""
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


def data_check_alert():
    """Once a day, tell the owner which prices the feed's cross-check could not confirm (crosscheck.py)."""
    mark = os.path.join(HERE, "sent", f"{STAMP}-datacheck.json")
    if os.path.exists(mark) or not (USER and PW):
        return
    try:
        md = json.load(open(os.path.join(HERE, "market_data.json"), encoding="utf-8-sig"))
    except Exception:
        return
    if md.get("generatedAt", "")[:10] != ISO:
        return
    flagged = [i["check"] for i in md.get("items", []) if i.get("check")]
    fixed = [f"{i['name']} {i['asOf']}: {i['corrected']['from']} -> {i['corrected']['to']} ({i['corrected']['why']})"
             for i in md.get("items", []) if i.get("corrected")]
    if not flagged and not fixed:
        return
    body = ""
    if flagged:
        body += ("Unconfirmed (no two sources agree), so the brief must not print or chart them today (pulse_check "
                 "enforces it):\n" + "\n".join("- " + f for f in flagged) + "\n\n")
    if fixed:
        body += ("Corrected (the feed's figure disagreed, two other sources agree; the brief uses the corrected "
                 "figure):\n" + "\n".join("- " + f for f in fixed) + "\n")
    alert(f"{'Unconfirmed' if flagged else 'Corrected'} prices {STAMP}", body)
    os.makedirs(os.path.dirname(mark), exist_ok=True)
    json.dump({"flagged": flagged}, open(mark, "w")); out("commit", "true")
    print("unconfirmed-price alert sent")


THREAD_NAMES = {}  # thread id -> newsletter name as in kit/newsletters.txt (filled by newsletter_coverage)


def canonical_newsletter(thread_id, written):
    """The newsletters.txt name for a SOURCES line: by its thread's sender when the inbox was read, else by matching
    the name the writer typed ("Bloomberg Evening" -> "Bloomberg", "Exec Sum" -> "Exec Sum - Litquidity")."""
    if thread_id.lower() in THREAD_NAMES:
        return THREAD_NAMES[thread_id.lower()]
    try:
        sys.path.insert(0, os.path.join(HERE, "kit"))
        import enrich
        names = list(dict.fromkeys(n for n, _ in enrich.newsletters()))
    except Exception:
        return written
    w = re.sub(r"[^a-z ]", " ", written.lower()).split()
    best = max(names, key=lambda n: len(set(w) & set(re.sub(r"[^a-z ]", " ", n.lower()).split()) - {"the", "daily", "news"}), default=written)
    return best if set(w) & set(re.sub(r"[^a-z ]", " ", best.lower()).split()) - {"the", "daily", "news"} else written


def newsletter_coverage(sources):
    """Check the writer's reading against the inbox: every newsletter (kit/newsletters.txt) that arrived in the 24
    hours before the package was sent, versus the thread ids the package marks READ. Returns (read, arrived, missed
    names) or None when the inbox cannot be read."""
    try:
        sys.path.insert(0, os.path.join(HERE, "kit"))
        import enrich
        senders = enrich.newsletters()
        names = {a.lower(): n for n, a in senders}
        M = imaplib.IMAP4_SSL("imap.gmail.com"); M.login(USER, PW); M.select('"[Gmail]/All Mail"')
        typ, d = M.search(None, "X-GM-RAW", f'"subject:BRIEF-PACKAGE {STAMP} from:{USER}"')
        pk = d[0].split() if typ == "OK" else []
        if not pk:
            M.logout(); return None
        typ, dd = M.fetch(pk[-1], "(INTERNALDATE)")
        sent_at = imaplib.Internaldate2tuple(dd[0])
        sent_ts = time.mktime(sent_at)
        typ, d = M.search(None, "X-GM-RAW", '"' + enrich.newsletter_query(days=2) + '"')
        arrived = {}
        for i in (d[0].split() if typ == "OK" else []):
            typ, f = M.fetch(i, "(X-GM-THRID INTERNALDATE BODY.PEEK[HEADER.FIELDS (FROM)])")
            head = f[0][0].decode() if isinstance(f[0], tuple) else ""
            ts = time.mktime(imaplib.Internaldate2tuple(f[0][0]))
            if not sent_ts - 24 * 3600 <= ts <= sent_ts:
                continue
            thr = format(int(re.search(r"X-GM-THRID (\d+)", head).group(1)), "x")
            frm = email.utils.parseaddr(email.message_from_bytes(f[0][1]).get("From", ""))[1].lower()
            arrived[thr] = names.get(frm, frm)
        M.logout()
        read = {l.split("|")[0].strip().lower() for l in sources.splitlines() if "|" in l and "READ" in l.split("|")[1].upper()}
        missed = sorted({arrived[t] for t in arrived if t not in read})
        THREAD_NAMES.update(arrived)
        return len([t for t in arrived if t in read]), len(arrived), missed
    except Exception as e:
        print("newsletter check skipped:", type(e).__name__, e)
        return None


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
    data_check_alert()
    if USER and PW and already_emailed():
        print("today's brief is already in Sent; not sending again")
        os.makedirs(os.path.dirname(MARK), exist_ok=True)
        json.dump({"mode": MODE, "note": "found in Sent by a later run"}, open(MARK, "w")); out("commit", "true")
        out("found", "false"); return 0
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
    for f in ("build_brief_v2.py", "extras_v2.py", "pulse_check.py", "brief_v2.css", "wordmark.png", "circles.png",
              "NotoSansArabic-Regular.ttf", "NotoSansArabic-Bold.ttf"):
        shutil.copy(os.path.join(HERE, "kit", f), WORK)
    for f in ("market_data.json", "series.json"):
        shutil.copy(os.path.join(HERE, f), WORK)
    base = f"Audi Capital Daily Brief - {STAMP}"
    txtp = os.path.join(WORK, base + ".txt"); pdfp = os.path.join(WORK, base + ".pdf")
    content, hero, txt = json.loads(sec["CONTENT"]), json.loads(sec["HERO"]), sec["TXT"]
    md = json.load(open(os.path.join(WORK, "market_data.json"), encoding="utf-8-sig"))
    fixes = []
    if md.get("generatedAt", "")[:10] != ISO:
        # a stale feed is refreshed here rather than failing the build
        r = subprocess.run([sys.executable, "fetch_market_data.py"], cwd=HERE, capture_output=True, text=True, env=dict(os.environ, FORCE="1"))
        subprocess.run([sys.executable, "make_series.py"], cwd=HERE, capture_output=True, text=True, env=dict(os.environ, NO_BACKFILL="1"))
        for f in ("market_data.json", "series.json"):
            shutil.copy(os.path.join(HERE, f), WORK)
        md = json.load(open(os.path.join(WORK, "market_data.json"), encoding="utf-8-sig"))
        fixes.append(f"market data was stale; refreshed here (now {md.get('generatedAt', '?')}, fetch exit {r.returncode})")
    try:
        sys.path.insert(0, os.path.join(HERE, "kit"))
        import repair
        content, txt, rl = repair.all_repairs(content, txt, md)
        fixes += rl
    except Exception as e:
        fixes.append(f"repairs skipped ({type(e).__name__}: {e})")
    for f_ in fixes:
        print("repair:", f_)
    # Bring the package up to the desktop standard (enrich.py), then build the richest variant that still passes
    # the builder's overlap check and fits 2 pages (plus the fixed disclaimer page 3). The last variant is the package exactly as sent.
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
    try:
        if content.get("top3") or any(x.get("type") == "numday" for s_ in ("extras_left", "extras_right")
                                      for x in content.get("p1", {}).get(s_, []) or []):
            for lab, c_un in enrich.unhooked(content):
                variants.append((lab, c_un, hero, txt))
    except Exception as e:
        print("enrich: unhooked variants skipped:", type(e).__name__, e)
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
        ok = b.returncode == 0 and npg and npg.group(1) == "3"   # the 2-page brief and the disclaimer page
        print(f"build [{label}]:", "ok" if ok else f"rejected (exit {b.returncode}, pages {npg.group(1) if npg else '?'})")
        if ok:
            sec["TXT"] = t
            break
    if not ok:
        # Ralph, 26.10.2026: "everything should be clockwork" - a PDF with the disclaimer page always goes out.
        # Second pass: the richest variant that built 3 pages even if the overlap check complained (a label touching
        # a line beats no PDF); last: the fallback layout, the text brief in house style plus the disclaimer page,
        # which needs no charts or market data.
        fallback = None
        for label, c, h, t in variants:
            json.dump(c, open(os.path.join(WORK, "content_v2.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            json.dump(h, open(os.path.join(WORK, "hero_data.json"), "w", encoding="utf-8"), ensure_ascii=False)
            open(txtp, "w", encoding="utf-8").write(t)
            if os.path.exists(pdfp):
                os.remove(pdfp)
            b = subprocess.run([sys.executable, "build_brief_v2.py", "content_v2.json", "market_data.json", "hero_data.json", base + ".pdf"],
                               cwd=WORK, capture_output=True, text=True)
            npg = re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", pdfp], capture_output=True, text=True).stdout or "") if os.path.exists(pdfp) else None
            if npg and npg.group(1) == "3":
                ok, fallback = True, f"layout '{label}' sent despite builder exit {b.returncode}"
                sec["TXT"] = t
                break
        if not ok:
            open(txtp, "w", encoding="utf-8").write(txt)
            fb = subprocess.run([sys.executable, "build_brief_v2.py", "--fallback", base + ".txt", content.get("date", STAMP.replace(".", "-")), base + ".pdf"],
                                cwd=WORK, capture_output=True, text=True)
            ok = os.path.exists(pdfp)
            fallback = "fallback layout (text brief and disclaimer page)" if ok else None
            log += "\n" + (fb.stdout + fb.stderr)[-800:]
        if ok:
            fixes.append("no designed layout passed every check; sent " + fallback)
            print("build: fallback ->", fallback)
        else:
            # the PDF engine itself is broken (the morning canary should have reported it): the text still goes out
            print(log)
            if DRY:
                print("[dry run] no PDF could be built; would send the text brief"); return 0
            msg = EmailMessage(); msg["From"] = USER; msg["To"] = ", ".join(RECIP)
            subject = f"Morning Briefing - {NOW.strftime('%A')}, {NOW.strftime('%d %B %Y')}"
            msg["Subject"] = ("[CLOUD TEST] " if MODE == "test" else "") + subject
            msg.set_content(txt)
            smtp_send(msg)
            json.dump({"mode": MODE, "sentAt": NOW.strftime("%H:%M"), "pdf": False, "recipients": len(RECIP)}, open(MARK, "w"))
            alert(f"Brief sent as text only {STAMP}", f"No PDF could be built, not even the fallback layout.\n\n{log}")
            print("sent", MODE, "text only"); return 0
    # the writer's sandbox normally runs the full check before sending; when its shell was down it sends the package
    # marked "PRECHECK: not run" and this run does the full check (ledger, sources, facts and the page audit) instead
    unchecked = bool(re.search(r"^PRECHECK:\s*not run", body.split("=====TXT=====")[0], re.M | re.I))
    pargs = ["--txt", base + ".txt", "--today", ISO]
    lp = os.path.join(HERE, "sent", "ledger.txt")
    if os.path.exists(lp):
        shutil.copy(lp, os.path.join(WORK, "ledger.txt")); pargs += ["--ledger", "ledger.txt"]
    # the full check runs here on every package (26.10.2026: a package reported "PASS, no warnings" while every fact
    # cited a newsletter tracking link); searches.txt sits next to sources.txt, where pulse_check looks for it
    open(os.path.join(WORK, "searches.txt"), "w", encoding="utf-8").write(sec.get("SEARCHES", "") + "\n")
    for name, fn in (("SOURCES", "sources.txt"), ("FACTS", "facts.txt")):
        open(os.path.join(WORK, fn), "w", encoding="utf-8").write(sec.get(name, "") + "\n"); pargs += ["--" + name.lower(), fn]
    shutil.copy(os.path.join(HERE, "kit", "factcheck.py"), WORK)
    p = subprocess.run([sys.executable, "pulse_check.py", "content_v2.json", "market_data.json", "hero_data.json", base + ".pdf"]
                       + pargs, cwd=WORK, capture_output=True, text=True)
    plog = p.stdout.strip()
    fails = [l.strip()[5:].strip() for l in plog.splitlines() if l.strip().startswith("FAIL")]
    blocking = [l.strip()[5:].strip() for l in plog.splitlines()
                if l.strip().startswith("WARN") and l.strip()[5:].strip().startswith(BLOCKING)]
    hard = [l.strip()[5:].strip() for l in plog.splitlines() if l.strip().startswith("WARN")
            and l.strip()[5:].strip().startswith(BLOCKING + ("DESKTOP STANDARD", "SOURCES", "HOOKS", "THEME"))]
    if unchecked:
        print("precheck: not run by the writer; full check run here,", len(blocking), "blocking warning(s)")
    if (fixes or fails or hard) and not DRY:
        alert(f"Brief report {STAMP}: {len(fixes)} repaired, {len(fails) + len(hard)} for the writer",
              "The brief was sent.\n\n"
              + ("Repaired automatically before sending:\n" + "\n".join("- " + f_ for f_ in fixes) + "\n\n" if fixes else "")
              + ("Left for the writer (its next run reads lessons.txt):\n" + "\n".join("- " + w for w in fails + hard) if fails or hard else ""))
    pages = re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", pdfp], capture_output=True, text=True).stdout).group(1)
    lay = hashlib.sha1(subprocess.run(["pdftotext", "-layout", pdfp, "-"], capture_output=True, text=True).stdout.encode()).hexdigest()[:12]
    words = len(sec["TXT"].split()); kb = os.path.getsize(pdfp) // 1024
    cov = newsletter_coverage(sec.get("SOURCES", "")) if (USER and PW) else None
    # reading is selective by design (Ralph, 20.10: core newsletters in full, the rest skimmed); report only, no alert
    covline = f"newsletters read in full: {cov[0]} of {cov[1]} that arrived in the 24 hours before the package" if cov else "newsletters: not checked"
    print(covline)
    # independent fact audit: every cited page is opened here, outside the writer, and the logged figure looked up
    try:
        sys.path.insert(0, os.path.join(HERE, "kit"))
        import factcheck
        audit = factcheck.audit(sec.get("FACTS", "").splitlines())
        factline = factcheck.summary(audit)
        doubts = [r for r in audit if r[1] in ("NOT FOUND", "PARTIAL", "NO SOURCE")]
        for lead, st, u, n in audit:
            print(f"  {st:<12} {lead[:50]:<50} {', '.join(n[:3])} {u[:80]}")
    except Exception as e:
        audit, doubts, factline = [], [], f"fact audit: skipped ({type(e).__name__})"
    print(factline)
    if doubts and not DRY:
        alert(f"Fact audit for {STAMP}: {len(doubts)} item(s) to check",
              "The brief was sent. These facts were not confirmed on the page the writer cited "
              "(NOT FOUND: the page opened but the figure is not on it; PARTIAL: only some figures are; NO SOURCE: no page cited):\n\n"
              + "\n".join(f"- {st}: {lead} | figures {', '.join(n)} | {u}" for lead, st, u, n in doubts)
              + "\n\nPages that could not be opened (paywalls, blocks) are listed in the test footer and the run log, not here.")
    if DRY:
        os.makedirs(os.path.join(WORK, "out"), exist_ok=True)
        shutil.copy(pdfp, os.path.join(WORK, "out", base + ".pdf"))
        print(plog); print("[dry run] built", pages, "pages", kb, "KB; nothing sent, no marker written")
        return 0
    subject = f"Morning Briefing - {NOW.strftime('%A')}, {NOW.strftime('%d %B %Y')}"
    msg = EmailMessage(); msg["From"] = USER; msg["To"] = ", ".join(RECIP)
    if MODE == "test":
        msg["Subject"] = "[CLOUD TEST] " + subject
        pre = ("writer precheck: not run (shell down), checked here" if unchecked else "writer precheck: run") + (f" | {len(fixes)} repaired here" if fixes else "")
        foot = f"\n\n--- cloud build check ---\npages {pages} | words {words} | pdf {kb} KB | layout {lay}\n{plog.splitlines()[-1] if plog else ''}\n{pre}\n{covline}\n{factline}\n"
        msg.set_content(sec["TXT"] + foot)
    else:
        msg["Subject"] = subject; msg.set_content(sec["TXT"])
    msg.add_attachment(open(pdfp, "rb").read(), maintype="application", subtype="pdf", filename=base + ".pdf")
    smtp_send(msg)
    json.dump({"mode": MODE, "sentAt": NOW.strftime("%H:%M"), "pages": int(pages), "words": words, "kb": kb, "layout": lay,
               "pulse": plog.splitlines()[-1] if plog else "", "recipients": len(RECIP),
               "precheck": "not run" if unchecked else "run", "repaired": fixes,
               "newsletters": {"read": cov[0], "arrived": cov[1], "not_read": cov[2]} if cov else None,
               "facts": {"summary": factline, "doubts": [f"{st}: {lead}" for lead, st, u, n in doubts]}}, open(MARK, "w"))
    # chart-rotation memory: one ledger line per sent edition, kept in the repo so the writer never loses days
    led = next((l.strip() for l in sec.get("LEDGER", "").splitlines() if re.match(r"\d\d-\d\d-\d{4}:", l.strip())), "")
    if led:
        lp = os.path.join(HERE, "sent", "ledger.txt")
        old_l = open(lp, encoding="utf-8").read().splitlines() if os.path.exists(lp) else []
        old_l = [l for l in old_l if not l.startswith(led[:10])]
        open(lp, "w", encoding="utf-8").write("\n".join((old_l + [led])[-30:]) + "\n")
    # newsletter yield memory: which newsletters gave stories to the brief, so the writer's reading order learns
    stl = []
    for l in sec.get("SOURCES", "").splitlines():
        f = [x.strip() for x in l.split("|")]
        u = re.search(r"used\s*=\s*(\d+)", l)
        if len(f) >= 3 and f[1].upper() in ("READ", "SKIMMED"):
            stl.append(f"{STAMP.replace('.', '-')} | {canonical_newsletter(f[0], f[2])} | {f[1].upper()} | {u.group(1) if u else 0}")
    if stl:
        sp = os.path.join(HERE, "sent", "newsletter_stats.txt")
        old_s = open(sp, encoding="utf-8").read().splitlines() if os.path.exists(sp) else []
        old_s = [l for l in old_s if not l.startswith(STAMP.replace('.', '-'))]
        open(sp, "w", encoding="utf-8").write("\n".join((old_s + stl)[-1200:]) + "\n")
    print("sent", MODE, pages, "pages", kb, "KB", lay)
    return 0


def canary():
    """Morning test build (Ralph, 26.10.2026: "everything should be clockwork"): after the market feed refreshes and
    before the writer starts, build a stored sample edition and the fallback layout with today's tools and fonts.
    Anything broken is reported to the owner while there is still time to fix it."""
    d = os.path.join(HERE, "work", "canary")
    shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    for f in ("build_brief_v2.py", "extras_v2.py", "brief_v2.css", "wordmark.png", "circles.png",
              "NotoSansArabic-Regular.ttf", "NotoSansArabic-Bold.ttf"):
        shutil.copy(os.path.join(HERE, "kit", f), d)
    for f in ("content_v2.json", "hero_data.json", "market_data.json", "brief.txt"):
        shutil.copy(os.path.join(HERE, "kit", "canary", f), d)
    shutil.copy(os.path.join(HERE, "series.json"), d)
    problems = []
    b = subprocess.run([sys.executable, "build_brief_v2.py", "content_v2.json", "market_data.json", "hero_data.json", "c.pdf"],
                       cwd=d, capture_output=True, text=True)
    npg = re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", os.path.join(d, "c.pdf")], capture_output=True, text=True).stdout or "")
    if not npg or npg.group(1) != "3":
        problems.append(f"designed layout: builder exit {b.returncode}, pages {npg.group(1) if npg else 'none'}\n{(b.stdout + b.stderr)[-1200:]}")
    f = subprocess.run([sys.executable, "build_brief_v2.py", "--fallback", "brief.txt", "01-01-2026", "f.pdf"],
                       cwd=d, capture_output=True, text=True)
    if not os.path.exists(os.path.join(d, "f.pdf")):
        problems.append(f"fallback layout: exit {f.returncode}\n{(f.stdout + f.stderr)[-1200:]}")
    fonts = subprocess.run(["pdffonts", os.path.join(d, "c.pdf")], capture_output=True, text=True).stdout if npg else ""
    if npg and "AR" not in fonts:
        problems.append("the Arabic font is missing from the disclaimer page")
    if problems:
        print("canary: FAILED\n" + "\n\n".join(problems))
        alert(f"Morning test build failed {STAMP}", "The test build before today's edition found a problem; the brief may not "
              "build as designed at 09:47 until it is fixed:\n\n" + "\n\n".join(problems))
        return 1
    print("canary: designed layout 3 pages, fallback layout built, Arabic font embedded")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["canary"]:
        sys.exit(canary())
    sys.exit(detect() if sys.argv[1:] == ["detect"] else send())
