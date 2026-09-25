'''
Stamps the build date into the Web UI footer and the NSIS installer before packaging.
'''

from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def stamp(path, mapping):
    '''Replace each placeholder in `path` with its value. Raises if the file is missing.'''
    content = path.read_text(encoding='utf-8')
    for placeholder, value in mapping.items():
        content = content.replace(placeholder, value)
    path.write_text(content, encoding='utf-8')
    print(f'Stamped {path}')


if __name__ == '__main__':
    dt = datetime.now()
    stamp(ROOT / 'www' / 'views' / 'footer.html', {'{{VU_VERSION}}': dt.strftime('%Y%m%d')})
    stamp(ROOT / 'installer' / 'install.nsi', {
        '{{VU_VERSION_MAJOR}}': dt.strftime('%Y'),
        '{{VU_VERSION_MINOR}}': dt.strftime('%m'),
        '{{VU_VERSION_BUILD}}': dt.strftime('%d'),
    })
