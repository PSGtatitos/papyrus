%global debug_package %{nil}

Name:           papyrus
Version:        2.0.0
Release:        1%{?dist}
Summary:        Animated wallpaper manager for Wayland compositors
License:        GPL-3.0-or-later
URL:            https://github.com/PSGtatitos/papyrus
Source0:        https://github.com/PSGtatitos/papyrus/archive/refs/tags/v%{version}.tar.gz
BuildArch:      noarch

Requires:       mpvpaper
Requires:       python3
Requires:       python3-gobject
Requires:       python3-pillow
Requires:       gtk4
Requires:       libadwaita
Requires:       ffmpeg-free

%description
Papyrus is a GTK4/libadwaita application for managing animated and static
wallpapers on Wayland compositors that support the required layer-shell
protocol. It uses mpvpaper to render wallpaper files behind the desktop.

%prep
%autosetup -n papyrus-%{version}

%build
# The application is a single Python script and needs no build step.

%install
install -Dpm 0755 papyrus.py %{buildroot}%{_bindir}/papyrus
install -Dpm 0644 io.github.PSGtatitos.papyrus.desktop \
    %{buildroot}%{_datadir}/applications/io.github.PSGtatitos.papyrus.desktop
install -Dpm 0644 io.github.PSGtatitos.papyrus.metainfo.xml \
    %{buildroot}%{_datadir}/metainfo/io.github.PSGtatitos.papyrus.metainfo.xml
install -Dpm 0644 assets/icon.png \
    %{buildroot}%{_datadir}/icons/hicolor/256x256/apps/io.github.PSGtatitos.papyrus.png

%files
%license LICENSE
%{_bindir}/papyrus
%{_datadir}/applications/io.github.PSGtatitos.papyrus.desktop
%{_datadir}/metainfo/io.github.PSGtatitos.papyrus.metainfo.xml
%{_datadir}/icons/hicolor/256x256/apps/io.github.PSGtatitos.papyrus.png

%changelog
* Tue Oct 27 2026 Papyrus maintainers <psgtatitos@github> - 2.0.0-1
- Initial COPR package
