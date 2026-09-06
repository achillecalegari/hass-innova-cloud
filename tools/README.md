# Re-analysis toolkit

If a new app version changes the protocol, these scripts rebuild the schema in minutes from the
app binary (install the iPad app on an Apple-silicon Mac, it is unencrypted apart from 4 KB):

```bash
python tools/extract_namemaps.py /Applications/Innova.app/Wrapper/Innova.app/Innova   # field numbers
python tools/swift_fields.py   /Applications/Innova.app/Wrapper/Innova.app/Innova   # field types
strings -n 4 .../Innova | grep -E '^(messages|services)\.'                          # message and service names
```

Hostnames are not literals in the binary (they come from a per-brand configuration); find them
in the app's URL cache (`~/Library/Containers/tech.solutiontech.Innova/Data/Library/Caches/`)
or probe candidates with `scripts/innova_cli.py`. The Android APK (`tech.solutiontech.innova`)
is an alternative source: its protobuf descriptors are recoverable with standard tools.

See `docs/PROTOCOL.md` for the current findings and `docs/ROBUSTNESS.md` for how the integration
behaves when the cloud misbehaves.
