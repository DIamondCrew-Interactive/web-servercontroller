#!/usr/bin/env python3
"""Offline visual fixtures using original Cockpit 287.1 CSS and login HTML."""
import argparse
import gzip
from pathlib import Path
import re
import shutil
from build import SOURCE, BRAND, patch_login


def generate(upstream, output):
    output.mkdir(parents=True, exist_ok=True)
    assets = output / 'assets'
    assets.mkdir(exist_ok=True)
    for module, file in [('shell', 'index'), ('systemd', 'overview'), ('systemd', 'services'), ('networkmanager', 'network'), ('storaged', 'storage'), ('packagekit', 'updates'), ('systemd', 'terminal')]:
        (assets / (file + '.css')).write_bytes(gzip.decompress((upstream / module / (file + '.css.gz')).read_bytes()))
    shutil.copytree(upstream / 'static/fonts', assets / 'fonts', dirs_exist_ok=True)
    shutil.copytree(upstream / 'static/fonts', output / 'static/fonts', dirs_exist_ok=True)
    shutil.copyfile(upstream / 'static/login.css', assets / 'login.css')
    shutil.copyfile(SOURCE / 'src/theme.css', assets / 'theme.css')
    shutil.copyfile(SOURCE / 'src/assets/logo.png', assets / 'dc-logo.png')
    (assets / 'branding.css').write_bytes((SOURCE / 'src/theme.css').read_bytes() + (SOURCE / 'src/branding.css').read_bytes())
    shutil.copyfile(SOURCE / 'preview/fixture.css', assets / 'fixture.css')
    shutil.copyfile(SOURCE / 'preview/fixture.js', assets / 'fixture.js')
    shutil.copyfile(SOURCE / 'src/login.js', assets / 'dci-login.js')
    login = (upstream / 'static/login.html').read_text(encoding='utf-8')
    login = re.sub(r'<script\b[^>]*>.*?</script>', '', login, flags=re.S)
    login = patch_login(login).replace('<html class="pf-theme-dark">', '<html lang="cs">')
    login = login.replace('cockpit/static/', 'assets/').replace('<title>Loading...</title>', '<title>DiamondCrew Interactive — Login preview</title>')
    login = login.replace('<h1 id="brand" class="hide-before"></h1>', '<h1 id="brand" class="hide-before">DiamondCrew Interactive</h1>')
    login = login.replace('id="login" class="login-area" hidden', 'id="login" class="login-area"')
    login = login.replace('id="error-group"', 'hidden id="error-group"')
    login = login.replace('id="login-details" hidden', 'id="login-details"')
    login = login.replace('<b id="server-name"></b>', '<b id="server-name">demo-node</b>')
    login = login.replace('<p id="login-note" class="login-note"></p>', '<p id="login-note" class="login-note">Přihlášení účtem na tomto serveru.</p>')
    login = login.replace('</body>', '<script src="assets/fixture.js"></script></body>')
    login = login.replace('</head>', '<link rel="stylesheet" href="assets/fixture.css"></head>')
    login = login.replace('<body class="login-pf">', '<body class="login-pf"><p class="preview-notice">Statický náhled · bez backendu · nepoužívejte skutečné přihlašovací údaje</p>')
    (output / 'login.html').write_text(login, encoding='utf-8')
    pages = [('overview', 'Přehled', 'overview'), ('services', 'Služby', 'services'), ('network', 'Síť', 'network'), ('storage', 'Úložiště', 'storage'), ('updates', 'Aktualizace softwaru', 'updates'), ('terminal', 'Terminál', 'terminal'), ('controls', 'Formuláře a dialogy', 'overview')]
    nav = ''.join(f'<li class="pf-c-nav__item"><a class="pf-c-nav__link" href="{key}.html" target="module">{title}</a></li>' for key, title, _ in pages)
    shell = (upstream / 'shell/index.html').read_text(encoding='utf-8')
    shell = re.sub(r'<script\b[^>]*>.*?</script>', '', shell, flags=re.S)
    shell = shell.replace('href="index.css"', 'href="assets/index.css"').replace('href="../../static/branding.css"', 'href="assets/branding.css"')
    shell = shell.replace('</head>', '<link rel="stylesheet" href="assets/fixture.css"></head>')
    shell = re.sub(r'(<body[^>]*?) hidden', r'\1', shell)
    shell = shell.replace('<!-- Navigation goes here !-->', f'<div class="pf-c-nav"><section class="pf-c-nav__section"><h2 class="pf-c-nav__section-title">Systém · ukázková data</h2><ul class="pf-c-nav__list">{nav}</ul></section></div>')
    shell = shell.replace('<nav id="host-apps"', BRAND.replace('../dci_theme/logo.png', 'assets/dc-logo.png') + '<nav id="host-apps"')
    shell = shell.replace('<!-- Hosts selector goes here !-->', '<span class="fixture-host">demo-node · Debian 12</span>')
    shell = shell.replace('<!-- Top navigation goes here !-->', '<div class="fixture-header"><span>DiamondCrew Interactive / Server Controller</span><span>Statický náhled · bez backendu</span></div>')
    shell = shell.replace('<!-- This is where the iframes appear -->', '<iframe class="container-frame" name="module" title="Náhled modulu" src="overview.html"></iframe>')
    (output / 'index.html').write_text(shell, encoding='utf-8')
    for key, title, css in pages:
        content = (SOURCE / 'preview' / (key + '.html')).read_text(encoding='utf-8')
        html = f'''<!doctype html><html class="pf-theme-dark" id="{'system-overview-page' if key == 'overview' else key + '-page'}" lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} · Static preview</title><link rel="stylesheet" href="assets/{css}.css"><link rel="stylesheet" href="assets/theme.css"><link rel="stylesheet" href="assets/fixture.css"></head><body class="pf-m-redhat-font"><main class="fixture-main"><p class="fixture-eyebrow">SERVER CONTROLLER / UKÁZKOVÁ DATA</p><h1>{title}</h1>{content}</main><script src="assets/fixture.js"></script></body></html>'''
        (output / (key + '.html')).write_text(html, encoding='utf-8')
    print(f'Offline preview: {output / "index.html"}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=SOURCE / 'build/preview')
    args = parser.parse_args()
    generate(args.upstream, args.output)
