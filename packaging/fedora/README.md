# Fedora COPR packaging

Papyrus needs `mpvpaper`, which is not currently available from Fedora's
official package set. Build both RPMs into the same COPR project so DNF can
resolve the dependency:

- `mpvpaper.spec` builds the upstream mpvpaper 1.9 source used by Papyrus.
- `papyrus.spec` packages the Papyrus release and requires `mpvpaper`.

## Build locally

On Fedora, install the RPM build tools and create SRPMs from both specs:

```bash
sudo dnf install rpm-build rpmdevtools
rpmdev-setuptree
spectool -g -R packaging/fedora/mpvpaper.spec
spectool -g -R packaging/fedora/papyrus.spec
rpmbuild -bs packaging/fedora/mpvpaper.spec
rpmbuild -bs packaging/fedora/papyrus.spec
```

`spectool` downloads each spec's versioned source archive. Check that both
SRPMs were created under `~/rpmbuild/SRPMS/` before submitting them.

## Publish to COPR

Create a Fedora Account System account and a COPR project (suggested name:
`papyrus`). Configure `copr-cli`, then submit the two SRPMs to the same project:

```bash
copr-cli build papyrus ~/rpmbuild/SRPMS/mpvpaper-1.9-1*.src.rpm
copr-cli build papyrus ~/rpmbuild/SRPMS/papyrus-1.3.7-1*.src.rpm
```

Build `mpvpaper` first and wait for it to succeed before submitting Papyrus.
After the project is published, Fedora users can enable it and install Papyrus:

```bash
sudo dnf copr enable YOUR_FEDORA_USERNAME/papyrus
sudo dnf install papyrus
```

Update the Papyrus `Version` in its spec for each Papyrus release. Update the
mpvpaper spec only when Papyrus moves to a different upstream mpvpaper version.
