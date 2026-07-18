# Slot100 Blackstar 30m/1s Verification

## Save Artifact

- Source: `E:\Documents\GitHub\CRIMSON-DESERT-SAVE-EDITOR-AND-GAME-MODS\tests\fixtures\slot100\save.save`
- Source encrypted SHA-256: `663a3c8522c12e33d0b1e43e68a7d5ba66dd4f2b40affcf18227d7420c5ccfb6`
- Source decompressed SHA-256: `cbb0c8ab5f8a58c6628c999685a5b155b86619d44056a3213ebb581a13e232ce`
- Output: `E:\Documents\GitHub\CRIMSON-DESERT-SAVE-EDITOR-AND-GAME-MODS\tests\generated\slot100_blackstar_30m_1s\save.save`
- Output encrypted SHA-256: `70efe1c1833a48438f748cf8d377252b472f041ed0f0c16e0d5c1fe4cf2abb68`
- Output decompressed SHA-256: `b9a5ef56e6c6b6537a8e5dd908f1f2ae42c90bb0bea8aa88410f80ff3299f8fd`
- Backup: `E:\Documents\GitHub\CRIMSON-DESERT-SAVE-EDITOR-AND-GAME-MODS\tests\generated\slot100_blackstar_30m_1s\backups\save.save.20260716_162411_061915.bak`
- Backup SHA-256: `663a3c8522c12e33d0b1e43e68a7d5ba66dd4f2b40affcf18227d7420c5ccfb6`
- Compatibility family: `blackstar-owner-114-v1`
- Schema SHA-256: `97b086ba545981e2678a91ae7eb81237681c8842fbe04e6d75a5f2ee1513a004`
- Structural schema match: `true`
- Intentional observed-encoding change: legitimate idle Blackstar element mask added
- Blackstar state: `legacy -> legitimate_idle`
- Blackstar record bytes: `206 -> 437`
- Mount records: `80 -> 80`
- Knowledge records: `3201 -> 3201`
- Call Dragon: `present level 1 -> present level 1`
- Quest semantic changes: `0`
- Knowledge semantic changes: `0`
- Save byte growth: `231`
- Allocated mercenary number: `1000798`
- Allocated equipment item number: `1000799`
- Second-run action: `none`
- Second-run byte growth: `0`

## Timer Mod

- JSON: `E:\Documents\GitHub\CRIMSON-DESERT-SAVE-EDITOR-AND-GAME-MODS\tests\generated\slot100_blackstar_30m_1s\Blackstar_30m_1s_1.14.json`
- JSON SHA-256: `f74558e14d3368f7ff8f92eee66bfbadf1d7c190062da2c9cde9a8b5e84a9f03`
- Source characterinfo size: `26431464`
- Source characterinfo SHA-256: `e234565b744fb1bb304547b5883cf9249c6cfff54c034c2611a87da26d8324d2`
- Source header size: `56842`
- Source header SHA-256: `f774cd93b0cd865297918b849472d276bd5a04355fdf908b541b043a40a5ab22`
- Candidate characterinfo SHA-256: `c90f6689c0aa757efa702e51669be8ff9ff0ab58a4393bc220ee390903fa1402`
- Loader-resolved PAZ: `D:\SteamLibrary\steamapps\common\Crimson Desert\0008\0.paz`
- Original compressed slot size: `1194691` bytes
- Candidate recompressed size: `793285` bytes
- Recompression headroom: `401406` bytes
- Target: `Riding_Dragon_1` / key `1000799`
- Cooldown: `3600 -> 1` second at offset `25579991`
- Mounted duration: `600 -> 1800` seconds at offset `25579999`
- Raw changed offsets: `25579991, 25579992, 25579999, 25580000`
- Other character semantic changes: `0`
- Installed game writes by Codex: `0`

## Source Preservation

- Fixture encrypted hash after generation: `663a3c8522c12e33d0b1e43e68a7d5ba66dd4f2b40affcf18227d7420c5ccfb6` (unchanged)
- Installed characterinfo body hash after validation: `e234565b744fb1bb304547b5883cf9249c6cfff54c034c2611a87da26d8324d2` (unchanged)
- Installed characterinfo header hash after validation: `f774cd93b0cd865297918b849472d276bd5a04355fdf908b541b043a40a5ab22` (unchanged)
- `lobby.save` changes: `0`
- Live save writes: `0`
- Live PAPGT/PAMT/PAZ writes: `0`
