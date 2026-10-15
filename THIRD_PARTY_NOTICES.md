# Third-party references

This repository is an original implementation. It does not vendor or link the
source/binaries/assets of the following investigated projects. Their code was
consulted to understand observable log formats and integration tradeoffs.

- **DeepBattler**, William-Dic: custom non-commercial terms in upstream README.
  https://github.com/william-Dic/DeepBattler
- **hearthstone-bg-tracker**, Copyright (c) 2026 Shufelt Designs LLC: MIT.
  https://github.com/shufunk-dev/hearthstone-bg-tracker
- **Battlegrounds-Match-Data**, jawslouis / benluiwj: no root LICENSE verified in
  the inspected fork; no code reused.
  https://github.com/benluiwj/Battlegrounds-Match-Data
- **Hearthstone Deck Tracker**, HearthSim: upstream README states All Rights Reserved.
  https://github.com/HearthSim/Hearthstone-Deck-Tracker
- **Firestone**, Zero-to-Heroes: no root LICENSE verified; no code reused.
  https://github.com/Zero-to-Heroes/firestone
- **hslog**, Copyright (c) Jerome Leclanche: MIT; no code reused.
  https://github.com/HearthSim/hslog

Runtime uses the Python standard library. Development dependencies are installed
separately; their licenses are distributed with their own packages. Optional
HearthstoneJSON data is supplied by the user and is not bundled in the package.

The Windows portable distribution bundles the Python runtime and a PyInstaller
bootloader. Their license texts are included in its `licenses` directory.
PyInstaller's license includes an exception for distributing bundled applications.
The source package itself does not vendor those runtimes. Optional exact-build
card metadata may also be downloaded at runtime; no card database is bundled.

Hearthstone and Battlegrounds names, card identifiers, and game data belong to
Blizzard Entertainment. This tool is not affiliated with or endorsed by Blizzard,
HearthSim, or the referenced projects. No statement about official approval of
third-party software is implied by use of log files.

Research commits and source links are recorded in `docs/research.md`.
