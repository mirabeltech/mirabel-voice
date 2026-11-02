# 0.9.6: Installs on Windows 11 on ARM, with dependency security updates

The installer used to refuse every computer that wasn't x64, which ruled out Windows on ARM laptops such as those with Snapdragon X chips. Windows 11 on ARM can run x64 apps under emulation, so the installer now accepts it and the app's startup check looks at what Python was built for rather than the physical CPU. Windows 10 on ARM is still refused because it can't emulate x64. There is no native ARM64 build.

Microphone capture, the global shortcut and text injection under emulation have not yet been tested on a real ARM computer. That check is open in the [acceptance record](windows-acceptance.md).

The dependency audit flagged new advisories, so the runtime moves to certifi 2026.10.18 and Pillow 13.0.0, and the build tools move to certifi 2026.10.18, filelock 4.2.1, msgpack 1.2.3 and setuptools 84.1.0.

Because the runtime dependencies changed, this is not a source update. Existing installations need the new Python ZIP: quit Mirabel Voice, download the ZIP from the company drive to Downloads, and run the usual install command. Until then, the app says the update needs a new Python bundle and the current copy keeps working. Preferences and credentials are kept.
