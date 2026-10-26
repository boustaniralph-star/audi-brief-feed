# Client Portal - build prompt

Build "Client Portal": a private daily portfolio portal for Ralph Boustani, Audi Capital Wealth Management Advisory.

## Purpose
My personal start-of-day portal. When I hit Refresh it pulls live positions, prices and events from my IBKR and Robinhood connectors and recalculates every client's portfolio. Read-only toward brokers: it never places, previews or stages orders.

## 1. Structure: firm overview, then client drill-down
- Home: total AUM (USD, SAR toggle at the 3.75 peg), AUM by asset class and by client, today's top movers, a 30-day events calendar, alerts panel.
- Client page: value, Day / MTD / YTD / Inception tiles; holdings grouped by asset class (collapsible, subtotals, weight).
- Asset classes: Cash & Time Deposits, Equity, Fixed Income, Private Equity, Options, Structured Products.

## 2. Data sources
- IBKR: positions, account summary, performance (all periods).
- Robinhood: accounts, equity and option positions, portfolio cash, equity and option quotes, analyst ratings and price targets, earnings, SEC filings.
- Manual holdings entered in the portal and saved across refreshes: time deposits, off-platform bonds and sukuk, private equity, structured products, off-platform equities and options.
- Each row is tagged IBKR, Robinhood, Manual or Override.

## 3. Price overrides
Sticky until cleared, beats the live price, visible badge with the live price alongside, reason required, audit log (old, new, reason, time, who).

## 4. Performance
Day, MTD, YTD, since inception; unrealized P&L vs cost; income received; accrued interest on bonds and TDs.

## 5. Tracking and alerts
Equities: price, day change, consensus, PT average/high/low and upside, next earnings, last EPS vs estimate. Fixed income and TDs: next coupon, maturity countdown, YTM. Options: expiry countdown, moneyness, delta. Structured products: distance to barrier and autocall, next observation. PE: NAV staleness after 90 days. News: SEC filings and analyst changes; "no feed" rather than invented headlines.
Alerts: day move > 3%, PT cut, earnings within 5 days, coupon or maturity within 7 days, SP within 10% of barrier, option expiry within 14 days, stale override or NAV.

## 6. Actions: skills
Buy recommendation, Exit & replace, Trade instruction to BAS, Screen bonds, Month-end client email, Investment note. Client text follows ralph-email-style. Drafts are editable, copyable, saved to the recommendation tracker, and can be saved to Gmail drafts.

## 7. Design and rules
Dense, professional, Audi Capital navy, light and dark, phone-friendly. Last-refreshed time and per-connector status. Never fabricate prices, targets or news. Client data private to Ralph.
