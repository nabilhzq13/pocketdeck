# PocketDeck

Turn your phone or iPad into a Stream Deck for your Windows PC. Launch apps, press shortcuts,
control volume, brightness, music, windows and SteelSeries Sonar from a touch screen next to
your keyboard.

A small server runs on the PC. Your phone opens it in the browser over your home Wi-Fi: there
is no app to install on the phone, no account, and nothing leaves your network.

## What it can do

| | |
| --- | --- |
| **Apps** | Launch any app from the Start menu (Store apps too) with its real icon, plus websites, files, folders and Windows settings pages. With two screens, choose which screen the app opens on |
| **Keyboard** | Any shortcut (`ctrl+shift+s`, or sequences like `ctrl+k ctrl+c`), type text, send text to the PC clipboard or read it back |
| **Audio** | Master volume, mute, microphone mute, per-app volume, switch the output device, media keys, now playing with album art |
| **SteelSeries Sonar** | Channel sliders and mutes, switch each channel's EQ preset, choose the speakers or headset Sonar plays through (only when SteelSeries GG is installed) |
| **Display** | Brightness for laptop screens and monitors (DDC/CI), laptop only / duplicate / extend / second screen only, dark mode, screen off |
| **System** | CPU, memory, NVIDIA GPU, battery, disk and network meters, Windows power mode, lock, sleep, restart, shut down |
| **Windows** | Every open window: tap to bring it forward, minimize or close it. If an app keeps running in the system tray after closing, PocketDeck offers to quit it completely |
| **Trackpad** | Use the phone as a touchpad and keyboard |
| **Macros** | Several actions in a row with pauses in between |

Every button and page can be changed on the phone: long-press a button, then drag it around,
or tap it to change what it does.

## Requirements

- A Windows 10 or 11 PC
- Python 3.11 or newer. If it's missing, `start.bat` offers to install it for you
- A phone or tablet with a web browser (iPhone, iPad, Android), on the same Wi-Fi as the PC

## Install

1. **Download.** On this page, click **Code**, then **Download ZIP**. Right-click the ZIP,
   choose **Properties**, tick **Unblock**, and click OK. Unzip it to a folder you'll keep,
   such as `Documents\PocketDeck`.
2. **Start it.** Double-click `start.bat`. The first time, it installs what it needs into a
   `.deps` folder inside PocketDeck, which takes about a minute. Nothing is installed
   system-wide.
   - If Windows says *"Windows protected your PC"*, click **More info**, then **Run anyway**.
   - If Windows Firewall asks about Python, tick **Private networks** and click **Allow**.
3. **Pair your phone.** A pairing page opens on the PC. Scan its QR code with your phone's
   camera.
4. **Make it an app.** On iPhone or iPad, tap **Share**, then **Add to Home Screen**. On Android,
   open the browser menu and tap **Add to Home screen**.
5. **Keep it running (optional).** Double-click `autostart.bat`. PocketDeck then starts hidden
   whenever you sign in to Windows, and restarts by itself if it ever crashes.

| File | What it does |
| --- | --- |
| `start.bat` | Start PocketDeck in a window (first run also installs it) |
| `autostart.bat` | Start hidden with Windows. `autostart.bat off` turns this off |
| `stop.bat` | Stop the hidden background copy |
| `allow-firewall.bat` | Let phones on your network connect, if the firewall still blocks them |

To pair another device later, open `http://localhost:8765/pair` on the PC.

## Using it

- **Pages:** tap the tabs at the bottom, or swipe left and right.
- **Edit:** long-press any button. The icons wiggle and you can drag them to new spots, or drop
  one on a page tab to move it to that page. Tap a button to change its label, action, icon,
  colour or screen. Use **+** to add buttons or panels, and tap the current page tab to rename,
  reorder or delete the page. Tap ✓ when you're done.
- Your layout is saved on the PC in `config.json`, so every phone shows the same deck.

## If the phone can't connect

- Check that the phone and PC are on the **same Wi-Fi**.
- Run `allow-firewall.bat`. It opens port 8765 for devices on your local network only.
- Hotel, school and office Wi-Fi often block devices from reaching each other. Turn on **Mobile
  hotspot** on the PC, join it from the phone, and open the pairing page again.
- If your router gives the PC a new address, scan the QR code again. To avoid this, reserve an
  address for the PC in your router's settings.

## Privacy and security

- Everything runs on your PC and your local network. There's no cloud service and no account.
- Each PC creates its own random pairing code (in `settings.json`). Anyone on your network who
  has it can control your PC, so don't share it. To change it, delete the `token` line in
  `settings.json` and restart PocketDeck. Every phone then has to pair again.
- Traffic between the phone and the PC is not encrypted, so only use PocketDeck on networks you
  trust.
- The phone loads its font from Google Fonts, and website buttons show icons from Google's
  favicon service. The first run downloads Python packages from PyPI.
- Personal files stay out of the download and out of git: `settings.json`, `config.json`, the
  logs and the icon cache are created on each PC and are listed in `.gitignore`.

## Good to know

- Windows doesn't let other programs press keys or move windows in apps running as
  administrator (Task Manager, for example), unless PocketDeck runs as administrator too.
- External monitor brightness needs **DDC/CI** turned on in the monitor's own menu.
- Games running in exclusive full screen can't be moved to another screen.
- SteelSeries Sonar control needs SteelSeries GG running with Sonar turned on. Volume sliders
  work in Classic mode.
- If your laptop GPU stays awake because of the NVIDIA meter, set `"gpu_stats": false` in
  `settings.json`.

## Uninstall

1. Turn off starting with Windows: click the PocketDeck folder's address bar, type `cmd`, press
   Enter, then run `autostart.bat off`.
2. Double-click `stop.bat`.
3. If you ran `allow-firewall.bat`, remove its rule. In PowerShell as administrator, run
   `Remove-NetFirewallRule -DisplayName PocketDeck`.
4. Delete the PocketDeck folder.

## Built with

[aiohttp](https://github.com/aio-libs/aiohttp), [pycaw](https://github.com/AndreMiras/pycaw),
[comtypes](https://github.com/enthought/comtypes), [psutil](https://github.com/giampaolo/psutil),
[screen-brightness-control](https://github.com/Crozzers/screen_brightness_control),
[python-qrcode](https://github.com/lincolnloop/python-qrcode) and
[PyWinRT](https://github.com/pywinrt/pywinrt).

PocketDeck is an independent project and isn't affiliated with Elgato, Corsair or SteelSeries.

## License

[MIT](LICENSE)
