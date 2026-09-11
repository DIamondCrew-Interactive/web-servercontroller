#!/usr/bin/env python3
"""Build overlays from installed upstream files. No host configuration is read."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

SOURCE = Path(__file__).resolve().parents[1]
LINK = '<link rel="stylesheet" href="{href}" data-dci-theme="1">'
BRAND = ('<div class="dci-brand" aria-label="DiamondCrew Interactive — Server Controller">'
         '<img src="../dci_theme/logo.png" alt="">'
         '<div><strong>DiamondCrew<br>Interactive</strong><small>Server Controller</small></div></div>')
DISCORD = ('<div id="dci-discord-options"><a class="dci-discord-button" id="dci-discord-login" '
           'href="#" aria-disabled="true">Continue with Discord</a>'
           '<p id="dci-discord-status" class="dci-discord-status" role="status"></p>'
           '<div class="dci-login-separator"><span id="dci-login-or">or</span></div></div>')


def patch_login(text):
    if 'dci-discord-options' in text:
        raise ValueError('Login already themed')
    text, count = re.subn(r'(<div id="login" class="login-area" hidden>\s*)', lambda m: m[0] + DISCORD, text)
    if count != 1:
        raise ValueError('Unknown login layout')
    pattern = r'(\s*</div>\s*)(<div class="details" id="login-details" hidden>.*?</div>)'
    text, count = re.subn(pattern, lambda m: '\n' + m[2] + '\n<p class="dci-login-motto">Create. Play. Together.</p>' + m[1], text, flags=re.S)
    if count != 1:
        raise ValueError('Unknown login details layout')
    return text.replace('</head>', '<script src="cockpit/static/dci-login.js"></script>\n</head>')


def patch_catalog(text, translations):
    for key, value in translations.items():
        encoded = json.dumps(key, ensure_ascii=False)
        alternatives = re.escape(encoded)
        if re.fullmatch(r'[A-Za-z_$][\w$]*', key):
            alternatives += '|' + re.escape(key)
        pattern = r'(?<![\w$])(' + alternatives + r'):(\[(?:null|""),)"(?:[^"\\]|\\.)*"(\])'
        text = re.sub(pattern, lambda m: m[1] + ':' + m[2] + json.dumps(value, ensure_ascii=False) + m[3], text)
    return text


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(upstream, names):
    result = {}
    for name in names:
        folder = upstream / name
        if not (folder / 'manifest.json').is_file():
            raise ValueError(f'Missing Cockpit package: {name}')
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                # Reject links outside the installed package, avoiding accidental secret copies.
                if not path.resolve().is_relative_to(upstream.resolve()):
                    raise ValueError(f'External package symlink: {path}')
                result[path.relative_to(upstream).as_posix()] = digest(path)
    return result


def patch_html(text, relative):
    if 'data-dci-theme=' in text:
        raise ValueError(f'Input already themed: {relative}')
    if len(re.findall(r'</head\s*>', text, re.I)) != 1:
        raise ValueError(f'Expected one HTML head: {relative}')
    # Relative to each HTML document, including nested module pages.
    depth = len(Path(relative).parts) - 1
    href = '../' * depth + 'dci_theme/theme.css'
    text = re.sub(r'</head\s*>', LINK.format(href=href) + '\n</head>', text, flags=re.I)
    if relative == 'shell/index.html':
        pattern = r'(<nav\s+id="host-apps"[^>]*>)'
        text, count = re.subn(pattern, lambda m: BRAND + '\n' + m[0], text)
        if count != 1:
            raise ValueError('Unknown shell navigation layout')
    return text


def build(upstream, output, source=SOURCE):
    upstream, output = Path(upstream).resolve(), Path(output).resolve()
    config = json.loads((source / 'compatibility.json').read_text())
    names = config['packages']
    before = inventory(upstream, names)
    if output.exists():
        raise ValueError(f'Output must not exist: {output}')
    output.mkdir(parents=True)
    patched = []
    catalogs = []
    translations = json.loads((source / 'src/locales/cs.json').read_text(encoding='utf-8'))
    try:
        for name in names:
            shutil.copytree(upstream / name, output / 'packages' / name)
            for path in sorted((output / 'packages' / name).rglob('*')):
                relative = path.relative_to(output / 'packages').as_posix()
                if path.name.endswith(('.html', '.html.gz')):
                    compressed = path.suffix == '.gz'
                    raw = gzip.decompress(path.read_bytes()) if compressed else path.read_bytes()
                    changed = patch_html(raw.decode('utf-8'), relative.removesuffix('.gz')).encode('utf-8')
                    path.write_bytes(gzip.compress(changed, mtime=0) if compressed else changed)
                    patched.append(relative)
                elif path.name == 'po.cs.js.gz':
                    original = gzip.decompress(path.read_bytes()).decode('utf-8')
                    changed = patch_catalog(original, translations)
                    if changed != original:
                        path.write_bytes(gzip.compress(changed.encode('utf-8'), mtime=0))
                        catalogs.append(relative)
        theme = output / 'packages' / 'dci_theme'
        theme.mkdir()
        shutil.copyfile(source / 'src/theme.css', theme / 'theme.css')
        shutil.copyfile(source / 'src/assets/logo.png', theme / 'logo.png')
        version = (source / 'VERSION').read_text().strip()
        (theme / 'manifest.json').write_text(json.dumps({'version': version, 'requires': {'cockpit': '287.1'}}) + '\n')
        branding = output / 'branding'
        branding.mkdir()
        (branding / 'branding.css').write_bytes((source / 'src/theme.css').read_bytes() + b'\n' + (source / 'src/branding.css').read_bytes())
        shutil.copyfile(source / 'src/assets/logo.png', branding / 'dc-logo.png')
        login_source = upstream / 'static/login.html.dci-original'
        if not login_source.exists():
            login_source = upstream / 'static/login.html'
        if not login_source.exists():
            raise ValueError('Missing upstream login.html')
        (branding / 'login.html').write_text(patch_login(login_source.read_text(encoding='utf-8')), encoding='utf-8', newline='\n')
        (branding / 'dci-login.js').write_bytes((source / 'src/login.js').read_bytes())
        shutil.copytree(source / 'discord/ui', output / 'packages/dci_discord')
        after = inventory(upstream, names)
        if before != after:
            raise ValueError('Upstream changed during build; retry outside package upgrades')
        report = {'theme_version': version, 'cockpit_version': config['cockpit_version'],
                  'upstream_sha256': before, 'patched_html': patched, 'patched_catalogs': catalogs,
                  'login_sha256': digest(login_source), 'packages': names + ['dci_theme', 'dci_discord']}
        (output / 'build.json').write_text(json.dumps(report, indent=2) + '\n')
        # Consistent permissions even with root umask 077.
        for path in output.rglob('*'):
            path.chmod(0o755 if path.is_dir() else 0o644)
        output.chmod(0o755)
        return report
    except BaseException:
        shutil.rmtree(output)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', type=Path, default=Path('/usr/share/cockpit'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = build(args.upstream, args.output)
    print(f"Built {len(report['patched_html'])} HTML overlays and {len(report['patched_catalogs'])} Czech catalog overrides; upstream application code preserved.")
