# Legal notice

This notice concerns the GitHub repository **nic034/ngtstudio** and the **NGT Studio** software published in it
(article 6 of French law no. 2004-575 of 21 June 2004 on confidence in the digital economy).

## 1. Publisher and contact

- **Publisher**: Nicolas, alias **Nic034**, author of the software. A personal project, distributed free of charge.
- **Contact**: through an issue on this repository (<https://github.com/nic034/ngtstudio/issues>) or the GitHub profile
  <https://github.com/nic034>. Author's website: <https://nic034.fr>.
- **Publication director**: the publisher.

## 2. Host

The repository is hosted by **GitHub, Inc.**, 88 Colin P. Kelly Jr. Street, San Francisco, CA 94107, USA
(<https://github.com>). Browsing data on GitHub is processed by GitHub under its own privacy policy.

## 3. License and intellectual property

- The NGT Studio code is published under the **MIT License** (file [`LICENSE`](LICENSE)), © 2026 Nicolas (Nic034).
- The MIT License **does not cover** some items (built-in pictures, games, BIOS, music, third-party components): see [`NOTICE.md`](NOTICE.md).
- Third-party libraries keep their own licenses: [`sources/THIRD_PARTY_NOTICES.md`](sources/THIRD_PARTY_NOTICES.md).

## 4. SNK, game publishers and developers: rights and absence of affiliation

**Rights holders.** Neo Geo, SNK, the console BIOS, the games, their titles, characters, logos, artwork, music, sounds and sound data are
protected works and trademarks. They belong to **SNK Corporation** (formerly SNK Playmore) as far as it is concerned and, for the other
games released on Neo Geo, to **their respective publishers, developers and composers** or their successors. NGT Studio claims no right over
these items, and the MIT License of the code **grants no right** over them.

**No affiliation.** NGT Studio is an independent fan project. It is **not affiliated with, endorsed, sponsored or approved** by SNK, by any
game publisher or developer, or by MAME, Darksoft, NeoSD, Yamaha, libretro or Arcade Database. These names (and YM2610) belong to their
respective owners and are used only to say what NGT Studio works with or where it fetches information from. The game titles shown by the
software and the screenshots fetched from the Internet belong to their owners.

**What this repository does not contain.** No Neo Geo game (ROM), BIOS, music, audio file, screenshot or game code. The built-in pictures
that show SNK hardware or a SNK game (the game box and the console of the screen saver) are © SNK and are not licensed under the MIT
License: see [`NOTICE.md`](NOTICE.md).

**What the user must do.**
- Have their **own** romsets and their **own** `neogeo.zip`, legally obtained. NGT Studio is not meant for piracy and provides no way to
  obtain games or BIOS files.
- Use the `.ngt` albums and the jukebox ROMs built with the software for **personal use only**. These files contain music data taken from the
  games (protected works) and, for the ROMs, two items of the BIOS: **do not distribute, publish or sell them**. This project does not authorise
  the distribution or sale of cartridges or files containing the music or the BIOS of a game, and grants no right to do so.
- Comply with the law of their country (copyright, private-copy exceptions, technical protection measures): they are **solely
  responsible**. The publisher of the software gives no legal advice.

**Removal on request.** If you are a rights holder (SNK, publisher, developer, composer) and believe that an item in this repository
infringes your rights, write to the publisher (see 1) and name the item: it will be reviewed and promptly removed if necessary.

## 5. Other trademarks

The other product or company names mentioned in this repository (Python, Windows, GitHub, etc.) belong to their respective owners.

## 6. Personal data and network access

- NGT Studio **collects no personal data**, has no account, advertising or statistics, and sends nothing to the publisher.
- The software works locally. It connects to the Internet only in the following cases:
  - **First launch**: automatic installation of the missing Python modules (`numpy`, `sounddevice`, `Pillow`, `soundfile`) from PyPI.
  - **Player**: fetching game screenshots from `thumbnails.libretro.com` and the full title of a game from the Arcade Database
    (`adb.arcadeitalia.net`; the game's short MAME name, for example `kof98`, is sent). Like any web server, these servers see your IP
    address and a `NGT-Studio/<version>` user agent. Without a connection the software works without this information.
  - **Manual diagnostic command** `--probe-pics` (only if you run it): also queries a Google image search.
- Files written on your computer: names cache `~/.ngt_studio_names.json`, cache `~/.ngt_studio_pics_index.json`, diagnostic log
  `ngt_studio.log` (next to the program, otherwise in the temporary folder; version, system, errors; never sent anywhere), and a temporary
  pictures folder deleted when the program closes. You can delete these files at any time.

## 7. Warranty and liability

The software is provided **"as is", without warranty of any kind** (see the MIT License). The jukebox cartridge was tested in MAME and on a
Darksoft Multi-AES, but **not on every real hardware or every flash cartridge**: you use it at your own risk, and the publisher cannot be held
liable for any damage to a console, a cartridge, files or data.

## 8. Governing law

This notice and the use of this repository are governed by French law, subject to the mandatory provisions applicable to the user in their
country of residence.
