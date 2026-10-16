# Kiosk runbook

## Release and deploy

1. Merge `dev` into `main` by pull request; CI must be green.
2. Tag `main`: `git tag v1.0.0 && git push origin v1.0.0`. The release workflow attaches
   `dashboard-dist.tar.gz`.
3. Deploy over Tailscale: `ssh kiosk@kiosk /opt/kiosk/deploy.sh v1.0.0`.
   It restarts the services and waits for `/health`; if that fails it restores the previous
   release and exits with an error.
4. Roll back by hand: `ssh kiosk@kiosk /opt/kiosk/deploy.sh --rollback`.

Code freeze from the evening of 20 Oct. No deploys during event hours.

## Useful commands (as kiosk, over Tailscale SSH)

| What | Command |
| --- | --- |
| Service status | `systemctl --user status kiosk-core kiosk-vision` |
| Live logs | `journalctl --user -u kiosk-core -f` |
| Restart | `systemctl --user restart kiosk-vision kiosk-core` |
| Reload the screen | `pkill -f chromium` (the launcher restarts it) |
| Load content | `KIOSK_DATA_DIR=/var/lib/kiosk /opt/kiosk/current/.venv/bin/python -m core.rag.ingest add-file FILE --title TITLE` (from `/opt/kiosk/current`) |
| Set the PIN | `KIOSK_DATA_DIR=/var/lib/kiosk /opt/kiosk/current/.venv/bin/python -m core.admin set-pin` |
| Temperature | `vcgencmd measure_temp` |

## Spare SD card

After the soak passes on 20 Oct:
1. Shut down from the dashboard (Health, then Shut down) and remove the card.
2. On a laptop, read the card to an image with Raspberry Pi Imager's "Use custom" backup tool
   or `sudo dd if=/dev/sdX of=kiosk-v1.0.0.img bs=4M status=progress`.
3. Write the image to the spare 64 GB card and boot it once on the bench Pi to confirm.
4. Label it "Kiosk v1.0.0 spare", with the date.

Swap at the venue: shut down, swap the card, power on. The spare has the same data as of
cloning time; content added after that must be re-added (or copy `/var/lib/kiosk/kiosk.db`
from the latest backup with `scp`).

## Venue setup, 21 Oct

1. Place the cabinet: power socket within 3 m, camera at about 1.6 m, nothing bright behind
   visitors.
2. Connect to the venue Wi-Fi: `sudo nmcli dev wifi connect "SSID" password "..."`.
3. Check the dashboard Health page: internet connected, camera and mic working, temperature normal.
4. Settings: tune the detection zone with the live preview while a colleague walks up and past.
5. Set the volume for the hall; check that music ducks when someone approaches.
6. Set the PIN with IIT's contact and give it to them.
7. Run the acceptance checklist below with IIT's contact, who signs it off.

## Acceptance checklist (baseline 16)

| # | Test | How to run it | Pass |
| --- | --- | --- | --- |
| 1 | Idle animation and music | Watch idle for 1 min | [ ] |
| 2 | Music ducks on approach | Walk up slowly | [ ] |
| 3 | One greeting per visitor | Walk up and stay 30 s | [ ] |
| 4 | Passer-by not greeted | Walk across at 2 m without stopping | [ ] |
| 5 | At most one follow-up | Stay silent after the greeting for 30 s | [ ] |
| 6 | Polite release | Say "no thanks"; separately, walk away mid-answer | [ ] |
| 7 | English question answered from content | Ask 3 of the FAQs | [ ] |
| 8 | Honest "I don't have that" | Ask "What's the weather on Mars?" | [ ] |
| 9 | Kids mode | Tap Kids mode, ask a question; no personal questions asked | [ ] |
| 10 | Settings gear needs a 3 s hold and PIN | Tap, then hold; wrong and right PIN | [ ] |
| 11 | Five wrong PINs lock for 5 min | Enter 5 wrong PINs | [ ] |
| 12 | New content answerable | Add a Q&A in the dashboard, ask it at once | [ ] |
| 13 | Stats match a counted run | 10 people walk up; compare Overview encounters | [ ] |
| 14 | No images or video stored | `find / -xdev \( -iname '*.jpg' -o -iname '*.png' -o -iname '*.mp4' -o -iname '*.h264' \) -newermt today 2>/dev/null` prints nothing | [ ] |
| 15 | Camera unplugged: touch and voice work | Power off, disconnect, boot, tap to talk | [ ] |
| 16 | Internet cut: offline menu | Unplug the Wi-Fi router or `nmcli radio wifi off`, ask a question | [ ] |
| 17 | Next visitor gets a clean session | After a visitor leaves, ask a follow-up-only question ("how long?") | [ ] |
| 18 | Music never over the voice | Listen during the greeting and answers | [ ] |
| 19 | 8 h without restart, under 80 °C | Soak log from 20 Oct (`tools.soak` summary, `NRestarts` = 0) | [ ] |

Signed off by: ____________________  Date: __________
