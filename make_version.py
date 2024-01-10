'''
Simple python script to dynamically add version tag to HTML files
'''

import os.path
from datetime import datetime

def apply_version_tag(filepath, version_tag):
    if not os.path.isfile(filepath):
        print(f'Not a file! {filepath}')
        return False

    with open(filepath, 'r') as template:
        content = template.read()

    content = content.replace('{{VU_VERSION}}', version_tag)

    with open(filepath, 'w') as stamped:
        # Writing data to a file
        stamped.write(content)

    return True


if __name__ == '__main__':
    dt = datetime.now()
    version_tag = dt.strftime('%Y%m%d')
    footer_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'www', 'views', 'footer.html')
    apply_version_tag(footer_path, version_tag)
