Name:           mpvpaper
Version:        1.9
Release:        1%{?dist}
Summary:        Video wallpaper renderer for Wayland compositors
License:        GPL-3.0-only
URL:            https://github.com/GhostNaN/mpvpaper
Source0:        https://github.com/GhostNaN/mpvpaper/archive/refs/tags/%{version}.tar.gz

BuildRequires:  gcc
BuildRequires:  meson
BuildRequires:  ninja-build
BuildRequires:  pkgconf-pkg-config
BuildRequires:  mpv-devel
BuildRequires:  wayland-devel
BuildRequires:  wayland-protocols-devel
Requires:       mpv-libs%{?_isa}

%description
mpvpaper is a video wallpaper program for wlroots-based Wayland compositors.
It uses libmpv to render video and image files as wallpaper surfaces.

%prep
%autosetup -n mpvpaper-%{version}

%build
CFLAGS="%{optflags} -Wno-error=incompatible-pointer-types" \
    meson setup build --prefix=%{_prefix} --buildtype=release
ninja -C build %{?_smp_mflags}

%install
DESTDIR=%{buildroot} ninja -C build install

%files
%license LICENSE
%{_bindir}/mpvpaper
%{_bindir}/mpvpaper-holder

%changelog
* Tue Oct 27 2026 Papyrus maintainers <psgtatitos@github> - 1.9-1
- Initial COPR package, built from the upstream version used by Papyrus
