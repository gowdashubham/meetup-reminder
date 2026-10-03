# Meetup soccer RSVP reminders

For every upcoming game in the **Diamond Bar / Hacienda Heights Pick-Up Soccer**
Meetup group, your phone gets three pushes around the moment RSVPs open:

| Push | When | Example (Oct 11 game) |
|---|---|---|
| **RSVPs open in 1 hour** | 1 hour before | Wed Oct 7, 5:20:00 PM |
| **RSVPs open in 15 seconds** | 15 seconds before | Wed Oct 7, 6:19:45 PM |
| **RSVPs are OPEN** | the moment they open | Wed Oct 7, 6:20:00 PM |

Tap the last one and hit **Attend**.

## How it works
- Once an hour, a free GitHub Action reads each upcoming game's RSVP opening
  time from its public Meetup page. No login, and it never RSVPs for you.
- It hands the three pushes to **ntfy's server** with exact delivery times, so
  they arrive on the second even though GitHub only runs roughly hourly.
- ntfy can only hold messages up to 3 days ahead, so reminders get scheduled
  about 3 days before RSVPs open.
- If the organizer moves the opening time, the next run moves the reminders.
  If a game is cancelled, its reminders are cancelled. If RSVPs open
  earlier than announced, you get an "OPEN (early)" push within the hour.

Your laptop can stay off.

## Setup (about 5 minutes)

### 1. Phone notifications
Reuse your courthouse ntfy topic, or make a new one:
1. Install the free **ntfy** app (iOS / Android).
2. Pick a long, unguessable topic name, e.g. `soccer-alerts-q8z3m1`, and subscribe to it in the app.
3. **iPhone:** in Settings → Notifications → ntfy, allow notifications, and turn on
   **Time Sensitive** so the urgent ones come through Focus modes.
   **Android:** allow ntfy to ignore battery optimization so pushes aren't delayed.

### 2. GitHub repo
Create a new repo (private is fine, since hourly runs stay well within the free
minutes) and push this folder:
```bash
cd meetup-checker
git init && git add . && git commit -m "Meetup RSVP reminders"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

### 3. Add your topic as a secret
Repo → **Settings → Secrets and variables → Actions → New repository secret**
- Name: `NTFY_TOPIC`, Value: your topic name

### 4. Test it
Repo → **Actions → Check Meetup soccer → Run workflow**. You'll get a
"Meetup checker is working" push listing each upcoming game and when its
RSVPs open.

## Knowing it's running
- **Actions** tab: a new row about every hour labeled `schedule`, green ✓ = fine.
  Click one → **check → Check Meetup** to see the opening times it found and
  which reminders it scheduled.
- If Meetup changes its pages and the check breaks, you get a
  "Meetup checker failed" push.

## Options
Repo → **Settings → Secrets and variables → Actions → Variables**:
- `REMINDERS`: seconds before opening, comma-separated. Default `3600,15`.
  E.g. `3600,300,15` adds a 5-minute warning.
- `TITLE_FILTER`: only games whose title contains this, e.g. `Sunday`.
- `MEETUP_GROUP_URL`: use a different group.

## Good to know
- Stay logged in to Meetup on your phone and already be a group member, so the
  "OPEN" tap goes straight to an RSVP button.
- Phone pushes usually arrive within a second or two of the scheduled time, but
  that depends on Apple/Google, so treat the 15-second warning as approximate.
