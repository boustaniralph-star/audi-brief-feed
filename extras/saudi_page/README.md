# Saudi market intelligence page (parked)

A one-page Saudi market sheet, previewed on 21.10.2026 and parked at Ralph's request. **Not part of the daily
brief**: nothing in the pipeline imports or runs these files.

- `saudi_data.py` gathers the data (run it on a GitHub runner; Yahoo and Argaam are not reachable from the writer's sandbox):
  all ~270 Tadawul stocks and the official sector indices from Yahoo (latest price from chart meta, because daily bars
  lag a session), sector membership from Argaam's company menu, Q3 results and the IPO / rights-issue pipeline from
  Argaam's tables. It prints `PREVIEW_*` JSON lines.
- `page3.py data.json out.pdf` renders the page with the brief's CSS (run it next to `kit/brief_v2.css` and `wordmark.png`).
- `sample_data_2026-10-20.json` is the data behind the 21.10 preview.

Known gaps before it could go live: dividend / AGM dates (no readable source found yet; the Saudi Exchange site
blocks automated access), weekly foreign flows (not wired), sector week / YTD use the median stock and YTD is
unvalidated (rights issues and bonus shares can distort unadjusted prices), and company display names need the
familiar Tadawul short names (Argaam's list) instead of Yahoo's.
